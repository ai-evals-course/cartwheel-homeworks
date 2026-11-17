from __future__ import annotations

from agent import agent, tools
from agent.auth import AuthContext

SHOPPER = AuthContext(user_id=1, role="shopper")


def _browse(category: str, limit: int = 5):
    function = getattr(tools, "browse_products_by_category", None)
    assert callable(function), "browse_products_by_category is not implemented"
    return function(SHOPPER, category, limit)


def test_category_browse_returns_products_only_from_requested_category(world: dict) -> None:
    result = _browse("home_and_kitchen", limit=25)

    assert result["ok"] is True
    assert result["count"] == len(result["products"])
    assert result["count"] == 25
    assert all(product["category"] == "home_and_kitchen" for product in result["products"])
    order_keys = [
        (product["price_usd"], product["product_id"])
        for product in result["products"]
    ]
    assert order_keys == sorted(order_keys)


def test_category_browse_matches_category_case_insensitively(world: dict) -> None:
    lower = _browse("home_and_kitchen")
    upper = _browse("HOME_AND_KITCHEN")

    assert [product["product_id"] for product in lower["products"]] == [
        product["product_id"] for product in upper["products"]
    ]


def test_category_browse_rejects_empty_category(world: dict) -> None:
    result = _browse("   ")

    assert result["ok"] is False
    assert result["error"] == "invalid_argument"


def test_category_browse_rejects_unknown_category(world: dict) -> None:
    result = _browse("furniture")

    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_category_browse_clamps_limit(world: dict) -> None:
    one = _browse("home_and_kitchen", limit=0)
    many = _browse("home_and_kitchen", limit=100)

    assert one["count"] == 1
    assert many["count"] == 25


def test_category_browse_is_registered_for_every_role() -> None:
    function = getattr(agent, "browse_products_by_category", None)

    assert function is not None
    assert all(
        function in agent.TOOLS_BY_ROLE[role]
        for role in ("shopper", "merchant", "support")
    )
