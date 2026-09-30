"""Export Homework 4 labels into the Homework 5 convention.

HW4 recorded each mode as present or absent per conversation. HW5 wants one JSONL file
per mode keyed by trace id, with **1 for Pass (failure absent) and 0 for Fail (failure
present)** — the opposite polarity, which is easy to get backwards and expensive to
notice later.

Also builds the trace source the Module 2 helpers can read. The Homework 3 export names
the conversation ``conversation``; the shared normaliser expects ``turns``. Traces with
no recorded reply are dropped, and duplicate runs of one scenario collapse to the
fullest, which is what the handout asks for.

    .venv/bin/python analysis/tools/export_hw5_labels.py irrelevant_policy_detail
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "analysis" / "state"


def build_trace_source() -> dict[str, str]:
    """Write the readable trace source; return scenario_id -> trace_id."""
    traces = json.loads((REPO / "traces/support_traces.json").read_text())["traces"]
    usable = [t for t in traces
              if any((x.get("agent") or "").strip() for x in (t.get("conversation") or []))]
    best: dict[str, tuple[int, dict]] = {}
    for t in usable:
        scen = t.get("cartwheel_scenario_id")
        size = sum(len((x.get("agent") or "") + (x.get("user") or ""))
                   for x in t["conversation"])
        if scen not in best or size > best[scen][0]:
            best[scen] = (size, t)
    out = [{**t, "turns": t["conversation"]} for _, t in (best[k] for k in sorted(best))]
    # Generated Homework 5 conversations are added by add_generated_records.py and do
    # not exist in the Homework 3 export. Rebuilding from that export alone silently
    # dropped them, which then dropped their labels.
    path = STATE / "hw5_trace_source.json"
    from_hw3 = {t["cartwheel_scenario_id"] for t in out}
    carried = [x for x in (json.loads(path.read_text()) if path.exists() else [])
               if x.get("cartwheel_scenario_id") not in from_hw3]
    out = out + carried
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(traces)} traces -> {len(usable)} with a reply -> "
          f"{len(out) - len(carried)} unique scenarios + {len(carried)} generated")
    print(f"  wrote {path}")
    return {t["cartwheel_scenario_id"]: t["id"] for t in out}


def export(mode: str) -> None:
    by_scenario = build_trace_source()
    labels = json.loads((STATE / "labels" / f"{mode}.json").read_text())

    rows, skipped = [], []
    for j in labels["judgments"]:
        trace_id = by_scenario.get(j["scenario_id"])
        if not trace_id:
            skipped.append(j["scenario_id"])
            continue
        # HW4 "present" means the failure is there, which is HW5 Fail, which is 0.
        rows.append({
            "trace_id": trace_id,
            "label": 0 if j["judgment"] == "present" else 1,
            "scenario_id": j["scenario_id"],
            "source": "human",
            "evidence": j.get("evidence"),
            "method": j.get("method"),
        })

    out = STATE / "hw5_labels"
    out.mkdir(exist_ok=True)
    path = out / f"{mode}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    fails = sum(1 for r in rows if r["label"] == 0)
    print(f"\n{mode}")
    print(f"  Fail (0, failure present): {fails}")
    print(f"  Pass (1, failure absent):  {len(rows) - fails}")
    print(f"  wrote {len(rows)} labels to {path}")
    if skipped:
        print(f"  skipped {len(skipped)} with no usable trace: {skipped[:5]}")
    short = [n for n, c in (("Fail", fails), ("Pass", len(rows) - fails)) if c < 30]
    if short:
        print(f"  SHORT of the 30 the handout requires: {', '.join(short)}")


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "irrelevant_policy_detail")
