"""Cartwheel trace review app (Homework 4).

A standard-library HTTP server that serves ``index.html`` and a small JSON
API over the files in ``analysis/state/``. Langfuse is the canonical trace
and score store; the state files are the committed mirror.

Data model. Cartwheel writes one Langfuse trace per user turn, so a
multi-turn scenario produces several traces. The app groups traces into
conversations by ``cartwheel.scenario_id`` (the HW3 runner opens one server
session per scenario; no trace carries ``cartwheel.session_id``), orders the
turns by timestamp, and keeps every trace id so a judgment lands on the exact
trace. Inside a turn, each GENERATION observation becomes a step holding the
model's reasoning text and its tool calls; each tool call is paired with the
TOOL observation whose name and arguments match.

Run from the repository root:

    uv run python -m analysis.review_app.server            # live Langfuse, port 8030
    uv run python -m analysis.review_app.server --offline  # read traces/support_traces.json
    uv run python -m analysis.review_app.server --refresh  # re-fetch from Langfuse

The review population is the set of trace ids in ``traces/support_traces.json``
(the HW3 final run). Live mode fetches those ids from Langfuse and caches the
raw records under ``analysis/review_app/.cache/`` (ignored by git).

API:

    GET  /api/status                   mode, counts, langfuse configured
    GET  /api/conversations            summaries for every conversation
    GET  /api/conversation/<scenario>  full conversation model
    GET  /api/spec                     SPEC.md text
    GET|POST /api/manifest             analysis/state/sample_manifest.json
    GET|POST /api/annotations          analysis/state/annotations.json
    GET|POST /api/patterns             analysis/state/patterns.json
    GET|POST /api/suggestions          analysis/state/suggestions.json
    GET  /api/labels                   every labels/<mode>.jsonl, latest per trace
    POST /api/labels                   one judgment: file line + Langfuse score
    GET  /api/hw5                      HW5 queue, definition, and labels per mode
    POST /api/hw5/label                one HW5 conversation label (1 = Pass, 0 = Fail)
    POST /api/hw5/review               my decision on one judge disagreement
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_DIR = Path(__file__).resolve().parent
STATE_DIR = ROOT / "analysis" / "state"
LABELS_DIR = STATE_DIR / "labels"
HW5_LABELS_DIR = STATE_DIR / "hw5_labels"
HW5_QUEUE_FILE = STATE_DIR / "hw5_queue.json"
HW5_REVIEW_FILE = STATE_DIR / "hw5_dev_review.jsonl"
HW5_DECISIONS = ("judge_wrong", "label_wrong", "definition_unclear")
CACHE_DIR = APP_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "traces.json"
EXPORT_FILE = ROOT / "traces" / "support_traces.json"
SCENARIO_FILE = ROOT / "scenarios" / "support_scenarios.jsonl"
SPEC_FILE = ROOT / "SPEC.md"

STATE_FILES = {
    "manifest": STATE_DIR / "sample_manifest.json",
    "annotations": STATE_DIR / "annotations.json",
    "patterns": STATE_DIR / "patterns.json",
    "suggestions": STATE_DIR / "suggestions.json",
}
STATE_DEFAULTS: dict[str, Any] = {
    "manifest": {"population": {}, "batches": []},
    "annotations": {"annotations": []},
    "patterns": {"modes": []},
    "suggestions": [],
}

_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# small file helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# ---------------------------------------------------------------------------
# trace loading
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "json") and hasattr(value, "dict"):
        return json.loads(value.json(by_alias=True))
    if hasattr(value, "dict"):
        return value.dict(by_alias=True)
    return value


def _attrs(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    attrs = metadata.get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    return attrs if isinstance(attrs, dict) else {}


def load_export() -> dict[str, Any]:
    if not EXPORT_FILE.exists():
        raise SystemExit(f"missing {EXPORT_FILE}; run the HW3 export first")
    return json.loads(EXPORT_FILE.read_text())


def load_raw_traces(offline: bool, refresh: bool) -> tuple[list[dict[str, Any]], str]:
    """Return the raw trace records and a label describing their source."""
    export = load_export()
    if offline:
        return export["traces"], "offline export"
    if CACHE_FILE.exists() and not refresh:
        cached = json.loads(CACHE_FILE.read_text())
        if cached.get("trace_count") == export["trace_count"]:
            return cached["traces"], "langfuse (cached)"
    from observability.instrument import load_env

    load_env()
    from analysis.helpers import langfuse_io

    if not langfuse_io.is_configured():
        raise SystemExit("LANGFUSE_* not configured; pass --offline to use the export")
    client = langfuse_io._client()
    ids = [t["id"] for t in export["traces"]]
    sid_by_id = {t["id"]: t.get("cartwheel_scenario_id") for t in export["traces"]}
    print(f"fetching {len(ids)} traces from Langfuse ...", flush=True)
    traces = []
    for i, trace_id in enumerate(ids, 1):
        record = _jsonable(client.api.trace.get(trace_id))
        record.setdefault("cartwheel_scenario_id", sid_by_id[trace_id])
        traces.append(record)
        if i % 50 == 0:
            print(f"  {i}/{len(ids)}", flush=True)
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / ".gitignore").write_text("*\n")
    _write_json(
        CACHE_FILE,
        {"fetched_at": _now(), "trace_count": len(traces), "traces": traces},
    )
    return traces, "langfuse (live)"


def load_scenarios() -> dict[str, dict[str, Any]]:
    out = {}
    for row in _read_jsonl(SCENARIO_FILE):
        out[row["id"]] = row
    return out


# ---------------------------------------------------------------------------
# conversation model
# ---------------------------------------------------------------------------


def _parts_text(value: Any) -> str:
    """Flatten a Langfuse message list to its text parts."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks = []
        for msg in value:
            if isinstance(msg, dict):
                for part in msg.get("parts") or []:
                    if isinstance(part, dict) and part.get("type") == "text":
                        chunks.append(str(part.get("content", "")))
        return "\n".join(chunks)
    return json.dumps(value, ensure_ascii=False)


def _ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return int((e - s).total_seconds() * 1000)
    except ValueError:
        return None


def _result_summary(name: str, out: Any) -> str:
    """One line a reviewer can read without expanding the result."""
    if not isinstance(out, dict):
        return str(out)[:160]
    if out.get("ok") is False:
        return f"error: {out.get('error')} ({out.get('reason', '')})".strip()
    bits = []
    if name == "issue_refund":
        bits = [f"status={out.get('status')}", f"refund_id={out.get('refund_id')}",
                f"amount=${out.get('amount_usd')}"]
    elif name == "cancel_order":
        bits = [f"status={out.get('status')}", f"order={out.get('order_id')}"]
    elif name == "escalate_to_human":
        bits = [f"ticket_id={out.get('ticket_id')}", f"sla_hours={out.get('sla_hours')}"]
    elif name == "get_order":
        o = out.get("order") or {}
        bits = [f"#{o.get('order_id')}", f"status={o.get('status')}",
                f"delivered={o.get('delivered_at')}", f"eligible={o.get('refund_eligible')}",
                f"${o.get('total_usd')}", str(o.get("store_name", ""))]
    elif name in {"find_order", "list_my_orders"}:
        orders = out.get("orders") or []
        bits = [f"{len(orders)} order(s): " + ", ".join(f"#{o.get('order_id')}" for o in orders[:8])]
    elif name == "search_help_center":
        res = out.get("results") or []
        bits = [f"{len(res)} result(s): " + ", ".join(str(r.get("policy_id")) for r in res[:5])]
    elif name == "get_policy":
        bits = [f"{out.get('policy_id')}: {out.get('title')}"]
    elif name == "get_store_policy":
        bits = [f"{out.get('store_name')}", f"window={out.get('return_window_days')}d",
                f"override={out.get('has_override')}", f"restocking={out.get('restocking_fee_opt_in')}"]
    elif name == "search_products":
        bits = [f"{out.get('count')} product(s)"]
    else:
        bits = [json.dumps(out, ensure_ascii=False)[:160]]
    return "  ".join(str(b) for b in bits if b not in ("", "None"))


def build_turn(trace: dict[str, Any], index: int) -> dict[str, Any]:
    attrs = _attrs(trace.get("metadata"))
    obs = sorted(trace.get("observations") or [], key=lambda o: o.get("startTime") or "")
    generations = [o for o in obs if o.get("type") == "GENERATION"]
    tools = [o for o in obs if o.get("type") == "TOOL"]
    unmatched = list(tools)

    steps = []
    for g in generations:
        reasoning: list[str] = []
        calls: list[dict[str, Any]] = []
        for msg in g.get("output") or []:
            if not isinstance(msg, dict):
                continue
            for part in msg.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and str(part.get("content", "")).strip():
                    reasoning.append(str(part["content"]))
                elif part.get("type") == "tool_call":
                    calls.append({"name": part.get("name"), "args": part.get("arguments"),
                                  "call_id": part.get("id")})
        # Pair each call with the TOOL observation of the same name and args.
        for call in calls:
            key = json.dumps(call["args"], sort_keys=True, ensure_ascii=False)
            match = None
            for t in unmatched:
                if t.get("name") == call["name"] and json.dumps(t.get("input"), sort_keys=True, ensure_ascii=False) == key:
                    match = t
                    break
            if match is None:  # fall back to the first unmatched call of that name
                match = next((t for t in unmatched if t.get("name") == call["name"]), None)
            if match is not None:
                unmatched.remove(match)
                out = match.get("output")
                t_attrs = _attrs(match.get("metadata"))
                call.update({
                    "result": out,
                    "ok": out.get("ok") if isinstance(out, dict) else None,
                    "summary": _result_summary(call["name"], out),
                    "latency_ms": _ms(match.get("startTime"), match.get("endTime")),
                    "permission_denied": t_attrs.get("cartwheel.permission_denied") == "true",
                    "observation_id": match.get("id"),
                })
            else:
                call.update({"result": None, "ok": None, "summary": "(no tool result recorded)",
                             "latency_ms": None, "permission_denied": False, "observation_id": None})
        usage = g.get("usage") or {}
        steps.append({
            "index": len(steps),
            "reasoning": reasoning,
            "calls": calls,
            "model": g.get("model"),
            "latency_ms": _ms(g.get("startTime"), g.get("endTime")),
            "tokens": usage.get("total"),
        })
    orphan_tools = [{"name": t.get("name"), "args": t.get("input"), "result": t.get("output")} for t in unmatched]

    reply = _parts_text(trace.get("output"))
    # Drop a trailing reasoning line that is identical to the final reply so it
    # is not shown twice.
    if steps and steps[-1]["reasoning"] and steps[-1]["reasoning"][-1].strip() == reply.strip():
        steps[-1]["reasoning"] = steps[-1]["reasoning"][:-1]

    return {
        "index": index,
        "trace_id": trace["id"],
        "timestamp": trace.get("timestamp"),
        "user": _parts_text(trace.get("input")),
        "reply": reply,
        "steps": steps,
        "orphan_tools": orphan_tools,
        "latency_s": trace.get("latency"),
        "permalink": trace.get("htmlPath"),
        "user_id": attrs.get("cartwheel.user_id"),
        "prompt_version": attrs.get("cartwheel.prompt_version"),
        "tool_count": sum(len(s["calls"]) for s in steps),
    }


def build_conversations(traces: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for t in traces:
        sid = t.get("cartwheel_scenario_id") or _attrs(t.get("metadata")).get("cartwheel.scenario_id")
        if not sid:
            continue
        grouped.setdefault(sid, []).append(t)

    convs: dict[str, dict[str, Any]] = {}
    for sid, group in grouped.items():
        group.sort(key=lambda t: t.get("timestamp") or "")
        scenario = scenarios.get(sid, {})
        tup = scenario.get("tuple") or {}
        role = tup.get("role") or _attrs(group[0].get("metadata")).get("cartwheel.user_role")
        turns = [build_turn(t, i) for i, t in enumerate(group)]
        system_prompt = None
        for o in group[0].get("observations") or []:
            if o.get("type") == "GENERATION":
                msgs = (o.get("input") or {}).get("messages") if isinstance(o.get("input"), dict) else None
                for m in msgs or []:
                    if isinstance(m, dict) and m.get("role") == "system":
                        system_prompt = _parts_text([m])
                        break
                break
        convs[sid] = {
            "scenario_id": sid,
            "group": scenario.get("scenario_group"),
            "data_quality_case_id": scenario.get("data_quality_case_id"),
            "role": role,
            "tuple": tup,
            "expected": scenario.get("expected") or {},
            "opening_message": scenario.get("opening_message"),
            "followups": scenario.get("followups") or [],
            "trace_ids": [t["trace_id"] for t in turns],
            "turns": turns,
            "system_prompt": system_prompt,
            "tools_used": sorted({c["name"] for t in turns for s in t["steps"] for c in s["calls"] if c.get("name")}),
            "tool_call_count": sum(t["tool_count"] for t in turns),
            "errors": [c["summary"] for t in turns for s in t["steps"] for c in s["calls"] if c.get("ok") is False],
            "features": {
                "tool_calls": sum(t["tool_count"] for t in turns),
                "steps": sum(len(t["steps"]) for t in turns),
                "turns": len(turns),
                "distinct_tools": len({c["name"] for t in turns for s in t["steps"] for c in s["calls"]}),
                "reply_chars": sum(len(t["reply"]) for t in turns),
                "user_chars": sum(len(t["user"]) for t in turns),
                "latency_s": round(sum(t["latency_s"] or 0 for t in turns), 1),
                "tool_errors": sum(1 for t in turns for s in t["steps"] for c in s["calls"] if c.get("ok") is False),
            },
            "flags": [],
        }
    return convs


FEATURE_LABELS = {
    "tool_calls": "tool calls", "steps": "model steps", "turns": "turns", "distinct_tools": "distinct tools",
    "reply_chars": "reply length", "user_chars": "user message length", "latency_s": "latency", "tool_errors": "tool errors",
}


def add_outlier_flags(convs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Flag conversations in the top or bottom 10% of a structural feature.

    Returns the dataset-level summary (percentiles) for display. A flag reads
    "12 tool calls (more than 96%)" and is only attached when the value is a
    genuine outlier, so most conversations carry zero or one flag.
    """
    stats: dict[str, Any] = {}
    n = len(convs)
    if not n:
        return stats
    for key, label in FEATURE_LABELS.items():
        values = sorted(c["features"][key] for c in convs.values())
        stats[key] = {"min": values[0], "p50": values[n // 2], "p90": values[int(0.9 * (n - 1))], "max": values[-1]}
        for c in convs.values():
            v = c["features"][key]
            below = sum(1 for x in values if x < v) / n
            above = sum(1 for x in values if x > v) / n
            if below >= 0.9 and v > stats[key]["p50"]:
                c["flags"].append({"feature": key, "value": v, "pct": below, "text": f"{v} {label} (more than {below:.0%})"})
            elif above >= 0.9 and key in {"reply_chars", "user_chars", "latency_s"} and v < stats[key]["p50"]:
                c["flags"].append({"feature": key, "value": v, "pct": above, "text": f"{v} {label} (less than {above:.0%})"})
    # Correlated features (tool calls, steps, latency) flag together; keep the
    # three most extreme so the header stays compact.
    for c in convs.values():
        c["flags"] = sorted(c["flags"], key=lambda f: -f["pct"])[:3]
    return stats


def summaries(convs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for sid in sorted(convs):
        c = convs[sid]
        out.append({
            "scenario_id": sid,
            "group": c["group"],
            "role": c["role"],
            "intent": c["tuple"].get("intent"),
            "record_state": c["tuple"].get("record_state"),
            "difficulty": c["tuple"].get("difficulty"),
            "user_style": c["tuple"].get("user_style"),
            "turns": len(c["turns"]),
            "trace_ids": c["trace_ids"],
            "tools_used": c["tools_used"],
            "tool_call_count": c["tool_call_count"],
            "error_count": len(c["errors"]),
            "features": c["features"],
            "flags": c["flags"],
            "opening": (c["turns"][0]["user"] if c["turns"] else "")[:140],
        })
    return out


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------


def read_all_labels() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not LABELS_DIR.exists():
        return out
    for path in sorted(LABELS_DIR.glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        out[path.stem] = _read_jsonl(path)
    return out


def write_label(entry: dict[str, Any], *, offline: bool) -> dict[str, Any]:
    """Store one (trace, mode) judgment: latest-per-trace file, history, score."""
    mode = entry["mode"]
    trace_id = entry["trace_id"]
    label = int(entry["label"])
    ts = _now()
    row = {
        "trace_id": trace_id,
        "label": label,
        "source": entry.get("source", "human"),
        "ts": ts,
        "label_id": f"{trace_id}#{mode}",
        "scenario_id": entry.get("scenario_id"),
        "note": entry.get("note") or None,
    }
    path = LABELS_DIR / f"{mode}.jsonl"
    with _LOCK:
        rows = [r for r in _read_jsonl(path) if r.get("trace_id") != trace_id]
        rows.append(row)
        rows.sort(key=lambda r: (str(r.get("scenario_id") or ""), r["trace_id"]))
        _write_jsonl(path, rows)
        with (LABELS_DIR / "_history.jsonl").open("a") as fh:
            fh.write(json.dumps({**row, "mode": mode}, ensure_ascii=False) + "\n")

    langfuse_status = "skipped (offline)"
    if not offline:
        try:
            from analysis.helpers import langfuse_io

            if langfuse_io.is_configured():
                langfuse_io.write_label_score(
                    trace_id=trace_id, mode=mode, label=label, comment=row["note"]
                )
                langfuse_status = "written"
            else:
                langfuse_status = "skipped (not configured)"
        except Exception as exc:  # report, do not lose the local record
            langfuse_status = f"failed: {exc}"
    return {"row": row, "langfuse": langfuse_status}


def read_hw5_judges(mode: str) -> list[dict[str, Any]]:
    """Each judge version's verdicts and critiques for ``mode``.

    Predictions use Pass = 1. Test-split predictions are withheld until the
    version is frozen, so they cannot be seen while choosing the prompt.
    """
    splits = _read_json(STATE_DIR / "splits.json", {}).get(mode, {})
    split_of = {tid: name for name in ("train", "dev", "test") for tid in splits.get(name, [])}
    out = []
    for path in sorted((STATE_DIR / "judges").glob(f"{mode}-v*.json"), key=lambda p: int(p.stem.rsplit("-v", 1)[1])):
        judge = _read_json(path, {})
        digest = judge.get("prompt_hash")
        frozen = judge.get("status") == "frozen"
        preds = (judge.get("predictions") or {}).get(digest, {})
        critiques = (judge.get("critiques") or {}).get(digest, {})
        visible = {tid for tid in preds if frozen or split_of.get(tid) != "test"}
        out.append({
            "judge_id": judge.get("judge_id"),
            "status": judge.get("status"),
            "model": judge.get("model"),
            "iterations": judge.get("iterations", []),
            "predictions": {tid: preds[tid] for tid in visible},
            "critiques": {tid: critiques.get(tid) for tid in visible},
            "withheld_test": len(preds) - len(visible),
            # Disagreements as saved when the dev run finished, so a later label
            # fix does not drop the conversation from the review list.
            "dev_disagreements": _read_json(ROOT / "analysis" / "report" / f"dev-{judge.get('judge_id')}.json", {}).get("disagreements", []),
        })
    return out


def read_hw5() -> dict[str, Any]:
    """HW5 queue, current labels, split membership, and judge verdicts per mode."""
    queue = _read_json(HW5_QUEUE_FILE, {})
    labels = {mode: _read_jsonl(HW5_LABELS_DIR / f"{mode}.jsonl") for mode in queue}
    all_splits = _read_json(STATE_DIR / "splits.json", {})
    splits = {mode: {name: all_splits.get(mode, {}).get(name, []) for name in ("train", "dev", "test")} for mode in queue}
    judges = {mode: read_hw5_judges(mode) for mode in queue}
    reviews = _read_jsonl(HW5_REVIEW_FILE)
    return {"queue": queue, "labels": labels, "splits": splits, "judges": judges, "reviews": reviews}


def write_hw5_review(entry: dict[str, Any]) -> dict[str, Any]:
    """Record my decision on one judge disagreement (latest per judge and trace)."""
    if entry.get("decision") not in HW5_DECISIONS:
        raise ValueError(f"decision must be one of {HW5_DECISIONS}")
    row = {
        "judge_id": entry["judge_id"],
        "trace_id": entry["trace_id"],
        "scenario_id": entry.get("scenario_id"),
        "decision": entry["decision"],
        "note": (entry.get("note") or "").strip() or None,
        "ts": _now(),
    }
    with _LOCK:
        rows = [r for r in _read_jsonl(HW5_REVIEW_FILE)
                if not (r["judge_id"] == row["judge_id"] and r["trace_id"] == row["trace_id"])]
        rows.append(row)
        rows.sort(key=lambda r: (r["judge_id"], str(r.get("scenario_id") or "")))
        _write_jsonl(HW5_REVIEW_FILE, rows)
    return {"row": row}


def write_hw5_label(entry: dict[str, Any]) -> dict[str, Any]:
    """Store one HW5 label per conversation (1 = Pass, 0 = Fail).

    The file keeps the latest label per conversation; every write is also
    appended to ``hw5_labels/_history.jsonl``. HW4 labels are not touched and
    no Langfuse score is written.
    """
    mode = entry["mode"]
    sid = entry["scenario_id"]
    label = int(entry["label"])
    if label not in (0, 1):
        raise ValueError("label must be 1 (Pass) or 0 (Fail)")
    row = {
        "trace_id": entry["trace_id"],
        "scenario_id": sid,
        "label": label,
        "source": "human",
        "origin": entry.get("origin") or "hw5_review",
        "rules": [r for r in entry.get("rules") or [] if isinstance(r, str)],
        "note": (entry.get("note") or "").strip() or None,
        # Evidence spans highlighted in a reply: [{"trace_id", "text"}].
        "quotes": [
            {"trace_id": str(q["trace_id"]), "text": str(q["text"])}
            for q in entry.get("quotes") or []
            if isinstance(q, dict) and q.get("trace_id") and str(q.get("text") or "").strip()
        ],
        "ts": _now(),
        "label_id": f"{sid}#{mode}",
    }
    path = HW5_LABELS_DIR / f"{mode}.jsonl"
    with _LOCK:
        rows = [r for r in _read_jsonl(path) if r.get("scenario_id") != sid]
        rows.append(row)
        rows.sort(key=lambda r: str(r.get("scenario_id") or ""))
        _write_jsonl(path, rows)
        with (HW5_LABELS_DIR / "_history.jsonl").open("a") as fh:
            fh.write(json.dumps({**row, "mode": mode}, ensure_ascii=False) + "\n")
        queue = _read_json(HW5_QUEUE_FILE, {})
        for item in queue.get(mode, {}).get("items", []):
            if item["scenario_id"] == sid:
                item["status"] = "done"
                item["target_trace_id"] = row["trace_id"]
        _write_json(HW5_QUEUE_FILE, queue)
    return {"row": row}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class App:
    def __init__(self, offline: bool, refresh: bool) -> None:
        self.offline = offline
        raw, self.source = load_raw_traces(offline, refresh)
        scenarios = load_scenarios()
        self.conversations = build_conversations(raw, scenarios)
        self.feature_stats = add_outlier_flags(self.conversations)
        self.summaries = summaries(self.conversations)
        self.trace_count = sum(len(c["trace_ids"]) for c in self.conversations.values())
        print(f"loaded {self.trace_count} traces in {len(self.conversations)} conversations from {self.source}")


APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        if "/api/" not in (args[0] if args else ""):
            return

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Any:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode() or "null")

    def do_GET(self) -> None:  # noqa: N802
        assert APP is not None
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = (APP_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            self._json({
                "source": APP.source, "offline": APP.offline,
                "trace_count": APP.trace_count, "conversation_count": len(APP.conversations),
                "state_dir": str(STATE_DIR.relative_to(ROOT)),
                "langfuse_base": os.environ.get("LANGFUSE_HOST", "").rstrip("/"),
                "feature_stats": APP.feature_stats,
            })
            return
        if path == "/api/conversations":
            self._json(APP.summaries)
            return
        if path.startswith("/api/conversation/"):
            sid = path.rsplit("/", 1)[-1]
            conv = APP.conversations.get(sid)
            if conv is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(conv)
            return
        if path == "/api/spec":
            self._json({"text": SPEC_FILE.read_text() if SPEC_FILE.exists() else ""})
            return
        if path == "/api/labels":
            self._json(read_all_labels())
            return
        if path == "/api/hw5":
            self._json(read_hw5())
            return
        key = path.replace("/api/", "", 1)
        if key in STATE_FILES:
            with _LOCK:
                self._json(_read_json(STATE_FILES[key], STATE_DEFAULTS[key]))
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        assert APP is not None
        path = urlparse(self.path).path
        try:
            data = self._body()
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, 400)
            return
        if path == "/api/labels":
            required = {"trace_id", "mode", "label"}
            if not isinstance(data, dict) or not required <= set(data):
                self._json({"error": f"need {sorted(required)}"}, 400)
                return
            self._json(write_label(data, offline=APP.offline))
            return
        if path == "/api/hw5/label":
            required = {"mode", "scenario_id", "trace_id", "label"}
            if not isinstance(data, dict) or not required <= set(data):
                self._json({"error": f"need {sorted(required)}"}, 400)
                return
            try:
                self._json(write_hw5_label(data))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return
        if path == "/api/hw5/review":
            required = {"judge_id", "trace_id", "decision"}
            if not isinstance(data, dict) or not required <= set(data):
                self._json({"error": f"need {sorted(required)}"}, 400)
                return
            try:
                self._json(write_hw5_review(data))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return
        key = path.replace("/api/", "", 1)
        if key in STATE_FILES:
            with _LOCK:
                _write_json(STATE_FILES[key], data)
            self._json({"ok": True, "saved_at": _now()})
            return
        self._json({"error": "not found"}, 404)


def main() -> None:
    global APP
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--offline", action="store_true", help="read traces/support_traces.json instead of Langfuse")
    parser.add_argument("--refresh", action="store_true", help="ignore the local cache and re-fetch from Langfuse")
    args = parser.parse_args()
    APP = App(offline=args.offline, refresh=args.refresh)
    for key, path in STATE_FILES.items():
        if not path.exists():
            _write_json(path, STATE_DEFAULTS[key])
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"review app: http://127.0.0.1:{args.port}/  (mode: {APP.source})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
