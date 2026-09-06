"""CLI chat shell for the Cartwheel support agent. Instructor-provided.

Module 1 has no graphical UI on purpose; the first UI of the course is the
error-analysis UI Module 2 builds. Chat here.

Usage:
    uv run python -m agent.cli --role shopper
    uv run python -m agent.cli --role merchant --model claude-opus-4-6
    uv run python -m agent.cli --role support --user 9502 --trace
    uv run python -m agent.cli --role support --defenses   # Module 4 guards + refund pause

Tracing is off by default. ``--trace`` uses the course's Langfuse setup;
``--trace-openai`` opts into OpenAI hosted tracing (requires OPENAI_API_KEY
and is unavailable for zero-data-retention organizations). Pick one destination.
``--debug`` prints tool calls locally and works independently of tracing.
``--save PATH`` appends one conversation draft on exit, including follow-up
turns. Recording is local and does not require tracing. Add your assessment
to the saved draft afterward.

The role picks a default demo user (shopper 1, merchant 9001, support 9501);
--user overrides it. The auth context comes from the users table, exactly as
the server would inject it. It is never taken from the chat itself.

``--defenses`` turns on the Module 4 controls (Homework 8): the input and
output guardrails and the ``needs_approval`` refund pause. It is off by
default, so the plain chat is the Module 1 agent. With it on, an
above-threshold refund pauses before the tool runs. The pause seam in ``chat``
shows the pending tool call and asks whether the tool may run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from agents import RunConfig, Runner, SQLiteSession
from agents.items import RunItem
from opentelemetry import trace

from agent import db
from agent.agent import build_agent, prompt_version, render_system_prompt
from agent.auth import AuthContext
from agent.config import REPO_ROOT
from observability.instrument import load_env, setup_tracing

DEFAULT_USERS = {"shopper": 1, "merchant": 9001, "support": 9501}
MAX_TURNS = 12  # cap runaway loops; keeps conversations bounded
SESSIONS_DB = REPO_ROOT / ".sessions.db"
_tracer = trace.get_tracer("cartwheel.cli")


def _tool_calls(new_items: list[RunItem]) -> list[dict[str, Any]]:
    """Pair this turn's function calls and results by call ID."""
    outputs = {
        item.call_id: item.output
        for item in new_items
        if item.type == "tool_call_output_item" and item.call_id is not None
    }
    calls = []
    for item in new_items:
        if item.type == "tool_call_item":
            raw = item.raw_item
            args = (
                raw.get("arguments")
                if isinstance(raw, dict)
                else getattr(raw, "arguments", None)
            )
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            call = {"name": item.tool_name, "arguments": args}
            if item.call_id in outputs:
                call["result"] = outputs[item.call_id]
            calls.append(call)
    return calls


@contextmanager
def _record_conversation(path: Path | None, ctx: AuthContext) -> Iterator[dict[str, Any]]:
    """Append one factual draft, preserving completed turns if a later run fails."""
    record: dict[str, Any] = {"turns": [], "pending_request": None}
    if path is None:
        yield record
        return
    # Open before any model calls so an unwritable destination fails early.
    with path.open("a+b") as output:
        separator = b""
        if output.tell():
            output.seek(-1, 2)
            if output.read(1) != b"\n":
                separator = b"\n"
        complete = False
        try:
            yield record
            complete = True
        finally:
            turns = record["turns"]
            if turns or record["pending_request"] is not None:
                record.update(
                    role=ctx.role, user_id=ctx.user_id, store_id=ctx.store_id,
                    request=turns[0]["request"] if turns else record["pending_request"],
                    response=turns[-1]["response"] if turns else None,
                    tool_calls=[call for turn in turns for call in turn["tool_calls"]],
                    expected=None, requirement=None, met_requirement=None, problem_source=None,
                    execution_complete=complete,
                )
                output.write(separator + json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")
                output.flush()
                if complete:
                    print(f"Conversation saved to {path}. Add your assessment to complete the record.")
                else:
                    print(f"Incomplete conversation saved to {path}; pending tool activity may be missing.")


def resolve_auth(role: str, user_id: int | None) -> AuthContext:
    """Build the auth context from the users table (the injected block)."""
    conn = db.connect()
    try:
        user = db.get_user(conn, user_id if user_id is not None else DEFAULT_USERS[role])
    finally:
        conn.close()
    if user is None:
        raise SystemExit(f"no such user id: {user_id}")
    if user.role != role:
        raise SystemExit(
            f"user {user.id} has role '{user.role}', not '{role}'; pick a matching --user"
        )
    return AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)


async def chat(
    ctx: AuthContext,
    model: str | None,
    defenses: bool = False,
    debug: bool = False,
    tracing: bool = False,
    save: Path | None = None,
) -> None:
    agent = build_agent(ctx, model=model, defenses=defenses)
    # main() enables callbacks for Langfuse or explicit OpenAI tracing.
    run_config = RunConfig(tracing_disabled=not tracing)
    session = SQLiteSession(
        f"cli-{ctx.role}-{ctx.user_id}-{uuid4().hex}", str(SESSIONS_DB)
    )
    version = prompt_version(render_system_prompt(ctx))
    print(
        f"Cartwheel support CLI | role={ctx.role} user={ctx.user_id} "
        f"store={ctx.store_id} prompt_version={version} defenses={'on' if defenses else 'off'}"
    )
    print("Type a message, or 'quit' to exit.\n")
    with _record_conversation(save, ctx) as record:
        while True:
            try:
                line = input(f"{ctx.role}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                return
            record["pending_request"] = line
            with _tracer.start_as_current_span("cartwheel.session_message") as span:
                if span.is_recording():
                    span.set_attribute("cartwheel.user_role", ctx.role)
                    span.set_attribute("cartwheel.user_id", str(ctx.user_id))
                    span.set_attribute("cartwheel.prompt_version", version)
                result = await Runner.run(
                    agent,
                    line,
                    session=session,
                    context=ctx,
                    max_turns=MAX_TURNS,
                    run_config=run_config,
                )

            # ------------------------------------------------------------------
            # Module 4 pause and resume code (Homework 8, Part D). With defenses on,
            # an above-threshold refund makes refund_needs_human return True, so
            # the SDK pauses the run instead of executing the tool and lists the
            # pending call(s) in result.interruptions (each a ToolApprovalItem).
            # A queued run is not finished: result.final_output is not the answer
            # until the interruptions are resolved and the run resumes.
            #
            # Your job (the seam below): while result has interruptions, show each
            # pending tool name and its arguments, ask whether the tool may run,
            # save the answer in a resumable state, and resume the run. The SDK
            # contract (verified, openai-agents 0.17.7):
            #
            #   state = result.to_state()
            #   for item in result.interruptions:        # ToolApprovalItem
            #       # item.tool_name names the tool. item.raw_item carries the
            #       # pending call, including its JSON arguments.
            #       state.approve(item)                  # or state.reject(item)
            #   result = await Runner.run(agent, state, context=ctx,
            #                             max_turns=MAX_TURNS, run_config=run_config)
            #
            # Loop until result.interruptions is empty (a resumed run can pause
            # again). Then fall through to printing final_output. Approving here
            # only allows the tool to run. The tool may then create a refund with
            # status queued_for_approval. A support user makes the later refund
            # decision through agent/review.py.
            # ------------------------------------------------------------------
            if getattr(result, "interruptions", None):
                ### YOUR CODE HERE (m4)
                raise NotImplementedError(
                    "m4: show each pending tool call, allow or reject it via "
                    "result.to_state(), and resume with Runner.run(agent, state, ...). "
                    "See the seam comment above."
                )

            calls = _tool_calls(result.new_items) if debug or save is not None else []
            if save is not None:
                record["turns"].append({
                    "request": line, "tool_calls": calls, "response": result.final_output,
                })
            record["pending_request"] = None
            if debug:
                for call in calls:
                    print(f"  [tool] {call['name']}({call['arguments']})")
                    if "result" in call:
                        print(f"    -> {call['result']}")
            print(f"\nagent> {result.final_output}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Cartwheel support agent.")
    parser.add_argument("--role", choices=["shopper", "merchant", "support"], default="shopper")
    parser.add_argument("--user", type=int, default=None, help="user id (defaults per role)")
    parser.add_argument(
        "--model",
        default=None,
        help="gpt-5.5 | claude-opus-4-6 | glm-5.2 (default: $CARTWHEEL_MODEL or gpt-5.5)",
    )
    tracing_options = parser.add_mutually_exclusive_group()
    tracing_options.add_argument(
        "--trace", action="store_true", help="ship spans to Langfuse (Lecture 2)"
    )
    tracing_options.add_argument(
        "--trace-openai", action="store_true",
        help="send traces to OpenAI (unavailable for zero-data-retention organizations)",
    )
    parser.add_argument(
        "--defenses",
        action="store_true",
        help="turn on the Module 4 guards and the refund approval pause (Homework 8)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print each tool call's name, arguments, and result",
    )
    parser.add_argument(
        "--save", type=Path, metavar="PATH",
        help="append one conversation draft on exit; add your own assessment afterward",
    )
    args = parser.parse_args()

    load_env()
    tracing = setup_tracing() if args.trace else args.trace_openai
    ctx = resolve_auth(args.role, args.user)
    asyncio.run(
        chat(ctx, args.model, defenses=args.defenses, debug=args.debug, tracing=tracing, save=args.save)
    )


if __name__ == "__main__":
    main()
