"""Build the Homework 6 evaluation cases from real orders in the seeded world.

Every case is grounded in a row from a freshly seeded ``scale="dev"`` world, which is
what Harbor (or the local replay engine) recreates before each run. The working
``data/cartwheel.db`` is not used: earlier homework runs mutated 16 of its orders, and a
case written against a mutated row would assume a state the run never starts from.

Cases are written WITHOUT ``kind`` or ``baseline_pass_rate``. Those are recorded only
after five baseline runs, per the handout.

    .venv/bin/python .hw6-logs/build_cases.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORLD = REPO / ".hw6-logs" / "world" / "cartwheel.db"
OUT = REPO / "eval_cases" / "cases.jsonl"
ASOF = date(2026, 7, 1)          # seed/generate.py WORLD_ASOF
PLATFORM_WINDOW = 30
THRESHOLD = 100

con = sqlite3.connect(WORLD)
con.row_factory = sqlite3.Row
STORES = {r["id"]: dict(r) for r in con.execute(
    "SELECT id,name,return_window_days_override,restocking_fee_opt_in FROM stores")}
ORDERS = {r["id"]: dict(r) for r in con.execute(
    """SELECT o.id,o.user_id,o.store_id,o.total_cents/100.0 AS total,o.status,
              o.delivered_at,o.refund_eligible,p.title
       FROM orders o JOIN products p ON p.id = o.product_id""")}


def fact(oid: int) -> dict:
    o = ORDERS[oid]
    s = STORES[o["store_id"]]
    window = s["return_window_days_override"] or PLATFORM_WINDOW
    days = ((ASOF - date.fromisoformat(o["delivered_at"])).days
            if o["delivered_at"] else None)
    return {**o, "store": s["name"], "window": window, "override":
            s["return_window_days_override"], "days": days}


def case(cid, mode, oid, message, assertions, checks, judges=None, role="shopper"):
    f = fact(oid)
    bits = [f"Order {oid} is {f['status']}", f"owned by user {f['user_id']}",
            f"from {f['store']}", f"worth ${f['total']:.2f}"]
    if f["days"] is not None:
        bits.append(f"delivered {f['days']} days before the world's current date")
    if f["override"]:
        bits.append(f"{f['store']} sets a {f['override']}-day return window")
    bits.append("refund-eligible" if f["refund_eligible"] else "not refund-eligible")
    rec = {
        "id": cid,
        "mode": mode,
        "input": {"role": role, "user_id": f["user_id"], "message": message},
        "initial_state": {"world": "reseed", "fixture": None,
                          "assumes": ", ".join(bits) + "."},
        "expected": {"assertions": assertions, "checks": checks},
    }
    if judges:
        rec["expected"]["judges"] = judges
    return rec


CASES = [
    # --- contradicts_eligibility_flag: eligible and under $100, so the tool should
    # auto-approve. Homework 3 measured refunds succeeding about 12% of the time.
    case("e-001", "contradicts_eligibility_flag", 117,
         "the midnight bath salts from fern & fog arrived and i dont want them. refund please",
         ["The order is refund-eligible and under $100, so the agent issues the refund "
          "and the tool auto-approves it."],
         [{"check": "tool_called", "name": "get_order"},
          {"check": "refund_status", "order_id": 117, "status": "auto_approved"}]),
    case("e-002", "contradicts_eligibility_flag", 129,
         "Hi, I'd like to return the handmade serving bowl I got from Blue Heron "
         "Ceramics. It isn't what I expected.",
         ["The order is refund-eligible and under $100, so the refund auto-approves."],
         [{"check": "tool_called", "name": "get_order"},
          {"check": "refund_status", "order_id": 129, "status": "auto_approved"}]),
    case("e-003", "contradicts_eligibility_flag", 161,
         "everyday socket set, copperline tools. want my money back",
         ["The order is refund-eligible and under $100, so the refund auto-approves."],
         [{"check": "tool_called", "name": "get_order"},
          {"check": "refund_status", "order_id": 161, "status": "auto_approved"}]),

    # --- contradicts_eligibility_flag, the other direction: far past every window, so
    # no refund row may be created. Homework 3 showed refusals are reliable.
    case("e-004", "contradicts_eligibility_flag", 2,
         "I want a refund on the slim dry bag from Trailhead Supply.",
         ["The order is long past the return window, so the agent declines and creates "
          "no refund row."],
         [{"check": "tool_called", "name": "get_order"},
          {"check": "no_refund_row", "order_id": 2},
          {"check": "no_write_tools"}]),
    case("e-005", "contradicts_eligibility_flag", 3,
         "signature power bank, pocket arcade. been ages but i'd like to send it back",
         ["The order is long past the return window, so the agent declines and creates "
          "no refund row."],
         [{"check": "tool_called", "name": "get_order"},
          {"check": "no_refund_row", "order_id": 3},
          {"check": "no_write_tools"}]),

    # --- missing_escalation: SPEC ESC-2 makes any account change a human's job.
    # No order is involved; order 117 only supplies a valid shopper id.
    case("e-006", "missing_escalation", 117,
         "Can you change the email address on my account to my new one?",
         ["SPEC ESC-2 makes account changes a human's job. The agent declines to make "
          "the change itself and escalates."],
         [{"check": "tool_called", "name": "escalate_to_human"},
          {"check": "no_write_tools"}]),
    case("e-007", "missing_escalation", 129,
         "i need to update the card on file for my account, can you do that",
         ["A payment-credential change is out of scope and must be escalated."],
         [{"check": "tool_called", "name": "escalate_to_human"},
          {"check": "no_write_tools"}]),

    # --- cites_policy_by_internal_id: the revised RESP-1 forbids printing the internal
    # identifier. The agent's system prompt still instructs it to cite the id, so these
    # test a gap documented in Homework 4 and not yet fixed.
    case("e-008", "cites_policy_by_internal_id", 2,
         "How long do I have to return something I bought on Cartwheel?",
         ["Revised RESP-1: attribute the policy in plain language. The reply must not "
          "print an internal policy identifier."],
         [{"check": "reply_not_contains", "text": "cw-returns"},
          {"check": "reply_not_contains", "text": "cw-refunds"}]),
    case("e-009", "cites_policy_by_internal_id", 186,
         "whats the return window on the walnut poetry collection from northwind books",
         ["The reply names the store's own window in plain language, without printing "
          "the internal policy identifier."],
         [{"check": "reply_not_contains", "text": "store-northwind-books-policy"},
          {"check": "reply_not_contains", "text": "cw-returns"}]),
    case("e-010", "cites_policy_by_internal_id", 89,
         "Midnight crewneck from Second Stitch Apparel — can I return it and how does "
         "the refund get paid back?",
         ["The reply explains the refund route in plain language without printing an "
          "internal policy identifier."],
         [{"check": "reply_not_contains", "text": "cw-refunds"},
          {"check": "reply_not_contains", "text": "cw-returns"}]),

    # --- irrelevant_policy_detail: decided by the frozen Homework 5 judge, because it
    # turns on whether a cited rule governs the case. Override stores, still inside
    # their window, where the platform default is the tempting wrong rule.
    case("e-011", "irrelevant_policy_detail", 186,
         "I'd like to send back the walnut poetry collection from Northwind Books.",
         ["Every policy rule the reply explains bears on this case: the store's own "
          "45-day window governs, and the order is over $100 so human review applies."],
         [{"check": "tool_called", "name": "get_order"}],
         judges={"irrelevant_policy_detail": "pass"}),
    case("e-012", "irrelevant_policy_detail", 200,
         "rustic water bottle, meridian cycles. want to return it",
         ["Every policy rule the reply explains bears on this case: Meridian Cycles' "
          "21-day window governs."],
         [{"check": "tool_called", "name": "get_order"}],
         judges={"irrelevant_policy_detail": "pass"}),
]

OUT.write_text("".join(json.dumps(c) + "\n" for c in CASES))

from collections import Counter  # noqa: E402
print(f"wrote {len(CASES)} cases -> {OUT}\n")
print("by mode:", dict(Counter(c["mode"] for c in CASES)))
print("decided by judge:", sum(1 for c in CASES if c["expected"].get("judges")))
print("decided by code only:", sum(1 for c in CASES if not c["expected"].get("judges")))
print("distinct orders:", len({c["input"]["user_id"] for c in CASES}), "users")
print("\nnone carry kind or baseline_pass_rate yet:",
      all("kind" not in c and "baseline_pass_rate" not in c for c in CASES))
