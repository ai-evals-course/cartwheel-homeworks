"""Contract tests for the two tools added in Homework 1, Part A.

Both were added after the Part B conversations showed a gap:
`get_product` because get_order returns a product_id that nothing could
resolve to a name, and `check_return_eligibility` because no tool exposed the
world's current date, so the agent could not say whether a return window had
closed.
"""

from __future__ import annotations

import sqlite3

from agent import db, tools
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
SHOPPER_2 = AuthContext(user_id=2, role="shopper")
SUPPORT = AuthContext(user_id=9501, role="support")


def test_get_product_returns_the_title_an_order_only_references(world: dict) -> None:
    conn = db.connect()
    try:
        product_id = db.get_order(conn, 4127).product_id
        expected = db.get_product(conn, product_id)
    finally:
        conn.close()

    result = tools.get_product(SHOPPER_1, product_id)
    assert result["ok"] is True
    assert result["product"]["product_id"] == product_id
    assert result["product"]["title"] == expected.title
    assert result["product"]["price_usd"] == expected.price_cents / 100
    assert result["product"]["store_name"] == "Blue Heron Ceramics"


def test_get_product_unknown_id_is_not_found(world: dict) -> None:
    missing = tools.get_product(SHOPPER_1, 999_999)
    assert missing["ok"] is False
    assert missing["error"] == "not_found"


def test_eligibility_inside_window_uses_the_platform_default(world: dict) -> None:
    result = tools.check_return_eligibility(SHOPPER_1, 4127)
    assert result["ok"] is True
    assert result["refund_eligible"] is True
    assert result["consistent"] is True
    assert result["return_window_days"] == 30
    assert result["window_source"] == "platform_default"
    assert result["policy_id"] == "cw-returns"
    assert result["as_of"] == "2026-07-01"
    assert result["days_since_delivery"] <= 30


def test_eligibility_outside_window_reports_the_closed_deadline(world: dict) -> None:
    result = tools.check_return_eligibility(SHOPPER_1, 3980)
    assert result["refund_eligible"] is False
    assert result["consistent"] is True
    assert result["days_since_delivery"] > result["return_window_days"]
    assert result["return_deadline"] < result["as_of"]


def test_eligibility_prefers_the_store_override_and_cites_its_doc(world: dict) -> None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT o.id, s.return_window_days_override AS ovr, s.slug "
            "FROM orders o JOIN stores s ON o.store_id = s.id "
            "WHERE s.return_window_days_override IS NOT NULL LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    result = tools.check_return_eligibility(SUPPORT, row["id"])
    assert result["return_window_days"] == row["ovr"] != 30
    assert result["window_source"] == "store_override"
    assert result["policy_id"] == f"store-{row['slug']}-policy"


def test_eligibility_flags_an_internally_inconsistent_order(world: dict) -> None:
    # Order 8001 is a seeded data-quality case: delivered before it shipped,
    # and stamped not eligible despite a delivery date inside the window.
    result = tools.check_return_eligibility(SUPPORT, 8001)
    assert result["ok"] is True
    assert result["refund_eligible"] is False
    assert result["computed_eligible"] is True
    assert result["consistent"] is False


def test_eligibility_is_scoped_like_get_order(world: dict) -> None:
    denied = tools.check_return_eligibility(SHOPPER_2, 4127)
    assert denied["ok"] is False
    assert denied["error"] == "permission_denied"

    missing = tools.check_return_eligibility(SHOPPER_1, 999_999)
    assert missing["error"] == "not_found"
