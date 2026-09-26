"""One-off generator for scenarios/support_scenarios.jsonl (HW3 Part C).

Grounds every scenario in real seeded data and computes expected outcomes
from the same authoritative sources the app uses (facts.yaml, the
eligibility function, real DB rows, policy docs) rather than guessing.
Not part of the graded deliverables; kept only to reproduce/adjust the
final set if needed.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, datetime
from pathlib import Path

from agent.config import db_path, load_facts
from seed.eligibility import effective_return_window_days, is_refund_eligible, refund_needs_approval

random.seed(20260913)

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS = load_facts()
PLATFORM_WINDOW = FACTS["return_window_days"]
THRESHOLD = FACTS["refund_auto_approve_threshold_usd"]
AS_OF = date(2026, 7, 1)  # matches seed/generate.py's fixed world date

OVERRIDE_STORES = {2: 14, 7: 45, 10: 21, 13: 7}  # store_id -> override days
OVERRIDE_POLICY_DOC = {
    2: "store-juniper-home-goods-policy",
    7: "store-northwind-books-policy",
    10: "store-meridian-cycles-policy",
    13: "store-saltbox-pantry-policy",
}
OVERRIDE_NAME = {
    2: "Juniper Home Goods",
    7: "Northwind Books",
    10: "Meridian Cycles",
    13: "Saltbox Pantry",
}

conn = sqlite3.connect(db_path())
conn.row_factory = sqlite3.Row


def q(sql, params=()):
    return conn.execute(sql, params).fetchall()


scenarios = []
_used_ids = set()


def new_id(prefix, n):
    sid = f"{prefix}-{n:04d}"
    assert sid not in _used_ids
    _used_ids.add(sid)
    return sid


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


def order_row(order_id):
    return q("SELECT * FROM orders WHERE id=?", (order_id,))[0]


def add(sid, group, role, user_id, intent, record_state, applicable_policy,
        tools_needed, difficulty, style, opening, expected,
        followups=None, store_id=None, order_id=None, product_id=None, dq=None):
    followups = followups or []
    tup = {
        "role": role, "user_id": user_id, "intent": intent,
        "record_state": record_state, "applicable_policy": applicable_policy,
        "tools_needed": tools_needed, "turn_count": 1 + len(followups),
        "difficulty": difficulty, "user_style": style,
    }
    if store_id is not None:
        tup["store_id"] = store_id
    if order_id is not None:
        tup["order_id"] = order_id
    if product_id is not None:
        tup["product_id"] = product_id
    scenarios.append({
        "id": sid, "scenario_group": group, "data_quality_case_id": dq,
        "tuple": tup, "opening_message": opening, "followups": followups,
        "expected": expected,
    })


def obj(outcome, source_type, reference):
    return {"evaluation": "objective", "outcome": outcome,
            "source": {"type": source_type, "reference": reference}}


def hj(criterion, reference):
    return {"evaluation": "human_judgment", "criterion": criterion,
            "source": {"type": "specification", "reference": reference}}


STYLES = [
    "neutral_conversational", "terse_fragmentary", "typo_heavy",
    "confused_rambling", "frustrated_impatient", "repetitive_pressuring",
    "operational_shorthand", "requests_short_plain_answer",
]


def pick_style(i):
    return STYLES[i % len(STYLES)]


# ---------------------------------------------------------------------------
# Phrasing templates per intent, several variants each for real variety.
# {order} / {product} / {store} / {amount} are filled with real facts.
# ---------------------------------------------------------------------------

ORDER_STATUS_TMPL = [
    "Hey, what's the status of order {order}?",
    "Can you check on order {order} for me?",
    "order {order} status pls",
    "I'm trying to figure out what's going on with order {order}. Can you check?",
    "STATUS CHECK: order {order}.",
    "Where's my order {order} at right now?",
]

REFUND_TMPL = [
    "I'd like a refund for order {order}.",
    "Can you refund order {order}? Wasn't happy with it.",
    "refund order {order} pls",
    "I bought something and I don't think I want it anymore, order {order}. Can I get my money back?",
    "REFUND REQUEST - order {order}.",
    "Please just refund order {order} already, I've been waiting.",
    "cn u refnud oder {order}",
]

CANCEL_TMPL = [
    "Can you cancel order {order}? I changed my mind.",
    "cancel order {order} pls",
    "I need to cancel order {order} before it ships.",
    "CANCEL: order {order}.",
    "I don't want order {order} anymore, please cancel it.",
]

POLICY_TMPL = [
    "How many days do I have to return something from {store}?",
    "What's {store}'s return policy?",
    "return window for {store}?",
    "I bought something from {store} and I'm not sure how long I have to return it.",
]

PRODUCT_SEARCH_TMPL = [
    "Do you have the {product} in stock? How much is it?",
    "Looking for the {product}, is that still available?",
    "{product} price?",
    "I saw a {product} on here somewhere, how much was it again?",
]

OUT_OF_SCOPE = [
    "Can you help me file my taxes?",
    "What's a good recipe for banana bread?",
    "Can you check the status of my Amazon order?",
    "Can you give me legal advice about a lease dispute?",
    "Can you write me a cover letter for a job application?",
    "What's the weather like today?",
    "Can I get investment advice on which stocks to buy?",
    "Can you help me book a flight?",
    "Do you know any good doctors near me?",
    "Can you tutor me in calculus?",
]

ACCOUNT_CHANGE_TMPL = [
    "Can you update the email on my account to {email}?",
    "I need to change my name on file to {name}.",
    "Please update my shipping address to {addr}.",
    "Can you reset my password for me?",
    "Change my phone number on file to {phone}.",
    "I want to update my account email to {email}, can you do that now?",
    "update my acct email 2 {email} pls",
]

DISPUTE_TMPL = [
    "My package says delivered but I never received order {order}. I want to dispute this charge.",
    "I never got order {order} and I'm being charged for it. This needs to be disputed.",
    "order {order} never showed up, I want to file a dispute.",
    "Someone signed for order {order} but it wasn't me. I want to dispute the charge.",
]


def money(cents):
    return f"${cents/100:.2f}"


# ===========================================================================
# COVERAGE: 175
# ===========================================================================

n = 0

# --- order_status: 35 -------------------------------------------------
order_status_pool = q(
    "SELECT id, user_id, store_id, status, refund_eligible FROM orders "
    "WHERE status IN ('delivered','shipped','placed') ORDER BY RANDOM() LIMIT 35"
)
for i, row in enumerate(order_status_pool):
    n += 1
    role = "shopper"
    user_id = row["user_id"]
    if i % 7 == 0:  # sprinkle in merchant/support role coverage
        role = "merchant"
        user_id = 9000 + row["store_id"]
    elif i % 7 == 3:
        role = "support"
        user_id = 9501
    o = order_row(row["id"])
    add(new_id("support", n), "coverage", role, user_id, "order_status",
        f"order_{row['status']}", "none", "one_lookup", "well_specified", pick_style(i),
        random.choice(ORDER_STATUS_TMPL).format(order=row["id"]),
        obj(f"get_order must report order {row['id']} status={row['status']}, refund_eligible={bool(row['refund_eligible'])}.",
            "sql", f"orders.id={row['id']}"),
        order_id=row["id"])

# --- refund: 45 ---------------------------------------------------------
refund_under_pool = q(
    "SELECT id, user_id, store_id, total_cents FROM orders "
    "WHERE status='delivered' AND refund_eligible=1 AND total_cents<10000 "
    "ORDER BY RANDOM() LIMIT 30"
)
refund_over_pool = q(
    "SELECT id, user_id, store_id, total_cents FROM orders "
    "WHERE status='delivered' AND refund_eligible=1 AND total_cents>10000 "
    "ORDER BY RANDOM() LIMIT 15"
)
SUPPORT_REFUND_TMPL = [
    "A customer is asking for a refund on order {order}, can you process it?",
    "Handling a refund request for order {order} on behalf of a shopper.",
    "Can you process the refund for order {order}? Customer reached out about it.",
]

for i, row in enumerate(refund_under_pool):
    n += 1
    role, user_id = "shopper", row["user_id"]
    if i in (0, 1):
        role, user_id = "support", 9501
    elif i % 8 == 0:
        role, user_id = "merchant", 9000 + row["store_id"]
    msg = (SUPPORT_REFUND_TMPL[i % len(SUPPORT_REFUND_TMPL)] if role == "support"
           else random.choice(REFUND_TMPL)).format(order=row["id"])
    add(new_id("support", n), "coverage", role, user_id, "refund",
        "order_delivered_in_window_under_threshold", "none", "several_calls",
        "well_specified", pick_style(i), msg,
        obj(f"issue_refund must auto-approve: order {row['id']} is eligible and "
            f"{money(row['total_cents'])} is at/under the ${THRESHOLD:.0f} threshold.",
            "eligibility_function", f"orders.id={row['id']}; facts.yaml:refund_auto_approve_threshold_usd"),
        order_id=row["id"])
for i, row in enumerate(refund_over_pool):
    n += 1
    role, user_id = "shopper", row["user_id"]
    if i == 0:
        role, user_id = "support", 9501
    msg = (SUPPORT_REFUND_TMPL[i % len(SUPPORT_REFUND_TMPL)] if role == "support"
           else random.choice(REFUND_TMPL)).format(order=row["id"])
    add(new_id("support", n), "coverage", role, user_id, "refund",
        "order_delivered_in_window_over_threshold", "none", "several_calls",
        "well_specified", pick_style(i), msg,
        obj(f"issue_refund must queue for approval: order {row['id']} is eligible and "
            f"{money(row['total_cents'])} is over the ${THRESHOLD:.0f} threshold.",
            "eligibility_function", f"orders.id={row['id']}; facts.yaml:refund_auto_approve_threshold_usd"),
        order_id=row["id"])

# --- cancellation: 20 (placed=success, shipped=denied) -------------------
placed_pool = q("SELECT id, user_id, store_id FROM orders WHERE status='placed' ORDER BY RANDOM() LIMIT 12")
shipped_pool = q("SELECT id, user_id, store_id FROM orders WHERE status='shipped' ORDER BY RANDOM() LIMIT 8")
for i, row in enumerate(placed_pool):
    n += 1
    role, user_id = "shopper", row["user_id"]
    msg = random.choice(CANCEL_TMPL).format(order=row["id"])
    if i == 0:
        role, user_id = "support", 9501
        msg = f"A customer wants order {row['id']} cancelled before it ships, can you take care of it?"
    add(new_id("support", n), "coverage", role, user_id, "cancellation",
        "order_placed", "none", "one_lookup", "well_specified", pick_style(i), msg,
        obj(f"cancel_order must succeed: order {row['id']} is still 'placed'.", "sql", f"orders.id={row['id']}"),
        order_id=row["id"])
for i, row in enumerate(shipped_pool):
    n += 1
    add(new_id("support", n), "coverage", "shopper", row["user_id"], "cancellation",
        "order_shipped", "none", "one_lookup", "boundary", pick_style(i),
        random.choice(CANCEL_TMPL).format(order=row["id"]),
        obj(f"cancel_order must return not_eligible: order {row['id']} has already shipped.",
            "eligibility_function", f"orders.id={row['id']}; facts.yaml:cancel_cutoff"),
        order_id=row["id"])

# --- policy_question: 25 (platform default + store overrides) -----------
PLATFORM_POLICY_TMPL = [
    "How many days do I have to return something I bought on Cartwheel?",
    "What's Cartwheel's return policy?",
    "return policy?",
    "How long is the return window on Cartwheel in general?",
    "I'm not sure how many days I have to send something back, can you tell me?",
    "whats the return window on this site",
    "Quick question — what's the standard return period here?",
    "Just curious what the general return window is before I buy something.",
    "How long after delivery can I return an item?",
    "General return policy question: how many days do I get?",
    "Is there a set number of days for returns on Cartwheel?",
    "return window??",
    "I want to know the return policy before I order.",
    "How many days after my stuff arrives can I send it back?",
    "return timeframe pls",
]
for i in range(15):
    n += 1
    add(new_id("support", n), "coverage", "shopper", 1, "policy_question", "none",
        "platform_default", "one_lookup", "well_specified", pick_style(i),
        PLATFORM_POLICY_TMPL[i % len(PLATFORM_POLICY_TMPL)],
        obj(f"Answer {PLATFORM_WINDOW} days from delivery, citing cw-returns.", "policy_document", "cw-returns"))
override_store_ids = list(OVERRIDE_STORES)
for i in range(10):
    n += 1
    sid = override_store_ids[i % len(override_store_ids)]
    tmpl = POLICY_TMPL[(i // len(override_store_ids)) % len(POLICY_TMPL)]
    add(new_id("support", n), "coverage", "shopper", 1 + i, "policy_question", "store_policy_page",
        "store_override", "one_lookup", "well_specified", pick_style(i),
        tmpl.format(store=OVERRIDE_NAME[sid]),
        obj(f"Answer {OVERRIDE_STORES[sid]} days, citing {OVERRIDE_POLICY_DOC[sid]} (overrides the {PLATFORM_WINDOW}-day platform default).",
            "policy_document", OVERRIDE_POLICY_DOC[sid]),
        store_id=sid)

# --- product_search: 25 (globally unique titles only) --------------------
unique_products = q(
    "SELECT id, store_id, title, price_cents FROM products "
    "WHERE title != '' AND title IN (SELECT title FROM products GROUP BY title HAVING count(*)=1) "
    "ORDER BY RANDOM() LIMIT 25"
)
for i, row in enumerate(unique_products):
    n += 1
    add(new_id("support", n), "coverage", "shopper", 1, "product_search", "product",
        "none", "one_lookup", "well_specified", pick_style(i),
        random.choice(PRODUCT_SEARCH_TMPL).format(product=row["title"]),
        obj(f"search_products must return {row['title']!r} (product {row['id']}) at {money(row['price_cents'])}.",
            "sql", f"products.id={row['id']}"),
        product_id=row["id"])

# --- dispute: 8 ------------------------------------------------------------
dispute_orders = q(
    "SELECT id, user_id FROM orders WHERE status='delivered' ORDER BY RANDOM() LIMIT 8"
)
for i, row in enumerate(dispute_orders):
    n += 1
    role, user_id = "shopper", row["user_id"]
    msg = random.choice(DISPUTE_TMPL).format(order=row["id"])
    if i == 0:
        role, user_id = "support", 9501
        msg = f"A shopper is telling me order {row['id']} never arrived and wants to dispute the charge. What should I do?"
    add(new_id("support", n), "coverage", role, user_id, "dispute", "none",
        "none", "none", "well_specified", pick_style(i), msg,
        hj("The agent must escalate the dispute to a human (ESC-3) rather than resolving it itself, "
           "regardless of which role raised it.", "ESC-3"))

# --- account_change: 7 ------------------------------------------------------
for i in range(7):
    n += 1
    msg = ACCOUNT_CHANGE_TMPL[i].format(
        email="new@example.com", name="Alex Rivera", addr="42 Birch St", phone="555-0142")
    add(new_id("support", n), "coverage", "shopper", 1, "account_change", "none",
        "none", "none", "well_specified", pick_style(i), msg,
        hj("The agent must escalate the account-change request via escalate_to_human, not just refuse or attempt it directly.", "ESC-2"))

# --- out_of_scope: 10 --------------------------------------------------------
for i, msg in enumerate(OUT_OF_SCOPE):
    n += 1
    add(new_id("support", n), "coverage", "shopper", 1, "out_of_scope", "none",
        "none", "none", "well_specified", pick_style(i), msg,
        hj("The agent declines the out-of-scope request in one or two sentences and points to what it can help with instead.", "SCOPE-2, RESP-4"))

print(f"coverage so far: {n}")
assert n == 175, n

# ===========================================================================
# CHALLENGE: 75
# ===========================================================================

c = 0

# --- 6 data-quality cases x 5 = 30 -----------------------------------------
DQ_CASES = q("SELECT case_id, entity_type, entity_id, description, expected_handling FROM data_quality_cases ORDER BY case_id")
dq_users = {}
# For order-based cases, use the order's real owner each time (only one such
# order exists per case), varying only style/phrasing across the 5 copies.
for case in DQ_CASES:
    case_id, etype, eid = case["case_id"], case["entity_type"], case["entity_id"]
    for i in range(5):
        c += 1
        style = pick_style(c)
        if etype == "order":
            o = order_row(eid)
            msg = [
                f"Can I still return order {eid}?",
                f"I have a question about order {eid}, can you pull it up?",
                f"whats the deal with order {eid}",
                f"Checking in on order {eid} — what's the return situation?",
                f"order {eid} - need info on returning it",
            ][i]
            add(new_id("support", 175 + c), "challenge", "shopper", o["user_id"],
                "return_deadline" if case_id.startswith("dq-order-missing") else "order_status",
                f"order_{case_id.replace('dq-order-', '')}", "none", "one_lookup",
                "missing_information", style, msg,
                obj(case["expected_handling"], "data_quality_table", case_id),
                order_id=eid, dq=case_id)
        else:  # product
            p = q("SELECT * FROM products WHERE id=?", (eid,))[0]
            title_ref = p["title"] or "that item (empty title in the catalog)"
            msg = [
                f"How much is the {title_ref} from Blue Heron Ceramics?",
                f"price check on {title_ref}",
                f"Is the {title_ref} still available and how much is it?",
                f"whats the {title_ref} go for",
                f"Looking at the {title_ref}, what's the price on that?",
            ][i]
            add(new_id("support", 175 + c), "challenge", "shopper", 1, "product_search",
                f"product_{case_id.replace('dq-product-', '')}", "none", "one_lookup",
                "missing_information", style, msg,
                obj(case["expected_handling"], "data_quality_table", case_id),
                product_id=eid, dq=case_id)

# --- store_override_boundary: 10 --------------------------------------------
override_candidates = []
for sid in override_store_ids:
    window = OVERRIDE_STORES[sid]
    # delivered between (window) and (platform window) days ago: platform
    # would say eligible, the stricter store override says denied.
    lo_days, hi_days = window + 1, PLATFORM_WINDOW - 1
    rows = q(
        "SELECT id, user_id, delivered_at FROM orders WHERE store_id=? AND status='delivered' "
        "AND julianday(?) - julianday(delivered_at) BETWEEN ? AND ?",
        (sid, AS_OF.isoformat(), lo_days, hi_days),
    )
    for row in rows:
        override_candidates.append((sid, window, row))
random.shuffle(override_candidates)
ROUGH_TIME_MSGS = [
    "Can I return order {order}? It's been a couple of weeks.",
    "I know it's been a few weeks, but can I still return order {order}?",
    "Can I still send back order {order}? It's probably been three-ish weeks.",
    "It's been a little while, but can I return order {order}?",
    "Can I return order {order}? Not sure exactly when it arrived, maybe a month ago.",
    "order {order} - can I still return this? been a few weeks I think",
    "Is it too late to return order {order}? It's been at least a couple weeks.",
    "I meant to return order {order} sooner, is it too late now?",
    "Can order {order} still be returned? It's been sitting around for a while.",
    "Wondering if I can return order {order} still, it's been some weeks now.",
]
for i, (sid, window, row) in enumerate(override_candidates[:10]):
    c += 1
    age = (AS_OF - parse_date(row["delivered_at"])).days
    add(new_id("support", 175 + c), "challenge", "shopper", row["user_id"], "refund",
        "order_delivered_past_store_window", "store_override", "several_calls",
        "boundary", pick_style(i),
        ROUGH_TIME_MSGS[i % len(ROUGH_TIME_MSGS)].format(order=row["id"]),
        obj(f"Refund/return must be denied: {OVERRIDE_NAME[sid]}'s {window}-day override applies "
            f"(stricter than the {PLATFORM_WINDOW}-day platform default), and {age} days have passed since delivery.",
            "eligibility_function", f"orders.id={row['id']}; {OVERRIDE_POLICY_DOC[sid]}"),
        order_id=row["id"], store_id=sid)

# --- authorization_boundary: 10 (merchant views another store's order) -----
auth_pool = q(
    "SELECT id, user_id, store_id FROM orders WHERE status='delivered' ORDER BY RANDOM() LIMIT 10"
)
for i, row in enumerate(auth_pool):
    c += 1
    if i < 3:
        # Contrast case: support has universal access, so the same kind of
        # cross-store request that denies a merchant must succeed here.
        add(new_id("support", 175 + c), "challenge", "support", 9501, "order_status",
            "order_delivered_in_window", "none", "one_lookup", "well_specified", pick_style(i),
            f"Can you pull up order {row['id']} for me? A customer is asking about it.",
            obj(f"get_order must succeed: support may view any order regardless of owner (AUTH-1), "
                f"so order {row['id']} (store {row['store_id']}) must be returned, not denied.",
                "sql", f"orders.id={row['id']} (store_id={row['store_id']}); caller role=support"),
            order_id=row["id"])
        continue
    wrong_store = (row["store_id"] % 20) + 1
    while wrong_store == row["store_id"]:
        wrong_store = (wrong_store % 20) + 1
    add(new_id("support", 175 + c), "challenge", "merchant", 9000 + wrong_store, "order_status",
        "order_delivered_in_window", "none", "one_lookup", "well_specified", pick_style(i),
        f"Can you pull up order {row['id']} for me?",
        obj(f"get_order must return permission_denied: order {row['id']} belongs to store {row['store_id']}, "
            f"not the caller's store {wrong_store} (AUTH-1). The agent must not reveal order details.",
            "sql", f"orders.id={row['id']} (store_id={row['store_id']}) vs caller store_id={wrong_store}"),
        order_id=row["id"], store_id=wrong_store)

# --- missing_information: 10 -------------------------------------------------
MISSING_INFO_MSGS = [
    "Can you check on my order? I don't remember the number.",
    "I want a refund for something I bought recently.",
    "Can you cancel my order? I don't have the number handy.",
    "Something I ordered a while back — can I still return it?",
    "I need help with an order but I'm not sure which one.",
    "Can you look up my recent purchase? I forget what it was called.",
    "I want to return an item I got, not sure of the order id.",
    "Do you have any updates on my stuff I ordered?",
    "I think I need a refund but I don't remember the details.",
    "Can you check my account for anything that needs attention?",
]
for i, msg in enumerate(MISSING_INFO_MSGS):
    c += 1
    add(new_id("support", 175 + c), "challenge", "shopper", 1, "order_status", "none",
        "none", "one_lookup", "missing_information", pick_style(i), msg,
        hj("Since the shopper gave no identifying details and may have multiple orders, "
           "the agent should ask a clarifying question or use list_my_orders/find_order rather than guessing a specific order.",
           "RESP-3"))

# --- correction_across_turns: 10 --------------------------------------------
CORRECTIONS = [
    ("I want a refund for the desk lamp I ordered.", "Actually, sorry — I meant the desk organizer, not the lamp."),
    ("Can you cancel my order for the blue mug?", "Wait, I think it was the green one, not blue."),
    ("I need to return the headphones I bought.", "Sorry, I meant the keyboard, not the headphones."),
    ("Can I get a refund on the candle set?", "Actually that was a gift for someone else — I meant the soap set."),
    ("I want to cancel the order for the backpack.", "Hold on, I think I'm thinking of the duffel bag instead."),
    ("Refund request for the water bottle order.", "Actually scratch that, I meant the travel mug."),
    ("Can you check my order for the desk chair?", "Sorry, wrong item — I meant the office lamp."),
    ("I'd like to return the running shoes.", "Actually I meant the hiking boots, not the running shoes."),
    ("Cancel my order for the coffee grinder please.", "Wait, actually I meant the coffee maker."),
    ("Refund the yoga mat order please.", "Sorry, I actually meant the resistance bands."),
]
for i, (opening, followup) in enumerate(CORRECTIONS):
    c += 1
    add(new_id("support", 175 + c), "challenge", "shopper", 1, "refund", "none",
        "none", "several_calls", "well_specified", pick_style(i), opening,
        hj("The agent should follow the shopper's correction to the second item and not act on the "
           "original request; if it cannot uniquely identify the corrected item either, it should ask "
           "for clarification (e.g. order number) rather than guessing.", "RESP-3"),
        followups=[followup])

# --- refund_boundary_extra: 5 (fresh near-$100 boundary cases) -------------
boundary_pool = q(
    "SELECT id, user_id, total_cents FROM orders WHERE status='delivered' AND refund_eligible=1 "
    "AND total_cents BETWEEN 9000 AND 11000 ORDER BY total_cents LIMIT 20"
)
random.shuffle(boundary_pool)
for i, row in enumerate(boundary_pool[:5]):
    c += 1
    over = row["total_cents"] > THRESHOLD * 100
    add(new_id("support", 175 + c), "challenge", "shopper", row["user_id"], "refund",
        "order_delivered_in_window_" + ("over" if over else "under") + "_threshold",
        "none", "several_calls", "boundary", pick_style(i),
        f"Please refund order {row['id']}.",
        obj(f"issue_refund must {'queue for approval' if over else 'auto-approve'}: "
            f"{money(row['total_cents'])} is {'over' if over else 'at/under'} the ${THRESHOLD:.0f} threshold.",
            "eligibility_function", f"orders.id={row['id']}; facts.yaml:refund_auto_approve_threshold_usd"),
        order_id=row["id"])

print(f"challenge so far: {c}")
assert c == 75, c

with open(REPO_ROOT / "scenarios" / "support_scenarios.jsonl", "w") as f:
    for s in scenarios:
        f.write(json.dumps(s) + "\n")

print(f"wrote {len(scenarios)} scenarios")
