"""Homework 1: the remaining commerce-agent tools.

The three lecture tools (`search_help_center`, `get_order`, `issue_refund`)
are implemented in agent/agent.py and are worked examples of the pattern:
check permissions first, go through agent/db.py for data, and return a
structured dict, never a prose error. The homework tools follow the same
pattern. agent/agent.py already wraps each function below as an SDK tool, so
once a function works here it works in chat with no further wiring.

Result convention (see agent/auth.py):
  - Success: a dict with "ok": True plus the payload fields named in each
    docstring.
  - Failure: {"ok": False, "error": <code>, "reason": <human-readable str>}.

Run the contract tests with: uv run pytest tests/test_hw_holes.py -k hw1
They are marked xfail and flip to passing as you implement each function.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, can_view_order, permission_denied
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch
from seed.eligibility import effective_return_window_days, is_refund_eligible

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20


def get_policy(ctx: AuthContext, policy_id: str) -> dict[str, Any]:
    """Fetch one policy doc by its exact id. Risk tier: read.

    Every role may read every policy doc (the corpus is public help-center
    content), so this tool needs no permission check.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        policy_id: An exact policy id, e.g. "cw-returns" or
            "store-juniper-home-goods-policy". Matching is exact and
            case-sensitive; ids are the `policy_id` front-matter field of the
            files in data/policies/.

    Returns:
        On success: {"ok": True, "policy_id": str, "title": str,
        "audience": str, "body": str} where body is the markdown body of the
        doc without the front matter.
        If no doc has that id: {"ok": False, "error": "not_found",
        "reason": ...} naming the id that was requested.

    Implementation notes:
        agent.helpcenter.load_policy_docs() returns every parsed doc.
    """
    for doc in load_policy_docs():
        if doc.policy_id == policy_id:
            return {
                "ok": True,
                "policy_id": doc.policy_id,
                "title": doc.title,
                "audience": doc.audience,
                "body": doc.body,
            }
    return {
        "ok": False,
        "error": "not_found",
        "reason": f"no policy doc with id '{policy_id}'",
    }


def search_products(
    ctx: AuthContext,
    query: str,
    store: str | None = None,
    max_price_usd: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search the product catalog. Risk tier: read.

    Every role may search products. Matching is deterministic keyword
    matching, not semantic search: a product matches when every whitespace
    token of `query` appears case-insensitively as a substring of the
    product's title or description.

    Args:
        ctx: The caller's auth context.
        query: Free-text query. Must be non-empty after stripping whitespace;
            otherwise return {"ok": False, "error": "invalid_argument",
            "reason": ...}.
        store: Optional store filter. Matched with
            agent.db.get_store_by_name (case-insensitive name or slug). If
            given and no store matches, return {"ok": False, "error":
            "not_found", "reason": ...} naming the store string.
        max_price_usd: Optional inclusive price ceiling. If given and not
            strictly positive, return an "invalid_argument" error.
        limit: Maximum products to return. Clamp to the range
            [1, MAX_SEARCH_LIMIT]; do not error on out-of-range values.

    Returns:
        {"ok": True, "products": [...], "count": <len(products)>} where each
        product is {"product_id": int, "store_id": int, "title": str,
        "price_usd": float}. Sort matches by price_usd ascending, then by
        product_id ascending, and truncate to `limit`. No matches is still a
        success: {"ok": True, "products": [], "count": 0}.

    Implementation notes:
        agent.db.list_products(conn, store_id) gives the candidate set.
        Use `with db.connection() as conn:` to close the database automatically.
    """
    query = query.strip()
    if not query:
        return {"ok": False, "error": "invalid_argument", "reason": "query must not be empty"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "max_price_usd must be positive",
        }
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    tokens = query.lower().split()

    with db.connection() as conn:
        store_id = None
        if store is not None:
            matched_store = db.get_store_by_name(conn, store)
            if matched_store is None:
                return {
                    "ok": False,
                    "error": "not_found",
                    "reason": f"no store matching '{store}'",
                }
            store_id = matched_store.id

        candidates = db.list_products(conn, store_id)

    matches = []
    for product in candidates:
        haystack = f"{product.title} {product.description}".lower()
        if not all(token in haystack for token in tokens):
            continue
        if max_price_usd is not None and product.price_usd > max_price_usd:
            continue
        matches.append(product)

    matches.sort(key=lambda p: (p.price_usd, p.id))
    products = [
        {
            "product_id": p.id,
            "store_id": p.store_id,
            "title": p.title,
            "price_usd": p.price_usd,
        }
        for p in matches[:limit]
    ]
    return {"ok": True, "products": products, "count": len(products)}


def list_my_orders(ctx: AuthContext) -> dict[str, Any]:
    """List recent orders in the caller's own scope. Risk tier: read.

    Role behavior, straight from the access matrix in SPEC.md:
        - shopper: the caller's own orders.
        - merchant: the caller's store's orders (ctx.store_id).
        - support: support staff have no orders of their own and look up
          specific orders with get_order instead, so return {"ok": False,
          "error": "invalid_argument", "reason": ...} saying exactly that.

    Returns:
        For shopper and merchant: {"ok": True, "orders": [...],
        "count": <len(orders)>} where each order is
        agent.db.Order.to_public_dict() and the list holds at most
        DEFAULT_ORDER_LIMIT orders, newest first (agent.db.list_orders_for_user
        and list_orders_for_store already sort and limit this way).

    Implementation notes:
        No permission check is needed beyond the role dispatch, because the
        scope is baked into which query you run. That is the point of the
        tool: the model cannot ask for someone else's orders through it.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "support staff have no orders of their own; use get_order instead",
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT)
        else:  # merchant
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT)

    payload = [order.to_public_dict() for order in orders]
    return {"ok": True, "orders": payload, "count": len(payload)}


def cancel_order(ctx: AuthContext, order_id: int, reason: str) -> dict[str, Any]:
    """Cancel an order. Risk tier: write.

    This is the homework's write tool, and it must enforce two independent
    rules in this order:

    1. The access matrix (scope): use agent.auth.can_cancel_order. Shoppers
       may cancel only their own orders, merchants only their own store's
       orders, support any order. On failure return
       agent.auth.permission_denied(...) with a reason naming the role and
       the order id. Scope is checked before the status rule so that an
       out-of-scope caller learns nothing about the order's state.
    2. The pre-shipment rule (facts.yaml `cancel_cutoff`): only orders whose
       status is exactly "placed" can be cancelled, for every role. If the
       order is in scope but its status is not "placed", return
       {"ok": False, "error": "not_eligible", "reason": ...} that names the
       current status and states that orders can be cancelled only before
       shipment.

    Args:
        ctx: The caller's auth context.
        order_id: The order to cancel.
        reason: Free-text reason from the user; not validated.

    Returns:
        If no order has this id: {"ok": False, "error": "not_found",
        "reason": ...}.
        On success: {"ok": True, "order_id": order_id, "status": "cancelled"}
        after persisting the new status with agent.db.set_order_status.

    Implementation notes:
        Fetch with agent.db.get_order. Note the argument order of
        can_cancel_order(ctx, order_user_id, order_store_id).

    The Module 4 kill switch is checked first (before the scope and
    status rules and before your code), so that a paused write tool touches
    nothing. It is provided; the default ("off") returns None and falls
    through to your implementation.
    """
    paused = kill_switch("cancel_order")
    if paused is not None:
        return {"ok": False, "error": "paused", "reason": paused}
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        if not can_cancel_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"role '{ctx.role}' (user {ctx.user_id}) may not cancel order #{order_id}"
            )
        if order.status != "placed":
            return {
                "ok": False,
                "error": "not_eligible",
                "reason": (
                    f"order #{order_id} has status '{order.status}'; "
                    f"orders can only be cancelled before shipment"
                ),
            }
        db.set_order_status(conn, order_id, "cancelled")
        return {"ok": True, "order_id": order_id, "status": "cancelled"}


def find_order(ctx: AuthContext, query: str) -> dict[str, Any]:
    """Search the caller's orders by product name. Risk tier: read.

    Takes a natural-language query (e.g., "earmuffs I bought last week")
    and searches the authenticated user's orders for products whose name
    matches. Use fuzzy string matching (e.g., thefuzz.fuzz.partial_ratio
    or SQLite LIKE) to find orders whose product name is close to the
    query.

    Access rules: a shopper searches only the shopper's own orders, a
    merchant searches orders from the merchant's store, and support staff
    can search any orders. Use agent.db.list_orders_for_user for shoppers
    and agent.db.list_orders_for_store for merchants. For support staff,
    use agent.db.list_orders_for_user with no user filter, or search
    across all orders.

    Args:
        ctx: The caller's auth context.
        query: A natural-language description of the product.

    Returns:
        {"ok": True, "orders": [...]} with a list of matching orders
        (at most 5), each as the dict returned by agent.db. If no orders
        match, return {"ok": True, "orders": []}.
    """
    from rapidfuzz import fuzz, process

    query = query.strip()
    if not query:
        return {"ok": True, "orders": []}

    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=10_000)
        elif ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=10_000)
        else:  # support: search across every order
            rows = conn.execute("SELECT id FROM orders").fetchall()
            orders = [db.get_order(conn, row["id"]) for row in rows]
        titles = {p.id: p.title for p in db.list_products(conn)}

    choices = {order.id: titles.get(order.product_id, "") for order in orders}
    matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=5, score_cutoff=60)
    matched_ids = {order_id for _title, _score, order_id in matches}
    result_orders = [o.to_public_dict() for o in orders if o.id in matched_ids]
    return {"ok": True, "orders": result_orders}


# ---------------------------------------------------------------------------
# Our own tools (Part A: "fill the gaps you notice during Part B").
# ---------------------------------------------------------------------------


def check_return_eligibility(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Explain whether an order is currently eligible for a return or refund.

    Risk tier: read. Reports the same `refund_eligible` decision that
    `get_order` and `issue_refund` rely on (seed.eligibility.is_refund_eligible),
    plus a plain-language reason and the days remaining in the return window.
    This exists because during manual testing, a shopper who was told "not
    refund eligible" had no way to ask *why* without escalating to a human.

    Access follows the same scope as `get_order`: shoppers see only their own
    orders, merchants only their own store's orders, support any order.

    Args:
        ctx: The caller's auth context.
        order_id: The order to check.

    Returns:
        On success: {"ok": True, "order_id": int, "status": str,
        "eligible": bool, "return_window_days": int,
        "days_since_delivery": int | None, "days_remaining": int | None,
        "reason": str}. `return_window_days` already reflects any store
        override (facts.yaml `store_overrides.precedence`).
        If no order has this id: {"ok": False, "error": "not_found", ...}.
        If the order is outside the caller's scope:
        agent.auth.permission_denied(...).
    """
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        if not can_view_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"role '{ctx.role}' (user {ctx.user_id}) may not view order #{order_id}"
            )
        store = db.get_store(conn, order.store_id)
        as_of = db.world_asof(conn)

    facts = load_facts()
    window_days = effective_return_window_days(
        facts["return_window_days"],
        store.return_window_days_override if store else None,
    )
    eligible = is_refund_eligible(
        status=order.status,
        delivered_at=order.delivered_at,
        as_of=as_of,
        return_window_days=window_days,
    )

    days_since_delivery = (as_of - order.delivered_at).days if order.delivered_at else None
    if order.status in ("cancelled", "refunded"):
        reason = f"order was {order.status} and was never delivered"
    elif order.status != "delivered":
        reason = f"order status is '{order.status}', not yet delivered"
    elif days_since_delivery is not None and days_since_delivery > window_days:
        reason = (
            f"delivered {days_since_delivery} days ago, past the "
            f"{window_days}-day return window"
        )
    else:
        reason = (
            f"delivered {days_since_delivery} days ago, within the "
            f"{window_days}-day return window"
        )

    return {
        "ok": True,
        "order_id": order_id,
        "status": order.status,
        "eligible": eligible,
        "return_window_days": window_days,
        "days_since_delivery": days_since_delivery,
        "days_remaining": (
            window_days - days_since_delivery if days_since_delivery is not None else None
        ),
        "reason": reason,
    }


def track_shipment(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Report shipment stage and dates for one order.

    Risk tier: read. Cartwheel has no live carrier tracking, so this reports
    the recorded ordered/shipped/delivered dates and, for an order that
    hasn't shipped or delivered yet, an estimated delivery date from the
    platform's handling and transit windows (facts.yaml
    `shipping_handling_days_max` and `shipping_transit_days_max`). This fills
    a gap noticed in Part B: shoppers ask "where is my order" long before
    they ask about refunds, and no existing tool answers that directly.

    Access follows the same scope as `get_order`.

    Args:
        ctx: The caller's auth context.
        order_id: The order to check.

    Returns:
        On success: {"ok": True, "order_id": int, "status": str,
        "ordered_at": str, "shipped_at": str | None,
        "delivered_at": str | None, "estimated_delivery_by": str | None}.
        The estimate is present only while the order has not yet shipped
        or been delivered.
        If no order has this id: {"ok": False, "error": "not_found", ...}.
        If the order is outside the caller's scope:
        agent.auth.permission_denied(...).
    """
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        if not can_view_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"role '{ctx.role}' (user {ctx.user_id}) may not view order #{order_id}"
            )

    estimated_delivery_by = None
    if order.status in ("placed", "shipped"):
        facts = load_facts()
        max_days = facts["shipping_handling_days_max"] + facts["shipping_transit_days_max"]
        estimated_delivery_by = (order.ordered_at + timedelta(days=max_days)).isoformat()

    return {
        "ok": True,
        "order_id": order_id,
        "status": order.status,
        "ordered_at": order.ordered_at.isoformat(),
        "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "estimated_delivery_by": estimated_delivery_by,
    }


def summarize_order_history(ctx: AuthContext) -> dict[str, Any]:
    """Summarize the caller's own recent order history.

    Risk tier: read. Same scope as `list_my_orders`: a shopper's own orders,
    or a merchant's store's orders, over the most recent `DEFAULT_ORDER_LIMIT`
    records. Support staff have no orders of their own, so this returns the
    same `invalid_argument` error `list_my_orders` does. Added because a
    shopper asking "how much have I spent with this store" otherwise forces
    the model to sum up a raw order list by hand.

    Returns:
        On success: {"ok": True, "count": int, "total_spent_usd": float,
        "by_status": {status: count}}.
        For a support caller: {"ok": False, "error": "invalid_argument", ...}.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "support staff have no orders of their own; use get_order instead",
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT)
        else:  # merchant
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT)

    by_status: dict[str, int] = {}
    total_cents = 0
    for order in orders:
        by_status[order.status] = by_status.get(order.status, 0) + 1
        total_cents += order.total_cents

    return {
        "ok": True,
        "count": len(orders),
        "total_spent_usd": round(total_cents / 100, 2),
        "by_status": by_status,
    }
