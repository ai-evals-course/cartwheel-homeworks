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

from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, permission_denied
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch

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
    ### YOUR CODE HERE (HW1)
    for doc in load_policy_docs():
        if doc.policy_id == policy_id:
            return {
                "ok": True,
                "policy_id": doc.policy_id,
                "title": doc.title,
                "audience": doc.audience,
                "body": doc.body,
            }
    return {"ok": False, "error": "not_found", "reason": f"no policy doc with id {policy_id!r}"}


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
    ### YOUR CODE HERE (HW1)
    query = query.strip()
    if not query:
        return {"ok": False, "error": "invalid_argument", "reason": "query must not be empty"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": f"max_price_usd must be positive, got {max_price_usd}",
        }

    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    tokens = [tok.lower() for tok in query.split()]

    with db.connection() as conn:
        store_id = None
        if store is not None:
            found_store = db.get_store_by_name(conn, store)
            if found_store is None:
                return {"ok": False, "error": "not_found", "reason": f"no store matching {store!r}"}
            store_id = found_store.id

        candidates = db.list_products(conn, store_id)

    def matches(product: db.Product) -> bool:
        haystack = f"{product.title} {product.description}".lower()
        return all(tok in haystack for tok in tokens)

    matched = [p for p in candidates if matches(p)]
    if max_price_usd is not None:
        matched = [p for p in matched if p.price_usd <= max_price_usd]
    matched.sort(key=lambda p: (p.price_usd, p.id))
    matched = matched[:limit]

    products = [
        {
            "product_id": p.id,
            "store_id": p.store_id,
            "title": p.title,
            "price_usd": p.price_usd,
        }
        for p in matched
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
    ### YOUR CODE HERE (HW1)
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "support staff have no orders of their own; use get_order instead",
        }

    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT)
        else:
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT)

    return {
        "ok": True,
        "orders": [order.to_public_dict() for order in orders],
        "count": len(orders),
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
    ### YOUR CODE HERE (HW1)
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order with id {order_id}"}

        if not can_cancel_order(ctx, order.user_id, order.store_id):
            return permission_denied(
                f"{ctx.role} {ctx.user_id} may not cancel order {order_id}"
            )

        if order.status != "placed":
            return {
                "ok": False,
                "error": "not_eligible",
                "reason": (
                    f"order {order_id} has status {order.status!r}; "
                    "orders can be cancelled only before shipment"
                ),
            }

        db.set_order_status(conn, order_id, "cancelled")

    return {"ok": True, "order_id": order_id, "status": "cancelled"}


def find_order(ctx: AuthContext, query: str) -> dict[str, Any]:
    """Search the caller's orders by product name. Risk tier: read.

    Takes a natural-language query (e.g., "earmuffs I bought last week")
    and searches the authenticated user's orders for products whose name
    matches. Use fuzzy string matching (e.g., thefuzz.fuzz.partial_ratio
    or case-insensitive substring matching) to find orders whose product name is close to the
    query.

    Access rules: a shopper searches only the shopper's own orders, a
    merchant searches orders from the merchant's store, and support staff
    can search any orders. Use agent.db.list_order_search_candidates with
    user_id=ctx.user_id for shoppers, store_id=ctx.store_id for merchants,
    or all_orders=True only for support. Derive the scope from ctx, never
    from the query; reject unsupported roles or missing required identity.
    Use agent.db.list_products to map product IDs to product titles.

    The helper returns the complete authorised scope, newest first with
    order ID descending as the tie-breaker. Match product names first,
    preserve that order, then return at most five matches. Do not search
    only the 20 most recent orders. Convert matches with to_public_dict().

    Args:
        ctx: The caller's auth context.
        query: A natural-language description of the product.

    Returns:
        {"ok": True, "orders": [...]} with a list of matching orders
        (at most 5), each as the dict returned by agent.db. If no orders
        match, return {"ok": True, "orders": []}.
    """
    ### YOUR CODE HERE (HW1)
    from rapidfuzz import fuzz

    with db.connection() as conn:
        if ctx.role == "shopper":
            candidates = db.list_order_search_candidates(conn, user_id=ctx.user_id)
        elif ctx.role == "merchant":
            candidates = db.list_order_search_candidates(conn, store_id=ctx.store_id)
        elif ctx.role == "support":
            candidates = db.list_order_search_candidates(conn, all_orders=True)
        else:
            return {"ok": False, "error": "invalid_argument", "reason": f"unsupported role {ctx.role!r}"}

        product_titles = {p.id: p.title for p in db.list_products(conn)}

    query_lower = query.lower()
    matched = [
        order
        for order in candidates
        if fuzz.partial_ratio(query_lower, product_titles.get(order.product_id, "").lower()) >= 60
    ][:5]

    return {"ok": True, "orders": [order.to_public_dict() for order in matched]}


def get_store_info(ctx: AuthContext, store: str) -> dict[str, Any]:
    """Look up public information about a store, including its policy overrides.

    Risk tier: read. This is a homework-added tool (not part of the five
    required holes): it fills a gap noted in the HW1 handout ("look up public
    store information and policy overrides"). Every role may look it up; a
    store's category and override settings are public, like its policy docs.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        store: A store name or slug. Matched case-insensitively with
            agent.db.get_store_by_name.

    Returns:
        On success: {"ok": True, "store_id": int, "name": str, "slug": str,
        "category": str, "return_window_days_override": int | None,
        "restocking_fee_opt_in": bool}.
        {"ok": False, "error": "invalid_argument", "reason": ...} for an
        empty store string.
        {"ok": False, "error": "not_found", "reason": ...} for no match.
    """
    store = store.strip()
    if not store:
        return {"ok": False, "error": "invalid_argument", "reason": "store must not be empty"}

    with db.connection() as conn:
        found = db.get_store_by_name(conn, store)

    if found is None:
        return {"ok": False, "error": "not_found", "reason": f"no store matching {store!r}"}

    return {
        "ok": True,
        "store_id": found.id,
        "name": found.name,
        "slug": found.slug,
        "category": found.category,
        "return_window_days_override": found.return_window_days_override,
        "restocking_fee_opt_in": found.restocking_fee_opt_in,
    }
