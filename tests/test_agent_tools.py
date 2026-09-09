"""The three instructor-provided lecture tools, tested through their logic
functions (no LLM, no API keys)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agent.agent import (
    get_order_logic,
    issue_refund_logic,
    search_help_center_logic,
)
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
SHOPPER_2 = AuthContext(user_id=2, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_search_help_center_finds_the_return_policy(world: dict) -> None:
    result = search_help_center_logic(SHOPPER_1, "return policy window days")
    assert result["ok"] is True
    top_ids = [r["policy_id"] for r in result["results"]]
    assert "cw-returns" in top_ids


def test_search_help_center_rejects_empty_query(world: dict) -> None:
    result = search_help_center_logic(SHOPPER_1, "   ")
    assert result == {"ok": False, "error": "invalid_argument", "reason": "empty query"}


def test_get_order_happy_path(world: dict) -> None:
    result = get_order_logic(SHOPPER_1, 4127)
    assert result["ok"] is True
    assert result["order"]["total_usd"] == 84.0
    assert result["order"]["refund_eligible"] is True
    assert result["order"]["store_name"] == "Blue Heron Ceramics"


def test_get_order_denies_other_shopper(world: dict) -> None:
    result = get_order_logic(SHOPPER_2, 4127)
    assert result["ok"] is False
    assert result["error"] == "permission_denied"


def test_get_order_denies_other_merchant_allows_support(world: dict) -> None:
    assert get_order_logic(MERCHANT_STORE_2, 4127)["error"] == "permission_denied"
    assert get_order_logic(SUPPORT, 4127)["ok"] is True


def test_refund_below_threshold_auto_approves(world_copy: Path) -> None:
    result = issue_refund_logic(SHOPPER_1, 4127, 84.0, "arrived chipped")
    assert result["ok"] is True
    assert result["status"] == "auto_approved"
    conn = sqlite3.connect(world_copy)
    try:
        status = conn.execute("SELECT status FROM orders WHERE id = 4127").fetchone()[0]
        refund = conn.execute(
            "SELECT status, amount_cents FROM refunds WHERE order_id = 4127"
        ).fetchone()
    finally:
        conn.close()
    assert status == "refunded"
    assert refund == ("auto_approved", 8400)


def test_refund_above_threshold_queues(world_copy: Path) -> None:
    result = issue_refund_logic(SHOPPER_1, 4455, 240.0, "wrong item")
    assert result["ok"] is True
    assert result["status"] == "queued_for_approval"
    conn = sqlite3.connect(world_copy)
    try:
        # Queued means no money moved: the order is untouched.
        status = conn.execute("SELECT status FROM orders WHERE id = 4455").fetchone()[0]
        refund = conn.execute(
            "SELECT status FROM refunds WHERE order_id = 4455"
        ).fetchone()
    finally:
        conn.close()
    assert status == "delivered"
    assert refund == ("queued_for_approval",)


def test_refund_outside_window_is_denied(world_copy: Path) -> None:
    result = issue_refund_logic(SHOPPER_1, 3980, 52.0, "changed my mind")
    assert result["ok"] is False
    assert result["error"] == "not_eligible"


def test_refund_respects_scope(world_copy: Path) -> None:
    result = issue_refund_logic(SHOPPER_2, 4127, 84.0, "not my order")
    assert result["ok"] is False
    assert result["error"] == "permission_denied"


def test_get_store_info_reports_override_and_default(world: dict) -> None:
    from agent.tools import get_store_info

    juniper = get_store_info(SHOPPER_1, "Juniper Home Goods")
    assert juniper["ok"] is True
    assert juniper["effective_return_window_days"] == 14
    assert juniper["return_window_days_override"] == 14
    assert juniper["platform_return_window_days"] == 30

    heron = get_store_info(SHOPPER_1, "blue-heron-ceramics")
    assert heron["ok"] is True
    assert heron["return_window_days_override"] is None
    assert heron["effective_return_window_days"] == 30

    assert get_store_info(SHOPPER_1, "")["error"] == "invalid_argument"
    assert get_store_info(SHOPPER_1, "No Such Store")["error"] == "not_found"
