"""Build the HW5 labeling queue for one failure mode.

HW5 needs one human label per conversation, stored with 1 = Pass and
0 = Fail in ``analysis/state/hw5_labels/<mode>.jsonl``. HW4 labels are per
turn with 1 = failure present and stay untouched in ``analysis/state/labels/``.

This script:

- Picks a target turn per conversation: the last turn labeled Fail in HW4,
  otherwise the last turn.
- Carries over conversations whose HW4 labels are all human and are not on
  the boundary recheck list, flipping the label to the HW5 convention.
- Queues every other HW4 conversation for review in the HW5 tab of the
  review app, with the reason it needs review.
- With ``--enrich K``, appends K new candidates from ``next_to_label``.

It never overwrites an existing HW5 label, so it is safe to rerun.

    uv run python -m analysis.hw5_queue                 # build or refresh the queue
    uv run python -m analysis.hw5_queue --enrich 20     # add enrich candidates
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "analysis" / "state"
EXPORT = ROOT / "traces" / "support_traces.json"
QUEUE_FILE = STATE / "hw5_queue.json"

MODE = "verbose_reply"

DEFINITION = {
    "version": "v1",
    "question": "Does the target assistant reply contain content the user did not need for their next decision?",
    "fail_rules": {
        "repetition": "States the same fact or instruction more than once.",
        "unneeded_mechanics": "Policy mechanics, caveats, or background the user did not ask about and that are not relevant to their situation, so the reply gives too much detail or overcomplicates the answer (includes override or exception mentions that do not apply).",
        "unsolicited_next_steps": "Offers next steps or further actions the user did not ask for.",
    },
    "pass": "The reply gives the answer, one citation, and at most one sentence of relevant context.",
    "never_verbose": [
        "RESP-8 fields after issue_refund / cancel_order or an order status answer: order (number, title, store), amount or status, what happens next, timing.",
        "Policy detail that bears directly on the user's situation or decision.",
        "Tool calls. Judge only the user-visible reply; redundant lookups are a separate mode.",
    ],
    "unit": "One record per conversation. Target = the turn labeled Fail, otherwise the last turn. Earlier turns are context.",
}

# Boundary v1 (2026-09-26) moved these neighbors inside verbose_reply.
RECHECK_NEIGHBORS = ["unsolicited_next_steps", "irrelevant_policy_nuance"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _live_labels(mode: str) -> dict[str, dict[str, Any]]:
    live: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(STATE / "labels" / f"{mode}.jsonl"):
        if not row.get("superseded_by"):
            live[row["trace_id"]] = row
    return live


def _turn_order() -> dict[str, list[str]]:
    """Scenario id -> trace ids ordered by timestamp (the review app's grouping)."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in json.loads(EXPORT.read_text())["traces"]:
        sid = trace.get("cartwheel_scenario_id")
        if sid:
            grouped[sid].append(trace)
    return {sid: [t["id"] for t in sorted(ts, key=lambda t: t.get("timestamp") or "")]
            for sid, ts in grouped.items()}


def hw5_labels_path(mode: str = MODE) -> Path:
    return STATE / "hw5_labels" / f"{mode}.jsonl"


def build(mode: str = MODE) -> dict[str, Any]:
    order = _turn_order()
    hw4 = _live_labels(mode)
    neighbors = {n: _live_labels(n) for n in RECHECK_NEIGHBORS}
    existing = {row["scenario_id"]: row for row in _read_jsonl(hw5_labels_path(mode))}
    queue_state = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else {}
    old_items = {i["scenario_id"]: i for i in queue_state.get(mode, {}).get("items", [])}

    by_conv: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in hw4.values():
        by_conv[row["scenario_id"]].append(row)

    items: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    for sid in sorted(by_conv):
        rows = by_conv[sid]
        turns = order[sid]
        fail_turns = [tid for tid in turns if hw4.get(tid, {}).get("label") == 1]
        target = fail_turns[-1] if fail_turns else turns[-1]
        reasons: list[str] = []
        if any(r.get("source") != "human" for r in rows):
            reasons.append("HW4 label is agent provisional")
        for n, labels in neighbors.items():
            for tid in turns:
                if labels.get(tid, {}).get("label") == 1 and hw4.get(tid, {}).get("label") == 0:
                    reasons.append(f"boundary v1: {n} Fail on turn {turns.index(tid) + 1}, verbose_reply Pass")
        item = {
            "scenario_id": sid,
            "target_trace_id": target,
            "origin": "hw4",
            "status": "needs_review" if reasons else "carried",
            "reasons": reasons,
        }
        if sid in old_items and old_items[sid].get("status") == "done":
            item["status"] = "done"
        items.append(item)
        if not reasons and sid not in existing:
            note = " | ".join(r["note"] for r in rows if r.get("note") and r["label"] == 1) or None
            carried.append({
                "trace_id": target,
                "scenario_id": sid,
                "label": 0 if fail_turns else 1,
                "source": "human",
                "origin": "carried_from_hw4",
                "rules": [],
                "note": note,
                "ts": _now(),
                "label_id": f"{sid}#{mode}",
            })

    # Keep enrich candidates from earlier runs.
    items += [i for i in old_items.values() if i.get("origin") == "enrich"]

    if carried:
        path = hw5_labels_path(mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(existing.values()) + carried
        rows.sort(key=lambda r: r["scenario_id"])
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        with (path.parent / "_history.jsonl").open("a") as fh:
            for r in carried:
                fh.write(json.dumps({**r, "mode": mode}, ensure_ascii=False) + "\n")

    queue_state[mode] = {"definition": DEFINITION, "updated_at": _now(), "items": items}
    QUEUE_FILE.write_text(json.dumps(queue_state, indent=2, ensure_ascii=False) + "\n")
    return {"items": len(items), "carried_now": len(carried),
            "needs_review": sum(i["status"] == "needs_review" for i in items)}


def enrich(k: int, mode: str = MODE) -> list[dict[str, Any]]:
    """Append ``k`` enrich candidates from conversations outside the queue."""
    from analysis.helpers import next_to_label

    queue_state = json.loads(QUEUE_FILE.read_text())
    items = queue_state[mode]["items"]
    queued = {i["scenario_id"] for i in items}
    order = _turn_order()
    sid_of = {tid: sid for sid, tids in order.items() for tid in tids}
    added: list[dict[str, Any]] = []
    # Ask for extra ids: several may belong to already queued conversations.
    for cand in next_to_label(mode=mode, k=k * 3, strategy="enrich", trace_source=str(EXPORT)):
        sid = sid_of.get(cand["trace_id"])
        if not sid or sid in queued:
            continue
        queued.add(sid)
        added.append({
            "scenario_id": sid,
            "target_trace_id": cand["trace_id"],
            "origin": "enrich",
            "status": "needs_review",
            "reasons": [f"enrich candidate: {cand.get('signal', '')}"],
        })
        if len(added) == k:
            break
    items += added
    queue_state[mode]["updated_at"] = _now()
    QUEUE_FILE.write_text(json.dumps(queue_state, indent=2, ensure_ascii=False) + "\n")
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--enrich", type=int, default=0, help="append K enrich candidates")
    args = parser.parse_args()
    print(build())
    if args.enrich:
        added = enrich(args.enrich)
        print(f"added {len(added)} enrich candidates: {[a['scenario_id'] for a in added]}")


if __name__ == "__main__":
    main()
