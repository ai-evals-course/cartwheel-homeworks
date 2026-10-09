"""Part E: apply every final mode to every reviewed trace.

The handout writes each judgment to Langfuse as a score; Langfuse never
ran here (Docker unavailable, see .hw3-logs/export_traces.py), so the judgment record
under analysis/state/labels/ is the only copy rather than a mirror of one.

Each mode gets a detector. A detector returns (present: bool, evidence: str) or None
meaning "this rule cannot decide, a human must".

    .venv/bin/python analysis/tools/label.py --check    # agreement against human notes
    .venv/bin/python analysis/tools/label.py --write    # write analysis/state/labels/
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "analysis" / "state"
LABELS = STATE / "labels"

# --- load -------------------------------------------------------------------

records = {r["session_id"]: r
           for r in json.loads((REPO / "analysis/review_app/records.json").read_text())}
annotations = json.loads((STATE / "annotations.json").read_text())
review_status = json.loads((STATE / "review_status.json").read_text())
patterns = json.loads((STATE / "patterns.json").read_text())

_resolved_sessions = {s["session_id"] for s in
                      json.loads((STATE / "suggestions.json").read_text())
                      if s.get("resolved")}
# A trace counts as reviewed if it was ticked, annotated, or had a candidate resolved on
# it. The third case matters: rejecting a candidate is a reading, and reversing an accept
# later must not quietly shrink the denominator every fraction is divided by.
# Sort by scenario id, then session id. Some scenarios have two sessions because a
# Homework 3 run timed out and was repeated, so scenario id alone leaves ties -- and set
# iteration order varies per process, which would make the committed label files differ
# run to run for no reason.
REVIEWED = sorted(set(review_status) | {a["session_id"] for a in annotations}
                  | _resolved_sessions,
                  key=lambda s: (records[s]["scenario_id"] if s in records else s, s))

traces = json.loads((REPO / "traces/support_traces.json").read_text())["traces"]
tools_by_session: dict[str, list[dict]] = defaultdict(list)
for t in traces:
    sid = t.get("session_id")
    if sid:
        tools_by_session[sid].extend(o for o in t["observations"] if o.get("type") == "TOOL")

notes_by_session: dict[str, list[dict]] = defaultdict(list)
for a in annotations:
    notes_by_session[a["session_id"]].append(a)


def reply_text(rec: dict) -> str:
    return "\n\n".join(t.get("agent") or "" for t in rec["turns"])


def last_reply(rec: dict) -> str:
    for t in reversed(rec["turns"]):
        if t.get("agent"):
            return t["agent"]
    return ""


# --- detectors --------------------------------------------------------------
# Each takes (rec, tools) and returns (present, evidence) or None for "cannot decide".

INTERNAL_ID = re.compile(r"\b(cw-[a-z][a-z-]+|store-[a-z0-9][a-z0-9-]*-polic\w*)", re.I)


def d_cites_policy_by_internal_id(rec, tools):
    hits = INTERNAL_ID.findall(reply_text(rec))
    if hits:
        return True, f"reply prints {sorted(set(h.lower() for h in hits))}"
    return False, "no internal identifier in any reply"


def d_tool_call_malformed(rec, tools):
    bad = []
    for o in tools:
        res = o.get("tool_result")
        text = res if isinstance(res, str) else json.dumps(res)
        if o.get("status") == "ERROR" or "Invalid JSON" in text:
            bad.append(o.get("tool_name"))
    if bad:
        return True, f"rejected call(s): {Counter(bad).most_common()}"
    return False, f"all {len(tools)} tool calls accepted"


ANNOUNCE = re.compile(
    r"(let me (just )?(pull|check|look|take a look|grab|see|review|verify|confirm|find)"
    r"|i'?ll (check|pull|look|take a look|grab|see|review|verify|confirm|find|get)"
    r"|one moment|hang tight|give me (a|one) (second|moment|sec)"
    r"|checking (on )?(that|this) now|i'?m (going to|gonna) (check|pull|look)"
    r"|i (need|have) to (check|pull|look|confirm|verify)|i'?ll need to)", re.I)


def d_abandons_mid_task(rec, tools):
    """Announce-a-lookup in the closing sentence of the final reply, nothing after it."""
    text = last_reply(rec).strip()
    if not text:
        return None
    tail = text[-200:]
    m = ANNOUNCE.search(tail)
    if not m:
        return False, "final reply does not end on an announced lookup"
    # A question back to the user is defers_what_was_asked, not this mode.
    if tail.rstrip().endswith("?"):
        return None
    return True, f"final reply ends: ...{tail[max(0, m.start() - 40):][:140]!r}"


ESCALATION_EXPECTED = {"escalate_to_human", "preserve_authorization_and_escalate",
                       "state_escalation_policy"}

FRUSTRATION = re.compile(
    r"(frustrat|ridiculous|unacceptable|still haven'?t|no one has|nobody has"
    r"|third time|second time|asked (you )?(again|twice|before)|already (asked|told you)"
    r"|fed up|so annoy|this is (absurd|crazy)|seriously\?|upset|angry|disappoint)", re.I)


ASKS_TO_ESCALATE = re.compile(
    r"(would you like me to|want me to|shall i|should i|just let me know if you"
    r"|let me know and i (can|could|will|'ll))"
    r"[^.?!]{0,80}(escalat|human|ticket|review|support agent|start that)", re.I)


def d_missing_escalation(rec, tools):
    outcome = rec["expected"].get("outcome")
    # ESC-2: any account change is a human's job, whatever the expected outcome says.
    entailed = outcome in ESCALATION_EXPECTED or rec["intent"] == "account_change"
    called = "escalate_to_human" in (rec.get("tools_called") or [])
    if entailed:
        if called:
            return False, f"escalation entailed by {outcome or rec['intent']} and performed"
        return True, (f"escalation entailed by {outcome or rec['intent']}, "
                      "escalate_to_human never called")
    if called:
        return False, "escalated"
    # Asking the user's permission to escalate, where they have already asked for the
    # thing escalation delivers, is a judgment call about what they asked for. Defer it.
    if ASKS_TO_ESCALATE.search(reply_text(rec)):
        return None
    # ESC-3 and ESC-4 turn on tone and on whether the agent could resolve the request.
    # A frustrated or repeated ask is the readable signal; a human decides those.
    if FRUSTRATION.search(" ".join(t.get("user") or "" for t in rec["turns"])):
        return None
    return False, "no escalation trigger: outcome does not entail it, user is not pressing"


# Phrasings taken from the replies themselves, not invented: the agent denies with
# "not able to approve", "outside the eligible period", "past the 30-day window".
GRANT = re.compile(
    r"(refund (is |has been )?(approved|issued|processed|on its way)"
    r"|i'?ve (issued|processed|approved|started)"
    r"|you'?re (still )?eligible|is (still )?eligible|qualifies for"
    r"|still (with)?in (the |your )?\S{0,12} ?(day )?(return |refund )?window"
    r"|within the \S{0,12} ?(day )?(return |refund )?window"
    r"|i can (start|process|issue|approve) (a|the|your)? ?(return|refund)"
    r"|you can (still )?return)", re.I)
DENY = re.compile(
    r"(no longer eligible|not eligible|isn'?t eligible|outside the eligible"
    r"|past (the|your|\S+'?s?) [^.]{0,40}window|outside (the|your) [^.]{0,30}window"
    r"|window (has )?(now )?(closed|passed|expired)|has (now )?passed"
    r"|(can'?t|cannot|not able to|unable to) (start|approve|offer|issue|process)"
    r"|too late)", re.I)


def d_contradicts_eligibility_flag(rec, tools):
    flag = None
    for o in tools:
        res = o.get("tool_result")
        if isinstance(res, dict):
            for k in ("refund_eligible", "eligible"):
                if k in res:
                    flag = bool(res[k])
        elif isinstance(res, str):
            m = re.search(r'"refund_eligible"\s*:\s*(true|false)', res)
            if m:
                flag = m.group(1) == "true"
    if flag is None:
        return False, "no eligibility flag was returned in this conversation"
    text = reply_text(rec)
    grants, denies = bool(GRANT.search(text)), bool(DENY.search(text))
    if not grants and not denies:
        # The reply makes no eligibility claim at all, so it cannot contradict one.
        return False, "reply states no refund eligibility conclusion"
    if grants and denies:
        return None  # says both: a human decides which one the user takes away
    said_yes = grants
    if said_yes != flag:
        return True, f"tools returned refund_eligible={flag}, reply {'grants' if said_yes else 'denies'}"
    return False, f"reply agrees with refund_eligible={flag}"


_suggestions = json.loads((STATE / "suggestions.json").read_text())
HUMAN_ACCEPTED: dict[str, set[str]] = defaultdict(set)
for _s in _suggestions:
    if _s.get("resolved") == "accepted" and _s.get("mode"):
        HUMAN_ACCEPTED[_s["mode"]].add(_s["scenario_id"])
for _a in annotations:
    if _a.get("mode"):
        HUMAN_ACCEPTED[_a["mode"]].add(_a["scenario_id"])


def human_verdict(mode: str):
    """For modes no rule can decide, the human's judgment IS the label.

    Positives come from two places and both count: a shortlisted candidate the human
    accepted, and a free-text note written during open coding that was never
    shortlisted at all. Where a candidate was rejected but an independent note exists,
    the note wins — the rejection was of the heuristic's stated reason, not of the mode.
    """
    rejected = {s["scenario_id"] for s in _suggestions
                if s.get("mode") == mode and s.get("resolved") == "rejected"}
    coded = set(patterns[mode].get("example_ids", []))

    def detect(rec, tools):
        scen = rec["scenario_id"]
        if scen in HUMAN_ACCEPTED[mode]:
            return True, "shortlisted candidate accepted on reading"
        if scen in coded:
            return True, "coded for this mode from a free-text note during open coding"
        if scen in rejected:
            return False, "shortlisted as a candidate and rejected on reading"
        return False, "never shortlisted by the mode's heuristic and never annotated"

    return detect


# These three turn on whether a rule governs the case, whether an offer applies, and
# whether the detail fits the ask. No rule decides them; the label is a human reading.
HUMAN_JUDGED = {"irrelevant_policy_detail", "unwarranted_offer",
                "detail_level_ignores_the_ask"}

DETECTORS = {
    "cites_policy_by_internal_id": d_cites_policy_by_internal_id,
    "tool_call_malformed": d_tool_call_malformed,
    "abandons_mid_task": d_abandons_mid_task,
    "missing_escalation": d_missing_escalation,
    "contradicts_eligibility_flag": d_contradicts_eligibility_flag,
    "irrelevant_policy_detail": human_verdict("irrelevant_policy_detail"),
    "unwarranted_offer": human_verdict("unwarranted_offer"),
    "detail_level_ignores_the_ask": human_verdict("detail_level_ignores_the_ask"),
}

# --- human labels from the review -------------------------------------------
# A note promoted from a suggestion carries its mode. Free-text notes do not, so a
# conversation's confirmed positives are the modes named in patterns.json example_ids
# plus any mode-tagged annotation.

human_positive: dict[str, set[str]] = defaultdict(set)
for a in annotations:
    if a.get("mode"):
        human_positive[a["session_id"]].add(a["mode"])
by_scenario = {r["scenario_id"]: sid for sid, r in records.items()}
for mode, p in patterns.items():
    for scen in p.get("example_ids", []):
        if scen in by_scenario:
            human_positive[by_scenario[scen]].add(mode)

human_negative: dict[str, set[str]] = defaultdict(set)
for mode, p in patterns.items():
    for scen in p.get("close_negatives", []):
        if scen in by_scenario:
            human_negative[by_scenario[scen]].add(mode)


_rp = STATE / "human_resolutions.json"
RESOLVED = {(r["mode"], r["scenario_id"]): r
            for r in (json.loads(_rp.read_text()) if _rp.exists() else [])}


def run():
    out = {m: [] for m in DETECTORS}
    for sid in REVIEWED:
        rec = records.get(sid)
        if not rec:
            continue
        tools = tools_by_session.get(sid, [])
        for mode, fn in DETECTORS.items():
            res = fn(rec, tools)
            row = {
                "session_id": sid,
                "scenario_id": rec["scenario_id"],
                "mode": mode,
                "judgment": None if res is None else ("present" if res[0] else "absent"),
                "method": ("human_review_required" if res is None
                           else "human_review" if mode in HUMAN_JUDGED else "code_check"),
                "evidence": None if res is None else res[1],
            }
            # Where the rule declined to decide, the human's reading settles it. The
            # rule's abstention is kept, so the record shows who decided what.
            hit = RESOLVED.get((mode, rec["scenario_id"]))
            if hit and row["judgment"] is None:
                row["judgment"] = hit["judgment"]
                row["method"] = "human_review"
                row["evidence"] = hit["reason"]
            out[mode].append(row)
    return out


def check(out):
    print(f"{'mode':32} {'present':>8} {'absent':>7} {'undecided':>10}   agreement with your notes")
    for mode, rows in out.items():
        c = Counter(r["judgment"] for r in rows)
        agree = dis = 0
        detail = []
        for r in rows:
            sid = r["session_id"]
            want = (mode in human_positive[sid]) if mode in human_positive[sid] \
                else (False if mode in human_negative[sid] else None)
            if want is None or r["judgment"] is None:
                continue
            got = r["judgment"] == "present"
            if got == want:
                agree += 1
            else:
                dis += 1
                detail.append(f"{r['scenario_id']}: you={want} rule={got}")
        tag = "no rule" if all(r["method"] == "human_review_required" for r in rows) \
            else (f"{agree}/{agree + dis}" if agree + dis else "no overlap")
        print(f"{mode:32} {c['present']:>8} {c['absent']:>7} {c[None]:>10}   {tag}")
        for d in detail[:4]:
            print(f"{'':32} {'':>27}   ! {d}")


def write(out):
    LABELS.mkdir(parents=True, exist_ok=True)
    for mode, rows in out.items():
        c = Counter(r["judgment"] for r in rows)
        (LABELS / f"{mode}.json").write_text(json.dumps({
            "mode": mode,
            "definition": patterns[mode]["description"],
            "boundary": patterns[mode]["boundary"],
            "requirement_source": patterns[mode].get("requirement_source"),
            "labelled_at": datetime.now(timezone.utc).isoformat(),
            "score_destination": ("analysis/state/labels only; Langfuse was never "
                                  "available (Docker could not be installed)"),
            "reviewed_sample_size": len(rows),
            "present": c["present"], "absent": c["absent"], "undecided": c[None],
            "sample_fraction": round(c["present"] / len(rows), 3) if rows else 0.0,
            "fraction_note": ("sample fraction within the reviewed set, not a prevalence "
                              "estimate; the sample was built by clustering and focused search"),
            "judgments": rows,
        }, indent=1) + "\n")
    print(f"wrote {len(out)} files to {LABELS}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    out = run()
    check(out)
    if args.write:
        write(out)
