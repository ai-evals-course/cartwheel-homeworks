"""Fold generated Homework 5 conversations into the review interface.

Takes a runner results file plus the spans it produced, builds records in the same
shape as the Homework 4 review set, and appends them to
``analysis/review_app/records.json`` and the Homework 5 trace source.

Results and spans join on ``cartwheel.scenario_id``; the runner output does not carry
a session id but the root span does.

Idempotent: re-running replaces records for the same scenario ids rather than
duplicating them.

    .venv/bin/python analysis/tools/add_generated_records.py \\
        scenarios/hw5-wave1-results.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "analysis" / "state"
RECORDS = REPO / "analysis" / "review_app" / "records.json"
SPANS = REPO / ".hw2-logs" / "spans.jsonl"
BASELINE = REPO / ".hw5-logs" / "spans_baseline.txt"

# The lookup every refund answer depends on, and the write each outcome entails.
REQUIRED_BY_OUTCOME = {
    "refund_auto_approved": ["get_order", "issue_refund"],
    "refund_queued_for_approval": ["get_order", "issue_refund"],
    "refund_denied_past_window": ["get_order"],
    "refund_denied_store_window_stricter": ["get_order"],
}


def kind_of(span: dict) -> str:
    if span["name"].endswith(".tool"):
        return "tool"
    if span["attributes"].get("gen_ai.operation.name") == "chat":
        return "model"
    return "scaffold"


def main() -> None:
    results_path = Path(sys.argv[1])
    results = [json.loads(l) for l in results_path.read_text().splitlines() if l.strip()]

    scen_files = ["scenarios/hw5_generation_scenarios.jsonl"]
    scenarios = {}
    for f in scen_files:
        for line in (REPO / f).read_text().splitlines():
            if line.strip():
                s = json.loads(line)
                scenarios[s["id"]] = s

    start = int(BASELINE.read_text().strip())
    spans = [json.loads(l) for l in SPANS.read_text().splitlines()[start:] if l.strip()]
    # Only the root span carries cartwheel.scenario_id -- that is how Homework 2
    # instrumented it. Keying on the attribute alone drops every tool and model span,
    # so resolve the scenario through the trace id instead.
    by_trace: dict[str, list[dict]] = defaultdict(list)
    trace_scenario: dict[str, str] = {}
    for sp in spans:
        by_trace[sp["trace_id"]].append(sp)
        sid = sp["attributes"].get("cartwheel.scenario_id")
        if sid:
            trace_scenario.setdefault(sp["trace_id"], sid)
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for tid, sid in trace_scenario.items():
        by_scenario[sid].extend(by_trace[tid])

    built, skipped = [], []
    for r in results:
        scen_id = r["scenario_id"]
        s = scenarios.get(scen_id)
        group = by_scenario.get(scen_id) or []
        if not s or not group or r.get("status") != "completed":
            skipped.append(scen_id)
            continue
        group.sort(key=lambda x: x["start_time"])
        root = next((x for x in group if x["parent_span_id"] is None), group[0])
        attrs = root["attributes"]
        tools = [x for x in group if kind_of(x) == "tool"]
        called = [x["attributes"].get("gen_ai.tool.name") for x in tools]
        t = s["tuple"]
        required = REQUIRED_BY_OUTCOME.get(s["expected"].get("outcome"), [])

        turns = []
        for i, turn in enumerate(r.get("turns") or [], start=1):
            turns.append({
                "n": i,
                "trace_id": root["trace_id"],
                "user": turn.get("user"),
                "agent": turn.get("agent"),
                "steps": [{"kind": kind_of(x), "name": x["name"],
                           "duration_ms": x["duration_ms"]} for x in group],
                "span_count": len(group),
                "status": root.get("status"),
            })

        flags = []
        if len(turns) > 1:
            flags.append(f"{len(turns)} turns")
        if len(tools) >= 7:
            flags.append(f"{len(tools)} tool calls")
        if any(x["attributes"].get("cartwheel.permission_denied") is True for x in group):
            flags.append("permission denied")
        flags.append("generated for HW5")

        built.append({
            "session_id": attrs.get("cartwheel.session_id") or root["trace_id"],
            "scenario_id": scen_id,
            "group": s["scenario_group"],
            "data_quality_case_id": s.get("data_quality_case_id"),
            "role": t["role"], "user_id": t["user_id"],
            "intent": t["intent"], "difficulty": t["difficulty"],
            "user_style": t["user_style"], "access": t["access_relationship"],
            "record_state": t["record_state"],
            "expected": s["expected"],
            "turn_count": len(turns),
            "span_count": len(group),
            "tool_count": len(tools),
            "denied": any(x["attributes"].get("cartwheel.permission_denied") is True
                          for x in group),
            "no_reply": not any((x.get("agent") or "").strip() for x in turns),
            "turns": turns,
            "flags": flags,
            "tools_called": called,
            "tools_required": required,
            "tools_missing": [x for x in required if x not in called],
            "lookup_expected": bool(required),
            "lookup_done": any(c in ("get_order", "find_order") for c in called),
            "generation_shape": s.get("generation_shape"),
        })

    existing = json.loads(RECORDS.read_text())
    new_ids = {b["scenario_id"] for b in built}
    merged = [e for e in existing if e["scenario_id"] not in new_ids] + built
    RECORDS.write_text(json.dumps(merged, indent=1) + "\n")
    print(f"records.json: {len(existing)} -> {len(merged)}  (+{len(built)} generated)")
    if skipped:
        print(f"  skipped {len(skipped)} not completed or missing spans: {skipped[:5]}")
    print("  by shape:", dict(Counter(b["generation_shape"] for b in built)))
    print("  by style:", dict(Counter(b["user_style"] for b in built)))

    # Mirror into the HW5 trace source so next_to_label and the searches see them.
    src_path = STATE / "hw5_trace_source.json"
    src = json.loads(src_path.read_text())
    src = [x for x in src if x.get("cartwheel_scenario_id") not in new_ids]
    for b in built:
        group = by_scenario[b["scenario_id"]]
        src.append({
            "id": b["turns"][0]["trace_id"],
            "cartwheel_scenario_id": b["scenario_id"],
            "session_id": b["session_id"],
            "turns": [{"user": x["user"], "agent": x["agent"]} for x in b["turns"]],
            "conversation": [{"user": x["user"], "agent": x["agent"]} for x in b["turns"]],
            "observations": [{
                "type": "TOOL" if kind_of(x) == "tool" else "SPAN",
                "tool_name": x["attributes"].get("gen_ai.tool.name"),
                "tool_arguments": x["attributes"].get("gen_ai.tool.call.arguments"),
                "tool_result": x["attributes"].get("gen_ai.tool.call.result"),
                "status": x.get("status"),
            } for x in group],
        })
    src_path.write_text(json.dumps(src, indent=1) + "\n")
    print(f"hw5_trace_source.json: {len(src)} traces")


if __name__ == "__main__":
    main()
