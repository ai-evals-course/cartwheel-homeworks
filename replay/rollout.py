"""Run one evaluation case against the real agent on a fresh world.

Instructor-provided and complete. This module is the shared plumbing under
the end-to-end tests (tests/eval/test_e2e.py) and the replay harness
(replay/harness.py):

  - :func:`load_cases` reads the evaluation case set in
    ``eval_cases/cases.jsonl``.
  - :func:`fresh_world` seeds a brand-new deterministic world into a
    directory and points the agent at it, restoring the previous environment
    on exit. Re-seeding is the course's sandbox reset: every rollout starts
    from the same world, and a write in one run cannot leak into the next.
  - :func:`run_case` plays one case (opening message plus scripted
    followups) through the real agent in process, and returns a transcript:
    per-turn replies, every tool call with its arguments and result, step
    count, and token usage.
  - :func:`apply_checks` executes a case's machine-readable ``checks``
    against a transcript and the end-state database. It is pure given its
    inputs, so the homework's structural tests exercise it offline.
  - :func:`judge_reply` runs one frozen Module 2 judge on a reply (a live
    model call to the judge's pinned model; only used when API keys are
    present).

Nothing here retries a verdict. A model call that fails with a transport
error raises, and the caller decides what counts as an infrastructure
failure (see replay/harness.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_CASES_PATH = REPO_ROOT / "eval_cases" / "cases.jsonl"

# The write tools of App 1. "No write before confirmation" checks look for
# exactly these names in a turn's tool calls.
WRITE_TOOLS = {"issue_refund", "cancel_order"}

REQUIRED_CASE_KEYS = {"id", "mode", "kind", "input", "initial_state", "expected"}


# ---------------------------------------------------------------------------
# The evaluation case set
# ---------------------------------------------------------------------------


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the evaluation cases used by Module 3 CI."""
    path = path or EVAL_CASES_PATH
    cases = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        missing = REQUIRED_CASE_KEYS - set(case)
        if missing:
            raise ValueError(f"{path}:{line_number}: case missing {sorted(missing)}")
        cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# The sandbox reset: a fresh world per run
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def fresh_world(root: Path) -> Iterator[Path]:
    """Seed a fresh deterministic world under ``root`` and point the agent
    at it (CARTWHEEL_DB / CARTWHEEL_POLICIES_DIR), restoring the previous
    environment on exit. Yields the database path."""
    from seed.generate import generate_world

    root.mkdir(parents=True, exist_ok=True)
    db = root / "cartwheel.db"
    policies = root / "policies"
    generate_world(scale="dev", db_path=db, policies_dir=policies)
    saved = {k: os.environ.get(k) for k in ("CARTWHEEL_DB", "CARTWHEEL_POLICIES_DIR")}
    os.environ["CARTWHEEL_DB"] = str(db)
    os.environ["CARTWHEEL_POLICIES_DIR"] = str(policies)
    try:
        yield db
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def world_reset(root: Path) -> Any:
    """A zero-argument ``reset()`` callable for the replay harness: each call
    re-seeds the same directory, so every rollout starts from the identical
    world and no write survives between rollouts."""
    from seed.generate import generate_world

    db = root / "cartwheel.db"
    policies = root / "policies"

    def reset() -> None:
        root.mkdir(parents=True, exist_ok=True)
        generate_world(scale="dev", db_path=db, policies_dir=policies)
        os.environ["CARTWHEEL_DB"] = str(db)
        os.environ["CARTWHEEL_POLICIES_DIR"] = str(policies)

    return reset


# ---------------------------------------------------------------------------
# Running one case in process
# ---------------------------------------------------------------------------


def _auth_context(case_input: dict[str, Any]) -> Any:
    from agent.auth import AuthContext

    return AuthContext(
        user_id=case_input["user_id"],
        role=case_input["role"],
        store_id=case_input.get("store_id"),
    )


def _extract_turn(new_items: list[Any]) -> dict[str, Any]:
    """Collapse one Runner turn's items into {reply, tool_calls, steps}."""
    from agents.items import MessageOutputItem

    from agent.run_items import tool_calls_from_items

    reply_parts: list[str] = []
    for item in new_items:
        if isinstance(item, MessageOutputItem):
            for part in getattr(item.raw_item, "content", []) or []:
                text = getattr(part, "text", None)
                if text:
                    reply_parts.append(text)
    return {
        "reply": "\n".join(reply_parts),
        "tool_calls": [
            {
                "name": call["name"],
                "args": json.loads(call["arguments"] or "{}"),
                "result": call.get("result"),
            }
            for call in tool_calls_from_items(new_items)
        ],
        "steps": len(new_items),
    }


def run_case(
    case: dict[str, Any],
    *,
    model: str | None = None,
    max_turns: int = 12,
    prompt_template: str | None = None,
) -> dict[str, Any]:
    """Play one evaluation case through the real agent, in process.

    The caller is responsible for the world (wrap in :func:`fresh_world` or
    call a :func:`world_reset` closure first), so that k runs of the same
    case are k independent samples from the same initial state.

    Returns a transcript dict:
        {"turns": [{"user", "reply", "tool_calls": [{"name", "args",
          "result"}], "steps"}],
         "final_reply": str, "steps": int,
         "usage": {"requests", "input_tokens", "output_tokens"}}
    """
    from agents import Runner, SQLiteSession

    from agent.agent import build_agent

    ctx = _auth_context(case["input"])
    agent = build_agent(ctx, model=model, prompt_template=prompt_template)
    messages = [case["input"]["message"], *case["input"].get("followups", [])]

    async def _run() -> dict[str, Any]:
        session = SQLiteSession(f"replay-{case['id']}")  # in-memory, per run
        turns = []
        usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        for message in messages:
            result = await Runner.run(
                agent, message, context=ctx, session=session, max_turns=max_turns
            )
            turn = _extract_turn(result.new_items)
            turn["user"] = message
            turns.append(turn)
            run_usage = result.context_wrapper.usage
            usage["requests"] += run_usage.requests
            usage["input_tokens"] += run_usage.input_tokens
            usage["output_tokens"] += run_usage.output_tokens
        return {
            "turns": turns,
            "final_reply": turns[-1]["reply"] if turns else "",
            "steps": sum(t["steps"] for t in turns),
            "usage": usage,
        }

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# The checks engine
# ---------------------------------------------------------------------------


def _all_tool_calls(transcript: dict[str, Any], turn: int | None) -> list[dict[str, Any]]:
    turns = transcript["turns"]
    if turn is not None:
        turns = turns[turn : turn + 1]
    return [call for t in turns for call in t["tool_calls"]]


def _one_check(
    check: dict[str, Any], transcript: dict[str, Any], conn: sqlite3.Connection
) -> tuple[bool, str]:
    """Run one machine-readable check. Returns (ok, description)."""
    kind = check["check"]
    reply = transcript["final_reply"]

    if kind == "no_write_tools":
        calls = _all_tool_calls(transcript, check.get("turn"))
        writes = [c["name"] for c in calls if c["name"] in WRITE_TOOLS]
        where = f"turn {check['turn']}" if check.get("turn") is not None else "any turn"
        return (not writes, f"no write tool on {where} (saw {writes or 'none'})")

    if kind == "tool_called":
        calls = _all_tool_calls(transcript, check.get("turn"))
        ok = any(c["name"] == check["name"] for c in calls)
        return (ok, f"tool {check['name']} called")

    if kind == "tool_result_permission_denied":
        for call in _all_tool_calls(transcript, None):
            result = call["result"]
            if (
                call["name"] == check["name"]
                and isinstance(result, dict)
                and result.get("error") == "permission_denied"
            ):
                return (True, f"{check['name']} denied by the access matrix")
        return (False, f"{check['name']} was never permission-denied")

    if kind == "no_refund_row":
        row = conn.execute(
            "SELECT COUNT(*) FROM refunds WHERE order_id = ?", (check["order_id"],)
        ).fetchone()
        return (row[0] == 0, f"no refund row for #{check['order_id']}")

    if kind == "refund_status":
        rows = conn.execute(
            "SELECT status FROM refunds WHERE order_id = ?", (check["order_id"],)
        ).fetchall()
        statuses = [r[0] for r in rows]
        ok = check["status"] in statuses
        return (ok, f"refund for #{check['order_id']} is {check['status']} (saw {statuses})")

    if kind == "order_not_status":
        row = conn.execute(
            "SELECT status FROM orders WHERE id = ?", (check["order_id"],)
        ).fetchone()
        status = row[0] if row else None
        return (status != check["status"], f"order #{check['order_id']} not {check['status']}")

    if kind == "reply_contains":
        return (check["text"].lower() in reply.lower(), f"reply contains {check['text']!r}")

    if kind == "reply_not_contains":
        return (
            check["text"].lower() not in reply.lower(),
            f"reply does not contain {check['text']!r}",
        )

    if kind == "reply_asks_question":
        return ("?" in reply, "reply asks a clarifying question")

    if kind == "reply_not_reveals_order":
        row = conn.execute(
            "SELECT total_cents, status FROM orders WHERE id = ?", (check["order_id"],)
        ).fetchone()
        if row is None:
            return (True, f"order #{check['order_id']} does not exist")
        total_usd = row[0] / 100
        variants = [f"${total_usd:.2f}", f"{total_usd:.2f}"]
        leaked = [v for v in variants if v in reply]
        return (not leaked, f"reply does not reveal order #{check['order_id']}'s total")

    raise ValueError(f"unknown check kind: {kind!r}")


def apply_checks(
    case: dict[str, Any], transcript: dict[str, Any], db_path: Path
) -> dict[str, Any]:
    """Execute a case's ``expected.checks`` against a transcript and the
    end-state database. Returns {"passed", "failed": [descriptions],
    "results": [(ok, description)]}. Judges are separate (:func:`judge_reply`)."""
    conn = sqlite3.connect(db_path)
    try:
        results = [
            _one_check(check, transcript, conn)
            for check in case["expected"].get("checks", [])
        ]
    finally:
        conn.close()
    failed = [desc for ok, desc in results if not ok]
    return {"passed": not failed, "failed": failed, "results": results}


# ---------------------------------------------------------------------------
# Pinned judges on a fresh reply
# ---------------------------------------------------------------------------


def _analysis_state_dir() -> Path:
    return Path(
        os.environ.get("CARTWHEEL_ANALYSIS_STATE", REPO_ROOT / "analysis" / "state")
    )


def load_frozen_judge(mode: str) -> dict[str, Any]:
    """Load the highest frozen judge version for a mode from the Module 2
    state (analysis/state/judges/). Raises if none is frozen."""
    judges_dir = _analysis_state_dir() / "judges"
    frozen = []
    for path in sorted(judges_dir.glob(f"{mode}-v*.json")):
        judge = json.loads(path.read_text())
        if judge.get("status") == "frozen":
            frozen.append(judge)
    if not frozen:
        raise FileNotFoundError(f"no frozen judge for mode {mode!r} in {judges_dir}")
    return max(frozen, key=lambda j: j.get("version", 0))


def retrieved_docs_text(transcript: dict[str, Any]) -> str:
    """Collect the policy docs the agent actually retrieved in this run, for
    the judge's context (the judge grades support, so it sees exactly what
    the agent saw)."""
    chunks: list[str] = []
    for call in _all_tool_calls(transcript, None):
        result = call["result"]
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if call["name"] == "search_help_center":
            for hit in result.get("results", []):
                chunks.append(f"[{hit['policy_id']}] {hit['title']}: {hit['snippet']}")
        elif call["name"] == "get_policy":
            chunks.append(f"[{result.get('policy_id')}] {result.get('body', '')}")
    return "\n\n".join(chunks) if chunks else "(no policy documents were retrieved)"


def judge_reply(judge: dict[str, Any], reply: str, docs: str) -> str:
    """Run one frozen judge on a reply. Returns "pass" or "fail".

    This is a live call to the judge's pinned model (a Module 2 freeze pins
    both the prompt and the model id), routed through LiteLLM like the
    course models. Callers check whether the required API key is present.
    """
    import litellm

    from agent.agent import LITELLM_COURSE_MODELS

    model = LITELLM_COURSE_MODELS.get(judge["model"], judge["model"])
    user_content = (
        f"Agent reply:\n{reply}\n\nPolicy documents retrieved in the trace:\n{docs}"
    )
    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": judge["prompt_text"]},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    text = response.choices[0].message.content or ""
    match = re.search(r'"answer"\s*:\s*"(pass|fail)"', text)
    if match:
        return match.group(1)
    lowered = text.lower()
    return "fail" if "fail" in lowered else "pass"
