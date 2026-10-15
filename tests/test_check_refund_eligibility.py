"""Tests for the student-added check_refund_eligibility tool (HW1 Part A)."""

from __future__ import annotations

import sqlite3

from agent import tools
from agent.agent import TOOLS_BY_ROLE
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_eligible_order_above_threshold(world: dict) -> None:
    # Demo order 4455: $240, delivered 2026-06-26, store 1 (no override).
    result = tools.check_refund_eligibility(SHOPPER_1, 4455)
    assert result["ok"] is True
    assert result["eligible"] is True
    assert result["return_window_days"] == 30
    assert result["window_source"] == "platform_default"
    assert result["last_eligible_date"] == "2026-07-26"
    assert result["days_remaining"] == 25
    assert result["full_refund_needs_human_approval"] is True
    assert result["policy_ids"] == ["cw-returns", "cw-refunds"]


def test_ineligible_order_explains_closed_window(world: dict) -> None:
    # Demo order 3980: delivered 2026-05-17, 45 days before the world date.
    result = tools.check_refund_eligibility(SHOPPER_1, 3980)
    assert result["ok"] is True
    assert result["eligible"] is False
    assert "2026-06-16" in result["reason"]
    assert result["days_remaining"] < 0
    assert "cw-refunds" not in result["policy_ids"]


def test_store_override_window_and_citation(world: dict) -> None:
    conn = sqlite3.connect(world["db"])
    try:
        order_id = conn.execute(
            "SELECT id FROM orders WHERE store_id = 2 AND status = 'delivered' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    result = tools.check_refund_eligibility(MERCHANT_STORE_2, order_id)
    assert result["ok"] is True
    assert result["return_window_days"] == 14
    assert result["window_source"] == "store_override"
    assert "store-juniper-home-goods-policy" in result["policy_ids"]


def test_out_of_scope_caller_learns_nothing(world: dict) -> None:
    # Order 4127 belongs to store 1; merchant 9002 runs store 2.
    result = tools.check_refund_eligibility(MERCHANT_STORE_2, 4127)
    assert result == {
        "ok": False,
        "error": "permission_denied",
        "reason": "role 'merchant' (user 9002) may not view order #4127",
    }
    assert tools.check_refund_eligibility(SUPPORT, 4127)["ok"] is True


def test_unknown_order(world: dict) -> None:
    assert tools.check_refund_eligibility(SHOPPER_1, 999_999)["error"] == "not_found"


def test_registered_for_every_role() -> None:
    for role, role_tools in TOOLS_BY_ROLE.items():
        assert "check_refund_eligibility" in [t.name for t in role_tools], role
