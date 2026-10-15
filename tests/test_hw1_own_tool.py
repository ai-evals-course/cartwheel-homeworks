"""Homework 1, Part A: my own tool, check_return_eligibility (no LLM, no API keys)."""

from __future__ import annotations

import pytest

from agent import db
from agent.agent import TOOLS_BY_ROLE
from agent.auth import AuthContext
from agent.tools import check_return_eligibility

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
SHOPPER_2 = AuthContext(user_id=2, role="shopper")
SHOPPER_333 = AuthContext(user_id=333, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_within_platform_window_gives_last_return_day(world: dict) -> None:
    result = check_return_eligibility(SHOPPER_1, 4127)
    assert result["ok"] is True
    assert result["eligible"] is True
    assert result["reason"] == "within_window"
    assert result["return_window_days"] == 30
    assert result["window_source"] == "platform_default"
    assert result["delivered_at"] == "2026-06-19"
    assert result["last_return_day"] == "2026-07-19"
    assert result["as_of"] == "2026-07-01"
    assert result["data_issues"] == []
    assert result["refund_needs_human_approval"] is False
    assert result["policy_ids"] == ["cw-returns"]


def test_refund_above_threshold_is_flagged_for_approval(world: dict) -> None:
    assert check_return_eligibility(SHOPPER_1, 4455)["refund_needs_human_approval"] is True


def test_store_override_closes_window_the_platform_would_allow(world: dict) -> None:
    # Delivered 2026-06-06: day 25 is inside 30 days but outside Juniper's 14.
    result = check_return_eligibility(SHOPPER_333, 569)
    assert result["eligible"] is False
    assert result["reason"] == "window_passed"
    assert result["return_window_days"] == 14
    assert result["window_source"] == "store_override"
    assert result["last_return_day"] == "2026-06-20"
    assert result["refund_needs_human_approval"] is None
    assert result["policy_ids"] == [
        "cw-returns",
        "cw-store-overrides",
        "store-juniper-home-goods-policy",
    ]


def test_restocking_store_is_flagged(world: dict) -> None:
    result = check_return_eligibility(SUPPORT, 120)  # Cascade Audio
    assert result["restocking_fee_may_apply"] is True
    assert result["window_source"] == "platform_default"
    assert "cw-restocking-fees" in result["policy_ids"]
    assert "store-cascade-audio-policy" in result["policy_ids"]


@pytest.mark.parametrize(
    "order_id, issue",
    [
        (8002, "marked delivered but has no delivery date"),
        (8001, "the order, ship, and delivery dates are out of order"),
        (8003, "the product is not listed by the order's store"),
    ],
)
def test_inconsistent_record_gives_no_deadline(world: dict, order_id: int, issue: str) -> None:
    result = check_return_eligibility(SUPPORT, order_id)
    assert result["ok"] is True
    assert result["eligible"] is None
    assert result["reason"] == "inconsistent_record"
    assert result["last_return_day"] is None
    assert issue in result["data_issues"]
    assert "escalate" in result["note"]


@pytest.mark.parametrize(
    "order_id, reason",
    [(3988, "already_refunded"), (9161, "cancelled"), (10, "not_delivered_yet")],
)
def test_undelivered_or_closed_orders_are_not_eligible(
    world: dict, order_id: int, reason: str
) -> None:
    result = check_return_eligibility(SUPPORT, order_id)
    assert result["eligible"] is False
    assert result["reason"] == reason
    assert result["last_return_day"] is None


def test_scope_matches_get_order(world: dict) -> None:
    assert check_return_eligibility(SHOPPER_2, 4127)["error"] == "permission_denied"
    assert check_return_eligibility(MERCHANT_STORE_2, 4127)["error"] == "permission_denied"
    assert check_return_eligibility(MERCHANT_STORE_2, 569)["ok"] is True
    assert check_return_eligibility(SUPPORT, 999_999)["error"] == "not_found"


def test_agrees_with_stamped_flag_on_consistent_records(world: dict) -> None:
    with db.connection() as conn:
        rows = conn.execute("SELECT id FROM orders WHERE id % 50 = 0 OR id IN (4127, 4455, 569)")
        orders = [db.get_order(conn, row["id"]) for row in rows.fetchall()]
    checked = 0
    for order in orders:
        result = check_return_eligibility(SUPPORT, order.id)
        if result["reason"] != "inconsistent_record":
            assert result["eligible"] is order.refund_eligible, order.id
            checked += 1
    assert checked > 100


def test_registered_for_every_role() -> None:
    for role, tools in TOOLS_BY_ROLE.items():
        assert "check_return_eligibility" in {tool.name for tool in tools}, role
