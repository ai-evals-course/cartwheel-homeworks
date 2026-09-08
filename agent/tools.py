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

import sqlite3
from datetime import timedelta
from typing import Any

from rapidfuzz import fuzz

from agent import db
from agent.auth import (
    AuthContext,
    can_cancel_order,
    can_view_order,
    permission_denied,
)
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch
from seed.eligibility import effective_return_window_days, is_refund_eligible

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20

# SQLite reads a negative LIMIT as "no limit", so the supplied list helpers in
# agent/db.py can return a full result set without a second query or a new
# helper. Used to count orders in scope before truncating to the limit above.
NO_LIMIT = -1

# find_order tuning. WRatio scores a natural-language query against a product
# title; MATCH_THRESHOLD is the cutoff below which a query counts as no match.
# Measured against the seeded catalog: real product queries score 73 and up,
# while a query for something the caller does not own tops out around 50.
MATCH_THRESHOLD = 70
MAX_FIND_RESULTS = 5


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
        return {"ok": False, "error": "invalid_argument", "reason": "empty query"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": f"max_price_usd must be positive, got {max_price_usd}",
        }
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    tokens = query.lower().split()
    max_price_cents = None if max_price_usd is None else round(max_price_usd * 100)

    with db.connection() as conn:
        store_id = None
        if store is not None:
            matched = db.get_store_by_name(conn, store)
            if matched is None:
                return {
                    "ok": False,
                    "error": "not_found",
                    "reason": f"no store named '{store}'",
                }
            store_id = matched.id
        matches = [
            product
            for product in db.list_products(conn, store_id)
            if all(
                token in f"{product.title} {product.description}".lower()
                for token in tokens
            )
            and (max_price_cents is None or product.price_cents <= max_price_cents)
        ]

    matches.sort(key=lambda p: (p.price_cents, p.id))
    products = [
        {
            "product_id": product.id,
            "store_id": product.store_id,
            "title": product.title,
            "price_usd": product.price_usd,
        }
        for product in matches[:limit]
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

        The result also carries "total_count", the number of orders in scope
        before truncation, and "truncated", True when total_count exceeds
        count. These extend the HW1 contract: "count" alone reads as the whole
        set, so a caller holding more than DEFAULT_ORDER_LIMIT orders would
        otherwise be told it has exactly DEFAULT_ORDER_LIMIT.

    Implementation notes:
        No permission check is needed beyond the role dispatch, because the
        scope is baked into which query you run. That is the point of the
        tool: the model cannot ask for someone else's orders through it.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                "support staff have no orders of their own; "
                "look up a specific order with get_order"
            ),
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=NO_LIMIT)
        else:  # merchant; AuthContext guarantees store_id is set
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=NO_LIMIT)

    total_count = len(orders)
    payload = [order.to_public_dict() for order in orders[:DEFAULT_ORDER_LIMIT]]
    return {
        "ok": True,
        "orders": payload,
        "count": len(payload),
        "total_count": total_count,
        "truncated": total_count > len(payload),
    }


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
            return {
                "ok": False,
                "error": "not_found",
                "reason": f"no order #{order_id}",
            }
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
                    f"orders can be cancelled only before shipment"
                ),
            }
        db.set_order_status(conn, order_id, "cancelled")
        return {"ok": True, "order_id": order_id, "status": "cancelled"}


def _orders_in_scope(conn: sqlite3.Connection, ctx: AuthContext) -> list[db.Order]:
    """Every order the caller may search, newest first."""
    if ctx.role == "shopper":
        return db.list_orders_for_user(conn, ctx.user_id, limit=NO_LIMIT)
    if ctx.role == "merchant":
        return db.list_orders_for_store(conn, ctx.store_id, limit=NO_LIMIT)
    return db.list_all_orders(conn, limit=NO_LIMIT)  # support: any order


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
    use agent.db.list_all_orders: list_orders_for_user requires a user id
    and so cannot express an unfiltered search.

    Matching scores the query against the ordered product's title with
    rapidfuzz.fuzz.WRatio and keeps scores at or above MATCH_THRESHOLD.
    A cutoff is required: without one, the highest-scoring five orders
    always come back, and a query matching nothing would still return
    results.

    Args:
        ctx: The caller's auth context.
        query: A natural-language description of the product.

    Returns:
        {"ok": True, "orders": [...]} with a list of matching orders
        (at most 5), each as the dict returned by agent.db. If no orders
        match, return {"ok": True, "orders": []}.
    """
    needle = query.strip().lower()
    if not needle:
        return {"ok": True, "orders": []}
    with db.connection() as conn:
        titles = {product.id: product.title for product in db.list_products(conn)}
        scored = [
            (fuzz.WRatio(needle, titles.get(order.product_id, "").lower()), order)
            for order in _orders_in_scope(conn, ctx)
        ]
    matches = [(score, order) for score, order in scored if score >= MATCH_THRESHOLD]
    matches.sort(key=lambda pair: -pair[0])  # stable: ties stay newest-first
    return {
        "ok": True,
        "orders": [order.to_public_dict() for _, order in matches[:MAX_FIND_RESULTS]],
    }


# ---------------------------------------------------------------------------
# Additional tools (Homework 1, Part A). Both were added after Part B
# conversations showed the agent could not answer a reasonable question with
# the tools it had. Each is registered in TOOLS_BY_ROLE in agent/agent.py.
# ---------------------------------------------------------------------------


def get_product(ctx: AuthContext, product_id: int) -> dict[str, Any]:
    """Fetch one product by its id. Risk tier: read.

    The catalog is public, so every role may read any product and this tool
    needs no permission check, exactly like search_products.

    Pairs with get_order, which returns a product_id but not the product's
    name: without this tool the agent cannot answer "what was the item I
    ordered?" for an order it can otherwise see.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        product_id: The product to look up.

    Returns:
        On success: {"ok": True, "product": {"product_id": int,
        "store_id": int, "store_name": str | None, "title": str,
        "description": str, "category": str, "price_usd": float}}.
        If no product has this id: {"ok": False, "error": "not_found",
        "reason": ...}.

    Note that price_usd is the current listing price, which is not
    necessarily what an older order paid; compare with the order's total_usd
    rather than assuming they agree.
    """
    with db.connection() as conn:
        product = db.get_product(conn, product_id)
        if product is None:
            return {
                "ok": False,
                "error": "not_found",
                "reason": f"no product #{product_id}",
            }
        store = db.get_store(conn, product.store_id)
        return {
            "ok": True,
            "product": {
                "product_id": product.id,
                "store_id": product.store_id,
                "store_name": store.name if store else None,
                "title": product.title,
                "description": product.description,
                "category": product.category,
                "price_usd": product.price_usd,
            },
        }


def check_return_eligibility(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Explain whether an order can still be returned, and why. Risk tier: read.

    Scoped by the access matrix through agent.auth.can_view_order, on the same
    terms as get_order: shoppers see their own orders, merchants their store's,
    support any.

    The eligibility decision reuses the oracle in seed/eligibility.py, the same
    pure functions the seed script uses to stamp refund_eligible on every
    order, so this tool cannot drift from the flag issue_refund honors.

    Args:
        ctx: The caller's auth context.
        order_id: The order to check.

    Returns:
        On success, {"ok": True, ...} with the fields below. If no order has
        this id: {"ok": False, "error": "not_found", ...}. If the order is
        outside the caller's scope: agent.auth.permission_denied(...).

        - status, delivered_at: the order's own values.
        - as_of: the world's current date (agent.db.world_asof), which is what
          every date calculation here counts against. It is not today's real
          date; do not substitute one.
        - days_since_delivery: negative if the delivery date is in the future.
        - return_window_days, window_source, policy_id: the window that
          applies, whether it came from the store override or the platform
          default, and the policy id to cite for it (RESP-1).
        - return_deadline: the last day a return may be started.
        - refund_eligible: the flag stored on the order. This is the
          authoritative answer, because issue_refund honors this flag.
        - computed_eligible, consistent: the recomputation from the oracle and
          whether it agrees with the stored flag. The seed plants at least one
          order whose stored flag disagrees with its own dates, so a False
          here means the record is internally inconsistent and the caller
          should say so rather than pick a side (RESP-3).

    This tool answers the return window only. It does not account for
    restocking fees, which some stores charge on opened items, nor for the
    refund auto-approval threshold, which issue_refund applies separately.
    """
    facts = load_facts()
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {
                "ok": False,
                "error": "not_found",
                "reason": f"no order #{order_id}",
            }
        if not can_view_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"role '{ctx.role}' (user {ctx.user_id}) may not view order #{order_id}"
            )
        store = db.get_store(conn, order.store_id)
        as_of = db.world_asof(conn)

    override = store.return_window_days_override if store else None
    window = effective_return_window_days(facts["return_window_days"], override)
    computed = is_refund_eligible(
        status=order.status,
        delivered_at=order.delivered_at,
        as_of=as_of,
        return_window_days=window,
    )

    # An override is valid only if the store's own policy page states it
    # (cw-store-overrides), so cite that page when one applies. Fall back to
    # the platform policy if the store has no doc under the usual id.
    policy_id = "cw-returns"
    if override is not None and store is not None:
        candidate = f"store-{store.slug}-policy"
        if any(doc.policy_id == candidate for doc in load_policy_docs()):
            policy_id = candidate

    return {
        "ok": True,
        "order_id": order_id,
        "status": order.status,
        "as_of": as_of.isoformat(),
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "days_since_delivery": (
            (as_of - order.delivered_at).days if order.delivered_at else None
        ),
        "return_window_days": window,
        "window_source": "store_override" if override is not None else "platform_default",
        "policy_id": policy_id,
        "return_deadline": (
            (order.delivered_at + timedelta(days=window)).isoformat()
            if order.delivered_at
            else None
        ),
        "refund_eligible": order.refund_eligible,
        "computed_eligible": computed,
        "consistent": computed == order.refund_eligible,
    }
