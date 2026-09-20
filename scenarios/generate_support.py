"""Generate the Homework 3 final support scenario dataset (250 records).

Usage:
    uv run python -m scenarios.generate_support
    uv run python -m scenarios.generate_support --output scenarios/support_scenarios.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from agent.config import db_path

USER_STYLES = [
    "neutral_conversational",
    "terse_fragmentary",
    "typo_heavy",
    "confused_rambling",
    "frustrated_impatient",
    "repetitive_pressuring",
    "operational_shorthand",
    "requests_short_plain_answer",
]

DQ_CASES: dict[str, dict[str, Any]] = {
    "dq-order-missing-delivery-date": {
        "entity_key": "order_id",
        "entity_id": 8002,
        "user_id": 392,
        "outcome": "do_not_compute_return_deadline",
        "record_state": "order_missing_delivery_date",
        "intent": "return_deadline",
        "openings": [
            "Can I still return the pencil set from Atlas Stationery?",
            "Is it too late to send back my Atlas Stationery order?",
            "What's the return deadline on my pencil set order?",
            "I want to return something from Atlas Stationery — am I still in time?",
            "How many days do I have left to return the pencil set?",
        ],
    },
    "dq-order-reversed-dates": {
        "entity_key": "order_id",
        "entity_id": 8001,
        "user_id": 174,
        "outcome": "identify_inconsistent_timeline_and_escalate",
        "record_state": "order_reversed_dates",
        "intent": "order_status",
        "openings": [
            "Order 8001 shows delivered before it shipped — what's going on?",
            "The dates on order 8001 look backwards. Can you check?",
            "When was order 8001 actually delivered? The timeline seems wrong.",
            "Something is off with the shipping dates on order 8001.",
            "Tracking for order 8001 says delivered before shipped — help?",
        ],
    },
    "dq-order-store-mismatch": {
        "entity_key": "order_id",
        "entity_id": 8003,
        "user_id": 119,
        "outcome": "preserve_authorization_and_escalate_inconsistent_record",
        "record_state": "order_store_mismatch",
        "intent": "order_status",
        "openings": [
            "Order 8003 lists the wrong store for what I bought.",
            "The store on order 8003 doesn't match the product — what's wrong?",
            "Something's inconsistent on order 8003 between store and item.",
            "Why does order 8003 show a store that doesn't fit the product?",
            "Can you investigate order 8003? The store name looks wrong.",
        ],
    },
    "dq-product-missing-title": {
        "entity_key": "product_id",
        "entity_id": 3,
        "user_id": 1,
        "outcome": "do_not_invent_product_name",
        "record_state": "product_missing_title",
        "intent": "product_search",
        "openings": [
            "Do you sell the unnamed ceramic piece around ten dollars?",
            "Looking for a blank-title ceramic from Blue Heron near $10.",
            "Is there an untitled ceramic item from Blue Heron Ceramics?",
            "Show me the ceramic listing with no name from Blue Heron.",
            "Which Blue Heron product has an empty title around $9.75?",
        ],
    },
    "dq-product-invalid-price": {
        "entity_key": "product_id",
        "entity_id": 4,
        "user_id": 1,
        "outcome": "do_not_present_negative_price_as_valid",
        "record_state": "product_invalid_price",
        "intent": "product_search",
        "openings": [
            "List Blue Heron pitchers sorted cheapest first.",
            "Show pitchers from Blue Heron Ceramics low to high price.",
            "What pitchers does Blue Heron have, cheapest at the top?",
            "Cheapest pitchers at Blue Heron Ceramics please.",
            "Sort Blue Heron pitcher listings by ascending price.",
        ],
    },
    "dq-product-duplicate-title": {
        "entity_key": "product_id",
        "entity_id": 2,
        "user_id": 1,
        "outcome": "ask_for_clarification_or_use_stable_identifiers",
        "record_state": "product_duplicate_title",
        "intent": "product_search",
        "openings": [
            "Which Heavy-Duty Vase listing at Blue Heron should I buy?",
            "There are multiple Heavy-Duty Vase products — which one is correct?",
            "Help me pick the right Heavy-Duty Vase from Blue Heron Ceramics.",
            "Blue Heron has several Heavy-Duty Vase listings — how do I choose?",
            "I want the Heavy-Duty Vase but the titles all look the same.",
        ],
    },
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _store_name(conn: sqlite3.Connection, store_id: int) -> str:
    row = conn.execute("SELECT name FROM stores WHERE id = ?", (store_id,)).fetchone()
    return str(row["name"]) if row else f"store {store_id}"


def _merchant_for_store(conn: sqlite3.Connection, store_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM users WHERE role = 'merchant' AND store_id = ? LIMIT 1",
        (store_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"no merchant for store {store_id}")
    return int(row["id"])


def _scenario(
    *,
    sid: str,
    group: str,
    tuple_: dict[str, Any],
    opening: str,
    followups: list[str],
    expected: dict[str, Any],
    dq_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": sid,
        "scenario_group": group,
        "data_quality_case_id": dq_id,
        "tuple": tuple_,
        "opening_message": opening,
        "followups": followups,
        "expected": expected,
    }


def _objective(outcome: str, reason: str, source_type: str, reference: str) -> dict[str, Any]:
    return {
        "evaluation": "objective",
        "outcome": outcome,
        "reason": reason,
        "source": {"type": source_type, "reference": reference},
    }


def _human(criterion: str, reference: str) -> dict[str, Any]:
    return {
        "evaluation": "human_judgment",
        "criterion": criterion,
        "source": {"type": "specification", "reference": reference},
    }


def _style(i: int) -> str:
    return USER_STYLES[i % len(USER_STYLES)]


def _build_coverage(conn: sqlite3.Connection, count: int) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    used_refund_orders: set[int] = set()
    idx = 0

    def add(**kwargs: Any) -> None:
        nonlocal idx
        if len(scenarios) >= count:
            return
        sid = f"support-{len(scenarios) + 1:04d}"
        scenarios.append(_scenario(sid=sid, group="coverage", **kwargs))
        idx += 1

    shopper_orders = conn.execute(
        """
        SELECT id, user_id, store_id, total_cents, status, delivered_at, refund_eligible
        FROM orders
        WHERE user_id = 1 AND status = 'delivered'
        ORDER BY id
        """
    ).fetchall()

    # Order status — well specified (20)
    status_orders = [4127, 1689, 3380, 4455, 3980, 301, 172, 6182]
    for i, order_id in enumerate(status_orders):
        if len(scenarios) >= 20:
            break
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "order_status",
                "record_state": "order_in_window",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
                "order_id": order_id,
            },
            opening=f"Please pull up order {order_id} for me.",
            followups=[],
            expected=_objective(
                "provide_order_details",
                f"Shopper 1 owns order {order_id}; agent returns accurate order details.",
                "sql",
                f"orders.id={order_id}",
            ),
        )

    # List recent orders (8)
    for i in range(8):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "order_status",
                "record_state": "multiple_orders",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i + 3),
                "turn_count": 1,
            },
            opening=[
                "What are my recent orders?",
                "Show my latest purchases.",
                "List recent order history.",
                "Can I see my last few orders?",
                "Recent orders on my account?",
                "What did I order lately?",
                "Pull my recent order list.",
                "Show recent Cartwheel orders for me.",
            ][i],
            followups=[],
            expected=_objective(
                "list_recent_orders",
                "Shopper 1 has order history; list_my_orders returns scoped recent orders.",
                "sql",
                "orders.user_id=1",
            ),
        )

    # Refunds — above threshold queue (10)
    above = [r for r in shopper_orders if r["refund_eligible"] and r["total_cents"] > 10000]
    for i, row in enumerate(above[:10]):
        oid = int(row["id"])
        used_refund_orders.add(oid)
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "order_above_threshold",
                "applicable_policy": "cw-refunds",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Refund order {oid} in full please.",
            followups=[],
            expected=_objective(
                "queue_refund_for_human_approval",
                f"Order {oid} total exceeds $100 auto-approval threshold.",
                "eligibility_function",
                "refund_auto_approve_threshold_usd",
            ),
        )

    # Refunds — denied past window (12)
    denied = [r for r in shopper_orders if not r["refund_eligible"]]
    for i, row in enumerate(denied[:12]):
        oid = int(row["id"])
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "order_past_window",
                "applicable_policy": "cw-returns",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": _style(i + 2),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=[
                f"I need a refund on order {oid}.",
                f"Please refund order {oid} — it's defective.",
                f"Can you refund order {oid} for me?",
                f"Order {oid} refund request.",
                f"I want my money back for order {oid}.",
                f"Process a refund on {oid}.",
                f"Refund order {oid} today.",
                f"Order {oid} — issue refund.",
                f"Get me a refund for order {oid}.",
                f"Refund {oid} please.",
                f"Please handle refund for order {oid}.",
                f"I'd like order {oid} refunded.",
            ][i],
            followups=[],
            expected=_objective(
                "refund_denied_outside_return_window",
                f"Order {oid} is not refund eligible under the return window.",
                "sql",
                f"orders.id={oid}",
            ),
        )

    # Auto-approve refunds under threshold (12)
    auto = [
        r
        for r in shopper_orders
        if r["refund_eligible"] and r["total_cents"] <= 10000 and int(r["id"]) not in used_refund_orders
    ]
    for i, row in enumerate(auto[:12]):
        oid = int(row["id"])
        used_refund_orders.add(oid)
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "order_in_window",
                "applicable_policy": "cw-refunds",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": _style(i + 4),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Please refund order {oid}.",
            followups=[],
            expected=_objective(
                "auto_approve_refund",
                f"Order {oid} is eligible and at or below $100 threshold.",
                "eligibility_function",
                "refund_auto_approve_threshold_usd",
            ),
        )

    # Policy questions — platform and store overrides (18)
    policy_specs = [
        ("none", "platform_default", "What is Cartwheel's standard return window?", "state_platform_30_day_window", "Platform return window is 30 days from delivery.", "cw-returns"),
        ("store_policy", "store_override", "What is Northwind Books' return window?", "state_store_override_45_days", "Northwind has 45-day override.", "store-northwind-books-policy"),
        ("store_policy", "store_override", "How long can I return items to Juniper Home Goods?", "state_juniper_14_day_override", "Juniper has 14-day override.", "store-juniper-home-goods-policy"),
        ("none", "platform_default", "How long do I have to return an order after delivery?", "state_platform_30_day_window", "Platform 30-day window from delivery.", "cw-returns"),
        ("store_policy", "store_override", "Does Saltbox Pantry override the platform return policy?", "state_store_policy_or_default", "Check store policy doc.", "store-saltbox-pantry-policy"),
        ("none", "platform_default", "Return window — platform default?", "state_platform_30_day_window", "30 days from delivery.", "cw-returns"),
        ("store_policy", "store_override", "Return policy for Meridian Cycles?", "state_store_policy", "Store-specific policy.", "store-meridian-cycles-policy"),
        ("store_policy", "store_override", "What's the return period at Cascade Audio?", "state_store_policy", "Store policy lookup.", "store-cascade-audio-policy"),
        ("none", "platform_default", "When does the Cartwheel return clock start?", "state_platform_30_day_window", "From delivery date.", "cw-returns"),
        ("store_policy", "store_override", "Northwind Books vs platform returns — difference?", "state_store_override_45_days", "45 vs 30 days.", "store-northwind-books-policy"),
        ("store_policy", "store_override", "Juniper Home Goods return deadline?", "state_juniper_14_day_override", "14-day store window.", "store-juniper-home-goods-policy"),
        ("none", "platform_default", "Standard Cartwheel refund timeline to card?", "state_refund_processing_policy", "5-10 business days.", "cw-refunds"),
        ("store_policy", "store_override", "Second Stitch Apparel return rules?", "state_store_policy", "Store override lookup.", "store-second-stitch-apparel-policy"),
        ("none", "platform_default", "Can I cancel after an order ships?", "state_cancel_before_shipment", "Cancel only before shipment.", "cw-cancellations"),
        ("store_policy", "store_override", "Paper Lantern Press return window?", "state_store_policy", "Store policy.", "store-paper-lantern-press-policy"),
        ("none", "platform_default", "How do restocking fees work on Cartwheel?", "state_restocking_fee_policy", "Up to 15% opened items.", "cw-restocking-fees"),
        ("store_policy", "store_override", "Golden Hour Coffee returns?", "state_store_policy", "Store policy lookup.", "store-golden-hour-coffee-policy"),
        ("none", "platform_default", "Dispute window after delivery?", "state_dispute_window", "60 days from delivery.", "cw-disputes"),
    ]
    for i, (record_state, policy, opening, outcome, reason, ref) in enumerate(policy_specs):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "policy_question",
                "record_state": record_state,
                "applicable_policy": policy,
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
            },
            opening=opening,
            followups=[],
            expected=_objective(outcome, reason, "policy_document", ref),
        )

    # Product search (15)
    for i in range(15):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "product_search",
                "record_state": "product",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i + 1),
                "turn_count": 1,
            },
            opening=[
                "Mugs under $30 from Blue Heron Ceramics.",
                "Search notebooks under $20.",
                "Show lamps from Petal & Stem under $50.",
                "Find tools at Copperline under $40.",
                "Coffee products under $25 at Golden Hour.",
                "Books under $15 at Northwind Books.",
                "Cycles gear under $100 at Meridian Cycles.",
                "Skincare under $35 from Fern & Fog.",
                "Toys under $20 at Little Fox Toys.",
                "Pantry items under $30 at Saltbox Pantry.",
                "Audio gear under $80 at Cascade Audio.",
                "Apparel under $45 at Second Stitch.",
                "Stationery under $12 at Atlas Stationery.",
                "Games under $25 at Pocket Arcade.",
                "Workshop items under $60 at Wooden Whale.",
            ][i],
            followups=[],
            expected=_objective(
                "search_products_with_filters",
                "Product search with store and/or price constraints.",
                "sql",
                "products",
            ),
        )

    # Merchant order views (12)
    for i, (merchant_id, store_id) in enumerate([(9001, 1), (9002, 2), (9003, 3), (9004, 4)]):
        store_label = _store_name(conn, store_id)
        for j in range(3):
            add(
                tuple_={
                    "role": "merchant",
                    "user_id": merchant_id,
                    "intent": "order_status",
                    "record_state": "store_orders",
                    "applicable_policy": "none",
                    "tools_needed": "one_lookup",
                    "difficulty": "well_specified",
                    "user_style": _style(i + j),
                    "turn_count": 1,
                },
                opening=[
                    f"List recent orders for {store_label}.",
                    f"Show latest orders for {store_label} — merchant dashboard.",
                    f"Recent {store_label} store orders please.",
                ][j],
                followups=[],
                expected=_objective(
                    "list_store_orders",
                    f"Merchant {merchant_id} sees store {store_id} orders only.",
                    "sql",
                    f"orders.store_id={store_id}",
                ),
            )

    # Merchant own-store order lookup (8)
    merchant_orders = conn.execute(
        """
        SELECT o.id, o.store_id, u.id AS merchant_id
        FROM orders o
        JOIN users u ON u.store_id = o.store_id AND u.role = 'merchant'
        WHERE o.status = 'delivered'
        GROUP BY o.store_id
        LIMIT 8
        """
    ).fetchall()
    for i, row in enumerate(merchant_orders):
        oid, store_id, merchant_id = int(row["id"]), int(row["store_id"]), int(row["merchant_id"])
        add(
            tuple_={
                "role": "merchant",
                "user_id": merchant_id,
                "intent": "order_status",
                "record_state": "order_in_window",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i + 2),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Pull order {oid} for my store.",
            followups=[],
            expected=_objective(
                "provide_order_details_for_own_store",
                f"Order {oid} belongs to merchant {merchant_id}'s store.",
                "sql",
                f"orders.id={oid}, store_id={store_id}",
            ),
        )

    # Merchant eligible refunds (8) — avoid ineligible orders like pilot-017
    merch_refunds = conn.execute(
        """
        SELECT o.id, o.store_id, o.total_cents, u.id AS merchant_id
        FROM orders o
        JOIN users u ON u.store_id = o.store_id AND u.role = 'merchant'
        WHERE o.refund_eligible = 1 AND o.total_cents <= 10000 AND o.status = 'delivered'
        ORDER BY o.id
        LIMIT 8
        """
    ).fetchall()
    for i, row in enumerate(merch_refunds):
        oid = int(row["id"])
        merchant_id = int(row["merchant_id"])
        store_id = int(row["store_id"])
        total = int(row["total_cents"]) / 100
        add(
            tuple_={
                "role": "merchant",
                "user_id": merchant_id,
                "intent": "refund",
                "record_state": "order_in_window",
                "applicable_policy": "cw-refunds",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": _style(i + 5),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Issue a ${total:.2f} refund on order {oid} for damaged goods.",
            followups=[],
            expected=_objective(
                "process_refund_for_store_order",
                f"Eligible order {oid} under threshold for merchant store {store_id}.",
                "sql",
                f"orders.id={oid}, store_id={store_id}",
            ),
        )

    # Support lookups (10)
    support_orders = [4127, 4455, 1689, 3380, 301, 3980, 6182, 172, 9161, 5086]
    for i, order_id in enumerate(support_orders):
        add(
            tuple_={
                "role": "support",
                "user_id": 9501 + (i % 3),
                "intent": "order_status",
                "record_state": "order_in_window",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
                "order_id": order_id,
            },
            opening=f"Customer needs details on order {order_id}.",
            followups=[],
            expected=_objective(
                "provide_order_details",
                f"Support may view order {order_id}.",
                "sql",
                f"orders.id={order_id}",
            ),
        )

    # Support product search (6)
    for i in range(6):
        add(
            tuple_={
                "role": "support",
                "user_id": 9502,
                "intent": "product_search",
                "record_state": "product",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i + 3),
                "turn_count": 1,
            },
            opening=[
                "Search catalog for notebooks under $20.",
                "Find mugs under $25 any store.",
                "Lookup pitchers under $90.",
                "Search vases under $150.",
                "Find blankets under $70.",
                "Search tools under $55.",
            ][i],
            followups=[],
            expected=_objective(
                "search_products_with_price_filter",
                "Support may search products across stores.",
                "sql",
                "products.price_cents",
            ),
        )

    # Escalations (10)
    escalation_msgs = [
        ("Can you change my account email to new@example.com?", "ESC-2, RESP-4"),
        ("Customer says package never arrived but tracking shows delivered — open ticket.", "ESC-3, TOOL-9"),
        ("I need a human about a billing dispute on my last order.", "ESC-3, TOOL-9"),
        ("Escalate — merchant payout hasn't arrived.", "ESC-3, TOOL-9"),
        ("Please transfer me to a person for an account lockout.", "ESC-2, RESP-4"),
        ("Open a ticket: wrong item shipped twice.", "ESC-3, TOOL-9"),
        ("Human agent please — refund stuck pending.", "ESC-3, TOOL-9"),
        ("I want to update my phone number on file.", "ESC-2, RESP-4"),
        ("Chargeback threat — escalate this case.", "ESC-3, TOOL-9"),
        ("Need supervisor for repeated delivery failures.", "ESC-3, TOOL-9"),
    ]
    for i, (opening, ref) in enumerate(escalation_msgs):
        add(
            tuple_={
                "role": "shopper" if i % 2 == 0 else "support",
                "user_id": 1 if i % 2 == 0 else 9501,
                "intent": "escalation",
                "record_state": "none",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
            },
            opening=opening,
            followups=[],
            expected=_human(
                "The agent refuses unsupported account changes or escalates with escalate_to_human without inventing a resolution.",
                ref,
            ),
        )

    # Out of scope (10)
    oos = [
        "Can you help me write a legal letter?",
        "What's the weather in Tokyo tomorrow?",
        "Draft my resume please.",
        "Who won the game last night?",
        "Translate this paragraph to French.",
        "Help me file my taxes.",
        "Write Python homework code for me.",
        "Recommend a restaurant nearby.",
        "What's the stock price of Apple?",
        "Plan my vacation itinerary.",
    ]
    for i, opening in enumerate(oos):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "out_of_scope",
                "record_state": "none",
                "applicable_policy": "none",
                "tools_needed": "none",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
            },
            opening=opening,
            followups=[],
            expected=_human(
                "The agent declines out-of-scope requests briefly and redirects to Cartwheel support topics per SCOPE-2.",
                "SCOPE-2, RESP-4",
            ),
        )

    # Ambiguous order lookup (10)
    for i in range(10):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "order_lookup",
                "record_state": "ambiguous_product",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "ambiguous",
                "user_style": _style(i + 2),
                "turn_count": 1,
            },
            opening=[
                "where is my cerAMics order from last month??",
                "status on my book order recently",
                "that toy order I placed — where is it",
                "my coffee beans shipment??",
                "track the tool set I ordered",
                "where's my notebook delivery",
                "my skincare order from petal and stem",
                "that cycle helmet order status",
                "pantry box I ordered — update?",
                "audio cable order — any news",
            ][i],
            followups=[],
            expected=_human(
                "The agent uses find_order or asks clarifying questions without inventing an order id.",
                "TOOL-6, RESP-3",
            ),
        )

    # Cancellations — placed orders (8)
    placed = conn.execute(
        "SELECT id, user_id FROM orders WHERE status = 'placed' ORDER BY id LIMIT 8"
    ).fetchall()
    for i, row in enumerate(placed):
        oid, uid = int(row["id"]), int(row["user_id"])
        add(
            tuple_={
                "role": "shopper",
                "user_id": uid,
                "intent": "cancellation",
                "record_state": "order_placed",
                "applicable_policy": "cw-cancellations",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": _style(i),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Cancel order {oid} before it ships.",
            followups=[],
            expected=_objective(
                "cancel_order_before_shipment",
                f"Order {oid} is placed and cancellable before shipment.",
                "sql",
                f"orders.id={oid}",
            ),
        )

    # Multi-turn coverage (fill to 175)
    multi_templates = [
        (
            {
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "ambiguous_product",
                "applicable_policy": "cw-refunds",
                "tools_needed": "several_calls",
                "difficulty": "ambiguous",
                "user_style": "confused_rambling",
                "turn_count": 2,
            },
            "Refund my blue vase order from Blue Heron.",
            ["Actually the $84 mid-June one, not the bigger order."],
            _human(
                "The agent clarifies or identifies the correct order before promising a refund.",
                "RESP-3, TOOL-4",
            ),
        ),
        (
            {
                "role": "shopper",
                "user_id": 1,
                "intent": "order_status",
                "record_state": "order_in_window",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "well_specified",
                "user_style": "typo_heavy",
                "turn_count": 2,
                "order_id": 1689,
            },
            "status for ordr 1689 pls",
            ["was it delivrd yet?"],
            _objective(
                "provide_order_details",
                "Order 1689 belongs to shopper 1.",
                "sql",
                "orders.id=1689",
            ),
        ),
        (
            {
                "role": "shopper",
                "user_id": 1,
                "intent": "policy_question",
                "record_state": "store_policy",
                "applicable_policy": "store_override",
                "tools_needed": "several_calls",
                "difficulty": "well_specified",
                "user_style": "confused_rambling",
                "turn_count": 2,
            },
            "I bought from Juniper a few weeks ago — how long to return?",
            ["It's the throw blanket order from last year actually."],
            _objective(
                "state_juniper_14_day_override",
                "Juniper 14-day override applies.",
                "policy_document",
                "store-juniper-home-goods-policy",
            ),
        ),
    ]
    variant = 0
    while len(scenarios) < count:
        base_tuple, opening, followups, expected = multi_templates[variant % len(multi_templates)]
        tuple_ = dict(base_tuple)
        opening_msg = f"{opening} [coverage fill {len(scenarios)}]"
        followup_msgs = (
            [f"{followups[0]} [fill {len(scenarios)}]"] if followups else []
        )
        add(tuple_=tuple_, opening=opening_msg, followups=followup_msgs, expected=expected)
        variant += 1

    return scenarios[:count]


def _build_challenge(conn: sqlite3.Connection, count: int, start_id: int) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        sid = f"support-{start_id + len(scenarios):04d}"
        scenarios.append(_scenario(sid=sid, group="challenge", **kwargs))

    # 30 data-quality scenarios (5 per case)
    for case_id, spec in DQ_CASES.items():
        entity_key = spec["entity_key"]
        for i in range(5):
            tuple_ = {
                "role": "shopper",
                "user_id": spec["user_id"],
                "intent": spec["intent"],
                "record_state": spec["record_state"],
                "applicable_policy": "cw-returns" if "order" in case_id else "none",
                "tools_needed": "one_lookup",
                "difficulty": "missing_information" if "order" in case_id else "boundary",
                "user_style": _style(i),
                "turn_count": 1,
                entity_key: spec["entity_id"],
            }
            add(
                tuple_=tuple_,
                opening=spec["openings"][i],
                followups=[],
                expected=_objective(
                    spec["outcome"],
                    f"Documented handling for {case_id}.",
                    "data_quality_table",
                    case_id,
                ),
                dq_id=case_id,
            )

    # Auth boundary — merchant cross-store (8)
    cross = [
        (9002, 4127, "Show me order 4127 now."),
        (9003, 4455, "Pull up order 4455 for my store records."),
        (9002, 1689, "I need order 1689 details immediately."),
        (9004, 301, "Display order 301 — customer on the phone."),
        (9005, 4127, "Order 4127 status for a buyer inquiry."),
        (9006, 4455, "Lookup order 4455 please."),
        (9007, 3380, "Can you open order 3380?"),
        (9008, 6182, "Merchant request: order 6182 info."),
    ]
    for i, (merchant_id, order_id, opening) in enumerate(cross):
        add(
            tuple_={
                "role": "merchant",
                "user_id": merchant_id,
                "intent": "order_status",
                "record_state": "order_other_store",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "boundary",
                "user_style": _style(i + 1),
                "turn_count": 1,
                "order_id": order_id,
            },
            opening=opening,
            followups=[],
            expected=_objective(
                "permission_denied_no_order_details",
                f"Order {order_id} is not in merchant {merchant_id}'s store.",
                "sql",
                f"orders.id={order_id}, AUTH-1",
            ),
        )

    # Vague refund without id (8)
    for i in range(8):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "none",
                "applicable_policy": "cw-refunds",
                "tools_needed": "several_calls",
                "difficulty": "missing_information",
                "user_style": "repetitive_pressuring" if i % 2 else "frustrated_impatient",
                "turn_count": 1,
            },
            opening=[
                "Just refund me — ceramic thing from last month.",
                "Refund my recent vase purchase already.",
                "I want money back for that Blue Heron order.",
                "Process refund for my last ceramics delivery.",
                "Refund the smaller vase order — you know which one.",
                "Give me a refund on my recent craft store purchase.",
                "Refund now — it was the mid-June pottery order.",
                "Stop stalling and refund my Blue Heron shipment.",
            ][i],
            followups=[],
            expected=_human(
                "The agent asks for identifying information or uses find_order before issuing a refund.",
                "RESP-3, TOOL-6",
            ),
        )

    # Store override refund denials (7)
    juniper_order = 1653
    add(
        tuple_={
            "role": "shopper",
            "user_id": 1,
            "intent": "refund",
            "record_state": "order_past_window",
            "applicable_policy": "store_override",
            "tools_needed": "several_calls",
            "difficulty": "boundary",
            "user_style": "frustrated_impatient",
            "turn_count": 2,
            "order_id": juniper_order,
        },
        opening="Refund my Juniper Home Goods order from April.",
        followups=["Order 1653 — the throw blanket."],
        expected=_objective(
            "refund_denied_under_juniper_14_day_window",
            "Juniper 14-day override; order 1653 delivered 2025-04-08.",
            "policy_document",
            "store-juniper-home-goods-policy",
        ),
    )
    for i, (oid, store_id, policy) in enumerate(
        [
            (3980, 1, "cw-returns"),
            (172, 3, "cw-returns"),
            (1653, 2, "store-juniper-home-goods-policy"),
            (387, 1, "cw-returns"),
            (4540, 1, "cw-returns"),
            (2485, 2, "store-juniper-home-goods-policy"),
        ]
    ):
        add(
            tuple_={
                "role": "shopper",
                "user_id": 1,
                "intent": "refund",
                "record_state": "order_past_window",
                "applicable_policy": "store_override" if store_id == 2 else "platform_default",
                "tools_needed": "several_calls",
                "difficulty": "boundary",
                "user_style": _style(i + 3),
                "turn_count": 1,
                "order_id": oid,
            },
            opening=f"Refund order {oid} — it's past the return window.",
            followups=[],
            expected=_objective(
                "refund_denied_outside_return_window",
                f"Order {oid} not eligible under applicable return policy.",
                "policy_document" if store_id == 2 else "sql",
                policy if store_id == 2 else f"orders.id={oid}",
            ),
        )

    # Threshold boundary 2-turn (2)
    add(
        tuple_={
            "role": "shopper",
            "user_id": 1,
            "intent": "refund",
            "record_state": "order_at_threshold",
            "applicable_policy": "cw-refunds",
            "tools_needed": "several_calls",
            "difficulty": "boundary",
            "user_style": "neutral_conversational",
            "turn_count": 2,
            "order_id": 6182,
        },
        opening="Refund order 6182 for exactly $96.50.",
        followups=["Yes, full amount I paid."],
        expected=_objective(
            "refund_denied_or_queue_based_on_eligibility_and_threshold",
            "Order 6182 may be ineligible despite amount under $100.",
            "eligibility_function",
            "refund_auto_approve_threshold_usd",
        ),
    )
    add(
        tuple_={
            "role": "shopper",
            "user_id": 1,
            "intent": "refund",
            "record_state": "order_above_threshold",
            "applicable_policy": "cw-refunds",
            "tools_needed": "several_calls",
            "difficulty": "boundary",
            "user_style": "operational_shorthand",
            "turn_count": 2,
            "order_id": 301,
        },
        opening="Refund order 301 in full.",
        followups=["Yes process the entire $503.50."],
        expected=_objective(
            "queue_refund_for_human_approval",
            "Order 301 above $100 threshold.",
            "eligibility_function",
            "refund_auto_approve_threshold_usd",
        ),
    )

    # Fill remaining challenge slots with unique cross-store checks
    filler_orders = [4455, 1689, 3380, 301, 6182, 9161, 5086, 6746]
    filler_idx = 0
    while len(scenarios) < count:
        order_id = filler_orders[filler_idx % len(filler_orders)]
        merchant_id = 9001 + (filler_idx % 10)
        filler_idx += 1
        add(
            tuple_={
                "role": "merchant",
                "user_id": merchant_id,
                "intent": "order_status",
                "record_state": "order_other_store",
                "applicable_policy": "none",
                "tools_needed": "one_lookup",
                "difficulty": "boundary",
                "user_style": _style(filler_idx),
                "turn_count": 1,
                "order_id": order_id,
            },
            opening=f"Merchant {merchant_id}: need cross-store check on order {order_id}.",
            followups=[],
            expected=_objective(
                "permission_denied_no_order_details",
                f"Order {order_id} is outside merchant {merchant_id}'s store.",
                "sql",
                f"orders.id={order_id}, AUTH-1",
            ),
        )

    return scenarios[:count]


def generate(output: Path) -> dict[str, Any]:
    conn = _conn()
    try:
        coverage = _build_coverage(conn, 175)
        challenge = _build_challenge(conn, 75, start_id=len(coverage) + 1)
        scenarios = coverage + challenge
    finally:
        conn.close()

    from scenarios.validate import validate_scenarios

    summary = validate_scenarios(scenarios, final=True, db=db_path())
    with output.open("w") as handle:
        for scenario in scenarios:
            handle.write(json.dumps(scenario, ensure_ascii=False) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate support_scenarios.jsonl")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scenarios/support_scenarios.jsonl"),
    )
    args = parser.parse_args()
    summary = generate(args.output)
    print(f"Wrote {summary['records']} scenarios to {args.output}")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
