"""Tests for the student-defined Homework 1 tool, get_store_info.

Offline: no LLM and no API keys. Expected numbers come from facts.yaml and the
seeded stores table, never from literals that could drift from policy.
"""

from __future__ import annotations

import pytest

from agent import db, tools
from agent.agent import TOOLS_BY_ROLE
from agent.auth import AuthContext
from agent.config import load_facts

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_store_with_override_reports_store_window_and_policy(world: dict) -> None:
    with db.connection() as conn:
        juniper = db.get_store(conn, 2)
    assert juniper.return_window_days_override is not None  # seeded override

    result = tools.get_store_info(SHOPPER_1, store_id=2)
    assert result["ok"] is True
    store = result["store"]
    assert store["name"] == juniper.name
    assert store["return_window_days"] == juniper.return_window_days_override
    assert store["has_return_window_override"] is True
    assert store["platform_return_window_days"] == load_facts()["return_window_days"]
    assert store["store_policy_id"] == "store-juniper-home-goods-policy"
    assert store["return_window_policy_id"] == "store-juniper-home-goods-policy"
    # the cited doc really exists
    assert tools.get_policy(SHOPPER_1, store["return_window_policy_id"])["ok"] is True


def test_store_without_override_falls_back_to_platform_default(world: dict) -> None:
    store = tools.get_store_info(SHOPPER_1, store_id=1)["store"]
    assert store["has_return_window_override"] is False
    assert store["return_window_days"] == load_facts()["return_window_days"]
    assert store["store_policy_id"] is None
    assert store["return_window_policy_id"] == "cw-returns"
    assert store["restocking_fee_opt_in"] is False
    assert store["restocking_fee_max_percent"] is None


def test_restocking_fee_store_reports_the_facts_cap(world: dict) -> None:
    store = tools.get_store_info(SHOPPER_1, store_name="Cascade Audio")["store"]
    assert store["restocking_fee_opt_in"] is True
    assert store["restocking_fee_max_percent"] == load_facts()["restocking_fee_max_percent"]
    assert store["has_return_window_override"] is False
    assert store["return_window_policy_id"] == "cw-returns"
    assert store["store_policy_id"] == "store-cascade-audio-policy"


def test_lookup_by_name_is_case_insensitive_and_matches_lookup_by_id(world: dict) -> None:
    by_name = tools.get_store_info(SHOPPER_1, store_name="  juniper home goods ")
    by_slug = tools.get_store_info(SHOPPER_1, store_name="juniper-home-goods")
    by_id = tools.get_store_info(SHOPPER_1, store_id=2)
    assert by_name == by_slug == by_id


@pytest.mark.parametrize("ctx", [SHOPPER_1, MERCHANT_STORE_2, SUPPORT], ids=lambda c: c.role)
def test_every_role_gets_the_same_public_answer(world: dict, ctx: AuthContext) -> None:
    assert tools.get_store_info(ctx, store_id=7) == tools.get_store_info(SHOPPER_1, store_id=7)


def test_result_exposes_no_private_data(world: dict) -> None:
    store = tools.get_store_info(MERCHANT_STORE_2, store_id=1)["store"]
    assert set(store) == {
        "store_id", "name", "category", "return_window_days", "has_return_window_override",
        "platform_return_window_days", "restocking_fee_opt_in", "restocking_fee_max_percent",
        "store_policy_id", "return_window_policy_id",
    }


def test_argument_and_lookup_errors(world: dict) -> None:
    assert tools.get_store_info(SHOPPER_1)["error"] == "invalid_argument"
    assert tools.get_store_info(SHOPPER_1, store_id=2, store_name="Juniper Home Goods")["error"] == "invalid_argument"
    assert tools.get_store_info(SHOPPER_1, store_name="   ")["error"] == "invalid_argument"

    missing_id = tools.get_store_info(SHOPPER_1, store_id=999_999)
    assert missing_id["ok"] is False and missing_id["error"] == "not_found"
    assert "999999" in missing_id["reason"]
    missing_name = tools.get_store_info(SHOPPER_1, store_name="No Such Store")
    assert missing_name["error"] == "not_found" and "No Such Store" in missing_name["reason"]


def test_tool_is_registered_for_every_role() -> None:
    for role, role_tools in TOOLS_BY_ROLE.items():
        assert "get_store_info" in [t.name for t in role_tools], role
