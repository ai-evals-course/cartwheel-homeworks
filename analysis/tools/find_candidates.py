"""Find Homework 5 labelling candidates for irrelevant_policy_detail, balanced by shape.

The mode has four failure shapes and no shape has more than two confirmed traces.
``next_to_label(strategy="enrich")`` searches for semantic neighbours of existing
failures, so left alone it drifts toward whichever shape is most numerous. This runs one
targeted search per shape as well, so the top-up covers all four.

Every search is a **candidate generator, not a labeller**. Each candidate carries the
database fact that triggered it so a human can check the reasoning, and rejecting one
still says something about where the boundary sits.

Grounding note: an earlier version of this search read every order a trace touched, and
on a conversation that listed seventeen orders it picked the wrong store and produced a
false positive the reviewer caught. Order resolution here prefers the order number the
reply actually names, and abstains when it cannot tell.

    .venv/bin/python analysis/tools/find_candidates.py            # report only
    .venv/bin/python analysis/tools/find_candidates.py --write    # queue for review
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "analysis" / "state"
MODE = "irrelevant_policy_detail"
SOURCE = "shape_search_2026-09-24"

db = sqlite3.connect(REPO / "data" / "cartwheel.db")
STORE = {r[0]: {"name": r[1], "override": r[2], "restocking": bool(r[3])}
         for r in db.execute("SELECT id,name,return_window_days_override,"
                             "restocking_fee_opt_in FROM stores")}
ORDER = {r[0]: {"store_id": r[1], "total": r[2] / 100}
         for r in db.execute("SELECT id,store_id,total_cents FROM orders")}

records = {r["scenario_id"]: r for r in
           json.loads((REPO / "analysis/review_app/records.json").read_text())}
traces = json.loads((STATE / "hw5_trace_source.json").read_text())
labelled = {json.loads(l)["scenario_id"]
            for l in (STATE / "hw5_labels" / f"{MODE}.jsonl").read_text().splitlines() if l}


def reply_of(t) -> str:
    return "\n\n".join(x.get("agent") or "" for x in t.get("turns") or [])


def tools_of(t) -> list[dict]:
    return [o for o in t.get("observations") or [] if o.get("type") == "TOOL"]


def subject_order(t, reply: str) -> int | None:
    """The order the reply is actually about, or None when it cannot be told.

    Prefers an order number the reply names. Falls back to the only order the tools
    returned. Abstains when several orders are in play and none is named, because that
    is exactly where the earlier search went wrong.
    """
    named = [int(n) for n in re.findall(r"(?:order\s*#?|#)\s*(\d{3,5})", reply, re.I)]
    seen = []
    for o in tools_of(t):
        v = o.get("tool_result")
        if isinstance(v, str):
            seen += [int(x) for x in re.findall(r'"order_id"\s*:\s*(\d+)', v)]
    for n in named:
        if n in ORDER:
            return n
    uniq = list(dict.fromkeys(seen))
    return uniq[0] if len(uniq) == 1 else None


def shape_1(t, reply, order, store, called):
    """Platform default mentioned where the store overrides it."""
    if not store or not store["override"] or store["override"] == 30:
        return None
    if not re.search(r"\b30[\s-]day|\b30 days", reply, re.I):
        return None
    names_it = re.search(rf"\b{store['override']}[\s-]?day|\b{store['override']} days",
                         reply, re.I)
    why = (f"mentions the 30-day platform default; {store['name']} overrides to "
           f"{store['override']} days")
    if names_it:
        # Naming the governing window is a Pass by the boundary, so this is only worth
        # a look, not a flag. Kept because the shape is scarce and reading is cheap.
        return "WIDE " + why + " and the reply does name that window"
    return why + ", and that number never appears in the reply"


POLICY_CONTEXT = re.compile(
    r"(auto[- ]?approv|threshold|limit|review|cw-refunds|refund polic|needs? a human"
    r"|goes? through automatically|queued)", re.I)


def shape_2(t, reply, order, store, called):
    """The $100 threshold mentioned; does it govern the path taken?

    The mention has to be the policy, not a price. An earlier version matched "$100"
    inside "Heavy-Duty Webcam - $100.25" and queued a product search with no policy in
    it at all, which cost the reviewer a read.
    """
    hits = list(re.finditer(r"\$100(?![.\d])|100 dollars", reply, re.I))
    if not hits:
        return None
    if not any(POLICY_CONTEXT.search(reply[max(0, m.start() - 120):m.end() + 120])
               for m in hits):
        return None
    took = [c for c in ("escalate_to_human", "issue_refund") if c in called]
    if not took:
        return ("explains the $100 review threshold but neither escalates nor issues a "
                "refund, so the threshold governs no path taken here")
    return ("WIDE mentions the $100 threshold and does call " + ", ".join(took) +
            "; check whether the threshold is the reason for the path taken")


def shape_3(t, reply, order, store, called):
    """A restocking fee mentioned; has the store opted in?"""
    if not re.search(r"restocking", reply, re.I):
        return None
    if store is None:
        return "WIDE raises a restocking fee; the order could not be resolved to a store"
    if store["restocking"]:
        return f"WIDE raises a restocking fee; {store['name']} HAS opted in"
    return f"raises a restocking fee; {store['name']} has not opted into one"


def shape_4(t, reply, order, store, called):
    """Policy recited after the action is complete."""
    if "issue_refund" not in called:
        return None
    done = [o for o in tools_of(t) if o.get("tool_name") == "issue_refund"
            and isinstance(o.get("tool_result"), str) and '"ok": true' in o["tool_result"]]
    if not done:
        return None
    tail = reply[-600:]
    if re.search(r"return window|\d+ days of delivery|restocking", tail, re.I):
        return ("refund already issued, then the reply explains the return window or "
                "restocking rule, which governs nothing still to be decided")
    return "WIDE refund issued; check whether the reply then recites policy that governs nothing"


SHAPES = {"1_default_as_operative": shape_1, "2_threshold_no_path": shape_2,
          "3_fee_not_opted_in": shape_3, "4_recited_after_settled": shape_4}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    found: dict[str, list] = {k: [] for k in SHAPES}
    abstained = 0
    for t in traces:
        scen = t.get("cartwheel_scenario_id")
        if scen in labelled:
            continue
        reply = reply_of(t)
        if not reply.strip():
            continue
        oid = subject_order(t, reply)
        store = STORE.get(ORDER[oid]["store_id"]) if oid in ORDER else None
        order = ORDER.get(oid)
        called = [o.get("tool_name") for o in tools_of(t)]
        if oid is None:
            abstained += 1
        for name, fn in SHAPES.items():
            why = fn(t, reply, order, store, called)
            if why:
                found[name].append({"scenario_id": scen, "trace_id": t["id"], "why": why})

    strict = {k: [r for r in v if not r["why"].startswith("WIDE")] for k, v in found.items()}
    print(f"unlabelled scenarios searched: {len(traces) - len(labelled)}")
    print(f"  order could not be resolved (search abstained): {abstained}\n")
    total = 0
    for name, rows in found.items():
        print(f"  {name:28} {len(strict[name]):>3} likely  "
              f"{len(rows) - len(strict[name]):>3} worth a look")
        total += len(rows)
        for r in rows[:2]:
            print(f"      {r['scenario_id']}  {r['why'][:76]}")
    print(f"\n  total {total} candidates across {sum(1 for v in found.values() if v)} shapes")
    print(f"  confirmed Fails today: 6. Need about 24 more.")

    if args.write:
        sp = STATE / "suggestions.json"
        existing = json.loads(sp.read_text())
        seen = {(s["scenario_id"], s.get("mode")) for s in existing}
        new = []
        for name, rows in found.items():
            for r in rows:
                if (r["scenario_id"], MODE) in seen:
                    continue
                seen.add((r["scenario_id"], MODE))
                rec = records.get(r["scenario_id"])
                new.append({
                    "session_id": rec["session_id"] if rec else None,
                    "scenario_id": r["scenario_id"],
                    "trace_id": r["trace_id"],
                    "span": "agent reply turn 1",
                    "quoted_text": "",
                    "note": f"[agent suggestion] shape {name}: {r['why']}. Candidate "
                            "only — check whether the rule governs the path taken.",
                    "mode": MODE,
                    "shape": name,
                    "source": SOURCE,
                    "already_reviewed": False,
                    "resolved": None,
                })
        sp.write_text(json.dumps(existing + new, indent=1) + "\n")
        print(f"\n  queued {len(new)} new candidates in {sp}")
    else:
        print("\n  dry run. re-run with --write to queue these in the review app.")


if __name__ == "__main__":
    main()
