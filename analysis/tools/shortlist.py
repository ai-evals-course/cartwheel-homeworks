"""Shortlist candidates for the three modes no code rule can decide.

These three modes turn on whether a rule governs the case, whether an
offer applies, and whether the detail level fits the ask. None of that is decidable
from the trace alone, so this produces candidates, not labels. Each candidate goes to
analysis/state/suggestions.json for the human to accept or reject in the review app.

Every heuristic is grounded in something checkable — the store's return window override
in the database, the order total against the $100 threshold, the scenario's user_style —
so a rejected candidate still says something about where the boundary sits.

    .venv/bin/python analysis/tools/shortlist.py           # print, change nothing
    .venv/bin/python analysis/tools/shortlist.py --write   # append to suggestions.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label as L  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SOURCE = "shortlist_2026-09-21"

db = sqlite3.connect(REPO / "data" / "cartwheel.db")
STORE = {r[0]: {"name": r[1], "override": r[2], "restocking": r[3]}
         for r in db.execute("SELECT id, name, return_window_days_override, "
                             "restocking_fee_opt_in FROM stores")}
ORDER = {r[0]: {"store_id": r[1], "total": r[2] / 100, "status": r[3]}
         for r in db.execute("SELECT id, store_id, total_cents, status FROM orders")}

LONG_REPLY, SHORT_REPLY = 655, 219          # p75 and p25 of reply length in the sample
TERSE = {"requests_short_plain_answer", "operational_shorthand", "terse_fragmentary"}
NON_DELIVERY = re.compile(
    r"(never (arrived|came|showed)|didn'?t (arrive|come|receive|get)|hasn'?t arrived"
    r"|not received|never received|no sign of it|still waiting|nothing arrived"
    r"|wasn'?t delivered|haven'?t (got|received))", re.I)
OFFERS_RETURN = re.compile(
    r"(help you (with|get) (a |the )?(return|next steps for a return)"
    r"|start (a |the |your )?return|send it back|process a return|request a return)", re.I)
NAMES_A_RULE = re.compile(r"(\d+[- ]day|return window|policy|within \d+|restocking)", re.I)


def orders_in(rec) -> list[int]:
    """Order ids the tools actually touched, so store lookups are grounded in the trace."""
    out = []
    for o in L.tools_by_session.get(rec["session_id"], []):
        res = o.get("tool_result")
        if isinstance(res, str):
            out += [int(x) for x in re.findall(r'"order_id"\s*:\s*(\d+)', res)]
    return out


def c_irrelevant_policy_detail(rec):
    text = L.reply_text(rec)
    for oid in dict.fromkeys(orders_in(rec)):
        o = ORDER.get(oid)
        if not o:
            continue
        st = STORE.get(o["store_id"], {})
        ov = st.get("override")
        if ov and ov != 30 and re.search(r"\b30[- ]day|\b30 days", text, re.I):
            yield ("quotes the 30-day platform default while "
                   f"{st['name']} overrides to {ov} days", "30-day")
        if "$100" in text and o["total"] and o["total"] > 100:
            yield (f"explains the $100 automatic limit on a ${o['total']:.2f} order, "
                   "which was never going to take the automatic path", "$100")
        if re.search(r"restocking", text, re.I) and not st.get("restocking"):
            yield (f"raises a restocking fee; {st['name']} has not opted into one",
                   "restocking")


def c_unwarranted_offer(rec):
    text = L.reply_text(rec)
    user = " ".join(t.get("user") or "" for t in rec["turns"])
    if NON_DELIVERY.search(user) and OFFERS_RETURN.search(text):
        yield ("user reports the item never arrived; the reply offers a return, which "
               "needs the item in hand", OFFERS_RETURN.search(text).group(0))
    m = re.search(r"[^.]{0,90}exception[^.]{0,60}", text, re.I)
    if m and "escalate_to_human" not in (rec.get("tools_called") or []):
        yield ("offers an exception before any human has reviewed the case", m.group(0).strip())
    m = re.search(r"[^.]{0,60}(another|a different|other) orders?[^.]{0,60}", text, re.I)
    if m and len(set(orders_in(rec))) <= 1:
        yield ("refers to another order when the lookup returned at most one",
               m.group(0).strip())


def c_detail_level_ignores_the_ask(rec):
    text = L.reply_text(rec)
    n = len(text)
    if rec["user_style"] in TERSE and n > LONG_REPLY:
        yield (f"user style is {rec['user_style']} and the reply runs {n} characters, "
               f"above the {LONG_REPLY}-character upper quartile", text[:110])
    if n < SHORT_REPLY and (L.GRANT.search(text) or L.DENY.search(text)) \
            and not NAMES_A_RULE.search(text):
        yield (f"decides the case in {n} characters without naming the window, the dates, "
               "or the policy that decided it", text[:110])
    if rec["user_style"] == "confused_rambling" and n < SHORT_REPLY:
        yield (f"user style is confused_rambling and the reply is {n} characters, "
               "below the lower quartile", text[:110])


CANDIDATES = {
    "irrelevant_policy_detail": c_irrelevant_policy_detail,
    "unwarranted_offer": c_unwarranted_offer,
    "detail_level_ignores_the_ask": c_detail_level_ignores_the_ask,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    sug_path = L.STATE / "suggestions.json"
    existing = json.loads(sug_path.read_text())
    seen = {(s["scenario_id"], s.get("mode")) for s in existing}

    new, counts = [], Counter()
    for sid in L.REVIEWED:
        rec = L.records[sid]
        for mode, fn in CANDIDATES.items():
            for reason, quote in fn(rec):
                counts[mode] += 1
                if (rec["scenario_id"], mode) in seen:
                    continue
                seen.add((rec["scenario_id"], mode))
                new.append({
                    "session_id": sid,
                    "scenario_id": rec["scenario_id"],
                    "trace_id": rec["turns"][0].get("trace_id"),
                    "span": "agent reply turn 1",
                    "quoted_text": quote,
                    "note": f"[agent suggestion] {reason}. Candidate only — read it and "
                            "reject if the rule does govern this case.",
                    "mode": mode,
                    "source": SOURCE,
                    "already_reviewed": True,
                    "resolved": None,
                })

    for mode in CANDIDATES:
        have = sum(1 for s in existing if s.get("mode") == mode and s.get("resolved") == "accepted")
        add = sum(1 for s in new if s["mode"] == mode)
        print(f"{mode:32} {counts[mode]:>3} hits  {add:>3} new to review  "
              f"({have} already accepted)")
    print(f"\ntotal new candidates for you: {len(new)}")

    if args.write:
        sug_path.write_text(json.dumps(existing + new, indent=1) + "\n")
        print(f"appended to {sug_path}")
    else:
        print("\ndry run. re-run with --write to queue these in the review app.")
        for s in new[:6]:
            print(f"  {s['scenario_id']:14} {s['mode']:30} {s['note'][19:110]}")


if __name__ == "__main__":
    main()
