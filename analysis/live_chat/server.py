"""Live chat console for HW4 trace investigation.

Not a homework deliverable -- a small tool for the human reviewer to check
whether a specific trace's behavior holds up over more turns than the
original scenario scripted. Two modes:

  - Resume: pick an existing scenario id, see its recorded conversation, then
    add live follow-up turns against the real agent, running as whatever
    role/user that scenario used (so tool permissions match).
  - New: start a blank session as any role and chat freely, e.g. to try a
    scenario variation that was never generated.

Resuming does not replay the original SDK session (that session_id was never
persisted anywhere -- the scenario runner discards it after each run). It
reconstructs conversational context as plain user/assistant text turns and
seeds a fresh session with those; the model gets full context and will
re-call tools live as needed, but the exact original tool-call items are not
replayed verbatim. Live follow-up turns run against agent/db.py's real
database (whatever cartwheel normally points at) via the same build_agent()
every other entry point uses -- a write tool (issue_refund, cancel_order,
escalate_to_human) here has the same real effect it would from the CLI or
server/app.py.

Every live turn leaves cartwheel.scenario_id unset (the documented "manual
sessions leave it null" convention from server/app.py), so it can never be
pulled into the HW4 review corpus by select_traces's scenario_id grouping.

Run with:
    uv run uvicorn analysis.live_chat.server:app --port 8020
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from agents import Runner, SQLiteSession
from agents.items import ItemHelpers, MessageOutputItem, ToolCallItem, ToolCallOutputItem
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from pydantic import BaseModel

from agent import db
from agent.agent import build_agent, prompt_version
from agent.auth import ROLES, AuthContext
from agent.config import REPO_ROOT
from observability.instrument import load_env, setup_tracing

UI_DIR = Path(__file__).parent / "ui"
SCENARIO_FILES = [
    REPO_ROOT / "scenarios" / "pilot_scenarios.jsonl",
    REPO_ROOT / "scenarios" / "support_scenarios.jsonl",
]
RESULTS_FILE = REPO_ROOT / "scenarios" / "final-results.jsonl"
SAMPLES_FILE = REPO_ROOT / "analysis" / "state" / "samples.json"
LIVE_SESSIONS_DB = REPO_ROOT / ".live_chat_sessions.db"
MAX_TURNS = 12
DEFAULT_USERS = {"shopper": 1, "merchant": 9001, "support": 9501}

_tracer = trace.get_tracer("cartwheel.live_chat")
app = FastAPI(title="Cartwheel live chat console")

# live_id -> {"ctx": AuthContext, "session": SQLiteSession, "resumed_from": str | None}
_LIVE: dict[str, dict[str, Any]] = {}

_SCENARIOS: dict[str, dict[str, Any]] | None = None
_RESULTS: dict[str, dict[str, Any]] | None = None
_SAMPLES_BY_SCENARIO: dict[str, dict[str, Any]] | None = None


def _load_scenarios() -> dict[str, dict[str, Any]]:
    global _SCENARIOS
    if _SCENARIOS is None:
        out: dict[str, dict[str, Any]] = {}
        for path in SCENARIO_FILES:
            if not path.exists():
                continue
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        out[rec["id"]] = rec
        _SCENARIOS = out
    return _SCENARIOS


def _load_results() -> dict[str, dict[str, Any]]:
    global _RESULTS
    if _RESULTS is None:
        out: dict[str, dict[str, Any]] = {}
        if RESULTS_FILE.exists():
            with open(RESULTS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        out[rec["scenario_id"]] = rec
        _RESULTS = out
    return _RESULTS


def _load_samples_by_scenario() -> dict[str, dict[str, Any]]:
    global _SAMPLES_BY_SCENARIO
    if _SAMPLES_BY_SCENARIO is None:
        out: dict[str, dict[str, Any]] = {}
        if SAMPLES_FILE.exists():
            with open(SAMPLES_FILE) as f:
                for s in json.load(f):
                    sid = s.get("meta", {}).get("scenario_id")
                    if sid and sid not in out:
                        out[sid] = s
        _SAMPLES_BY_SCENARIO = out
    return _SAMPLES_BY_SCENARIO


def _historical_trace(scenario_id: str) -> list[dict[str, Any]]:
    """Best available rendering of a scenario's recorded conversation.

    Prefers an already-sampled Langfuse trace (has tool calls) over the
    plain result record (text only, from the offline scenario run log).
    """
    sample = _load_samples_by_scenario().get(scenario_id)
    if sample:
        return sample["trace"]
    result = _load_results().get(scenario_id)
    if result:
        rendered: list[dict[str, Any]] = []
        for turn in result.get("turns", []):
            rendered.append({"role": "user", "text": turn["user"]})
            rendered.append({"role": "assistant", "text": turn["agent"]})
        return rendered
    return []


def _text_history_items(rendered_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce a rendered trace to the user/assistant text items used to seed
    a resumed session. See the module docstring for why tool calls aren't
    replayed verbatim."""
    items = []
    for m in rendered_trace:
        if m["role"] in ("user", "assistant") and m.get("text"):
            items.append({"role": m["role"], "content": m["text"]})
    return items


def _resolve_user(role: str, user_id: int) -> AuthContext:
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {role!r}")
    with db.connection() as conn:
        user = db.get_user(conn, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"unknown user id: {user_id}")
    if user.role != role:
        raise HTTPException(
            status_code=400,
            detail=f"user {user_id} is role {user.role!r}, not {role!r}",
        )
    return AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)


class StartLive(BaseModel):
    scenario_id: str | None = None
    role: str | None = None
    user_id: int | None = None


@app.post("/api/live/start")
async def start_live(body: StartLive) -> dict[str, Any]:
    if body.scenario_id:
        scenario = _load_scenarios().get(body.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail=f"unknown scenario {body.scenario_id!r}")
        role = scenario["tuple"].get("role", "shopper")
        user_id = scenario["tuple"].get("user_id", DEFAULT_USERS.get(role, 1))
        history = _historical_trace(body.scenario_id)
    else:
        role = body.role or "shopper"
        user_id = body.user_id or DEFAULT_USERS.get(role, 1)
        history = []

    ctx = _resolve_user(role, user_id)
    live_id = str(uuid.uuid4())
    session = SQLiteSession(live_id, str(LIVE_SESSIONS_DB))
    seed_items = _text_history_items(history)
    if seed_items:
        await session.add_items(seed_items)

    _LIVE[live_id] = {
        "ctx": ctx,
        "session": session,
        "resumed_from": body.scenario_id,
        "history": history,
        "live_turns": [],
    }
    return {
        "live_id": live_id,
        "role": ctx.role,
        "user_id": ctx.user_id,
        "resumed_from": body.scenario_id,
        "history": history,
    }


class LiveMessage(BaseModel):
    message: str


def _render_new_items(new_items: list[Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for item in new_items:
        if isinstance(item, ToolCallItem):
            raw = item.raw_item
            name = getattr(raw, "name", None)
            args_raw = getattr(raw, "arguments", None)
            if isinstance(raw, dict):
                name = name or raw.get("name")
                args_raw = args_raw if args_raw is not None else raw.get("arguments")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = args_raw
            rendered.append({"role": "tool_call", "name": name, "arguments": args})
        elif isinstance(item, ToolCallOutputItem):
            raw = item.raw_item
            name = raw.get("name") if isinstance(raw, dict) else None
            rendered.append({"role": "tool_result", "name": name, "content": item.output})
        elif isinstance(item, MessageOutputItem):
            rendered.append({"role": "assistant", "text": ItemHelpers.text_message_output(item)})
    return rendered


@app.post("/api/live/{live_id}/message")
async def live_message(live_id: str, body: LiveMessage) -> dict[str, Any]:
    entry = _LIVE.get(live_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail="unknown or expired live session (server restarted?)"
        )
    ctx: AuthContext = entry["ctx"]
    session: SQLiteSession = entry["session"]
    agent = build_agent(ctx)
    version = prompt_version()
    with _tracer.start_as_current_span("cartwheel.live_chat_message") as span:
        if span.is_recording():
            span.set_attribute("cartwheel.session_id", live_id)
            span.set_attribute("cartwheel.user_role", ctx.role)
            span.set_attribute("cartwheel.user_id", str(ctx.user_id))
            span.set_attribute("cartwheel.prompt_version", version)
            span.set_attribute("cartwheel.manual_investigation", True)
        result = await Runner.run(
            agent, body.message, session=session, context=ctx, max_turns=MAX_TURNS
        )
    turn = [{"role": "user", "text": body.message}] + _render_new_items(result.new_items)
    entry["live_turns"].extend(turn)
    return {"live_id": live_id, "turn": turn, "reply": str(result.final_output)}


def _flatten(rendered_trace: list[dict[str, Any]]) -> str:
    lines = []
    for m in rendered_trace:
        if m["role"] in ("user", "assistant"):
            lines.append(f"{m['role']}: {m.get('text', '')}")
        elif m["role"] == "tool_call":
            lines.append(f"tool_call: {json.dumps(m.get('arguments'))}")
        elif m["role"] == "tool_result":
            lines.append(f"tool_result: {json.dumps(m.get('content'))}")
    return "\n".join(lines)


def _features(rendered_trace: list[dict[str, Any]]) -> dict[str, Any]:
    tool_calls = [m for m in rendered_trace if m["role"] == "tool_call"]
    tools = {str(m.get("name")) for m in tool_calls if m.get("name")}
    text = _flatten(rendered_trace)
    return {
        "turn_count": sum(m["role"] in ("user", "assistant") for m in rendered_trace),
        "tool_call_count": len(tool_calls),
        "distinct_tools": len(tools),
        "has_retrieval": 0,
        "tokens": len(text.split()),
    }


@app.post("/api/live/{live_id}/export")
async def export_live(live_id: str) -> dict[str, Any]:
    """Append the resumed-plus-live conversation as a new sample record in
    analysis/state/samples.json, so it shows up in the HW4 review UI's
    sidebar like any other trace, ready to open-code."""
    entry = _LIVE.get(live_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown or expired live session")
    if not entry["live_turns"]:
        raise HTTPException(status_code=400, detail="no live turns to export yet")

    full_trace = entry["history"] + entry["live_turns"]
    resumed_from = entry["resumed_from"]
    reason = (
        f"live follow-up on {resumed_from}" if resumed_from else "manual new session (live chat)"
    )
    new_trace_id = f"live-{uuid.uuid4().hex}"
    sample = {
        "trace_id": new_trace_id,
        "reason": reason,
        "trace": full_trace,
        "text": _flatten(full_trace),
        "features": _features(full_trace),
        "meta": {
            "role": entry["ctx"].role,
            "prompt_version": prompt_version(),
            "scenario_id": resumed_from,
        },
        "permalink": None,
        "flags": ["live_chat_export"],
    }

    SAMPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    samples = json.loads(SAMPLES_FILE.read_text()) if SAMPLES_FILE.exists() else []
    samples.append(sample)
    SAMPLES_FILE.write_text(json.dumps(samples, indent=2))
    global _SAMPLES_BY_SCENARIO
    _SAMPLES_BY_SCENARIO = None  # invalidate cache

    return {"trace_id": new_trace_id, "total_samples": len(samples)}


@app.get("/api/scenarios")
def list_scenarios() -> dict[str, Any]:
    out = []
    for sid, s in _load_scenarios().items():
        t = s.get("tuple", {})
        out.append(
            {
                "id": sid,
                "role": t.get("role"),
                "intent": t.get("intent"),
                "turn_count": t.get("turn_count"),
                "opening_message": s.get("opening_message"),
            }
        )
    out.sort(key=lambda r: r["id"])
    return {"scenarios": out}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.on_event("startup")
async def _startup() -> None:
    load_env()
    setup_tracing()  # no-op with a warning if LANGFUSE_PUBLIC_KEY is unset


# Mounted last so it only catches paths the API routes above don't claim.
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
