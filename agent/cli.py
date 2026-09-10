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
import time

try:  # readline transparently upgrades input(): arrow keys, ctrl-a/e/k/w,
    import readline  # noqa: F401  # and up-arrow recall within this session
except ImportError:  # Windows and slim builds ship without it
    pass

from agents import RunConfig, Runner, SQLiteSession
from agents.items import RunItem
from opentelemetry import trace

from agent import db
from agent.agent import build_agent, prompt_version
from agent.auth import AuthContext
from agent.config import REPO_ROOT
from observability.instrument import load_env, setup_openai_tracing, setup_tracing

DEFAULT_USERS = {"shopper": 1, "merchant": 9001, "support": 9501}
MAX_TURNS = 12  # cap runaway loops; keeps conversations bounded
SESSIONS_DB = REPO_ROOT / ".sessions.db"
_tracer = trace.get_tracer("cartwheel.cli")


def _print_tool_calls(new_items: list[RunItem]) -> None:
    """Print each tool call and its result from one run's new items.

    `Runner.run` always returns the tool calls and their outputs on
    `result.new_items`, independent of whether tracing is configured, so
    this is accurate with or without --trace.
    """
    outputs = {
        item.call_id: item.output
        for item in new_items
        if item.type == "tool_call_output_item" and item.call_id is not None
    }
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
            print(f"  [tool] {item.tool_name}({args})")
            if item.call_id in outputs:
                print(f"    -> {outputs[item.call_id]}")


def resolve_auth(role: str, user_id: int | None) -> AuthContext:
    """Build the auth context from the users table (the injected block)."""
    with db.connection() as conn:
        user = db.get_user(conn, user_id if user_id is not None else DEFAULT_USERS[role])
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
) -> None:
    agent = build_agent(ctx, model=model, defenses=defenses)
    # main() enables callbacks for Langfuse or explicit OpenAI tracing.
    run_config = RunConfig(tracing_disabled=not tracing)
    session = SQLiteSession(
        f"cli-{ctx.role}-{ctx.user_id}-{int(time.time())}", str(SESSIONS_DB)
    )
    version = prompt_version()
    print(
        f"Cartwheel support CLI | role={ctx.role} user={ctx.user_id} "
        f"store={ctx.store_id} prompt_version={version} defenses={'on' if defenses else 'off'}"
    )
    print("Type a message, or 'quit' to exit.\n")
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

        if debug:
            _print_tool_calls(result.new_items)
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
    args = parser.parse_args()

    load_env()
    tracing = False
    if args.trace:
        tracing = setup_tracing()
    elif args.trace_openai:
        try:
            tracing = setup_openai_tracing()
        except ValueError as exc:
            parser.error(str(exc))
    ctx = resolve_auth(args.role, args.user)
    asyncio.run(
        chat(ctx, args.model, defenses=args.defenses, debug=args.debug, tracing=tracing)
    )


if __name__ == "__main__":
    main()
