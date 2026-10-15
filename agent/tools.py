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

import re
from datetime import date, timedelta
from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, can_view_order, permission_denied
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch
from seed.eligibility import (
    effective_return_window_days,
    is_refund_eligible,
    refund_needs_approval,
)

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20
FIND_ORDER_LIMIT = 5
STATUS_REASONS = {
    "placed": "not_delivered_yet",
    "shipped": "not_delivered_yet",
    "refunded": "already_refunded",
    "cancelled": "cancelled",
}


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
        "reason": (
            f"no policy doc with id {policy_id!r}; ids are exact and "
            f"case-sensitive, so use search_help_center to find the right id"
        ),
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
    tokens = query.lower().split()
    if not tokens:
        return {"ok": False, "error": "invalid_argument", "reason": "query must not be empty"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": f"max_price_usd must be positive, got {max_price_usd}",
        }
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))

    with db.connection() as conn:
        store_id = None
        if store is not None:
            found = db.get_store_by_name(conn, store)
            if found is None:
                return {"ok": False, "error": "not_found", "reason": f"no store named {store!r}"}
            store_id = found.id
        candidates = db.list_products(conn, store_id)

    matches = [
        p
        for p in candidates
        if all(t in p.title.lower() or t in p.description.lower() for t in tokens)
        and (max_price_usd is None or p.price_usd <= max_price_usd)
    ]
    matches.sort(key=lambda p: (p.price_usd, p.id))
    products = [
        {"product_id": p.id, "store_id": p.store_id, "title": p.title, "price_usd": p.price_usd}
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
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)
        elif ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)
        else:
            return {
                "ok": False,
                "error": "invalid_argument",
                "reason": (
                    "support staff have no orders of their own; "
                    "look up a specific order with get_order instead"
                ),
            }
    public = [order.to_public_dict() for order in orders]
    return {"ok": True, "orders": public, "count": len(public)}


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
                    f"orders can be cancelled only before shipment"
                ),
            }
        db.set_order_status(conn, order_id, "cancelled")
    return {"ok": True, "order_id": order_id, "status": "cancelled"}


def _normalize(text: str) -> str:
    """Lowercase and turn punctuation into spaces, so "Heavy-Duty" matches "heavy duty"."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _title_matches(query_words: list[str], title: str) -> bool:
    """Every query word appears in the title; a trailing plural "s" is optional."""
    title = _normalize(title)
    return all(
        word in title or (len(word) > 3 and word.endswith("s") and word[:-1] in title)
        for word in query_words
    )


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
    if ctx.role == "shopper" and ctx.user_id is not None:
        scope: dict[str, Any] = {"user_id": ctx.user_id}
    elif ctx.role == "merchant" and ctx.store_id is not None:
        scope = {"store_id": ctx.store_id}
    elif ctx.role == "support":
        scope = {"all_orders": True}
    else:
        return permission_denied(
            f"role '{ctx.role}' (user {ctx.user_id}) has no order search scope"
        )

    query_words = _normalize(query).split()
    if not query_words:
        return {"ok": True, "orders": []}

    with db.connection() as conn:
        candidates = db.list_order_search_candidates(conn, **scope)
        titles = {product.id: product.title for product in db.list_products(conn)}

    matches = [
        order
        for order in candidates
        if _title_matches(query_words, titles.get(order.product_id, ""))
    ]
    return {"ok": True, "orders": [order.to_public_dict() for order in matches[:FIND_ORDER_LIMIT]]}


# ---------------------------------------------------------------------------
# My own tool (Part A). Part B showed the gap: get_order exposes only the
# stamped refund_eligible flag, so the model supplied the reason itself. It
# read `false` as "the window has closed" for an order with no delivery date
# (B15) and answered window questions without the window or the deadline
# (B2, B5, B8).
# ---------------------------------------------------------------------------


def _record_issues(order: db.Order, store_product_ids: set[int], as_of: date) -> list[str]:
    """Contradictions in a delivered order's record that make its deadline unknowable."""
    issues = []
    if order.delivered_at is None:
        issues.append("marked delivered but has no delivery date")
    elif order.delivered_at > as_of:
        issues.append("the delivery date is in the future")
    dates = [d for d in (order.ordered_at, order.shipped_at, order.delivered_at) if d]
    if dates != sorted(dates):
        issues.append("the order, ship, and delivery dates are out of order")
    if order.product_id not in store_product_ids:
        issues.append("the product is not listed by the order's store")
    return issues


def check_return_eligibility(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Explain whether an order can be returned, and until when. Risk tier: read.

    Same scope as get_order (agent.auth.can_view_order). The decision reuses
    seed.eligibility, the oracle that stamped `refund_eligible`, so the two
    agree on every consistent record.

    Returns:
        If no order has this id: {"ok": False, "error": "not_found", ...}.
        Out of scope: agent.auth.permission_denied(...).
        Otherwise {"ok": True, "order_id", "status", "store_name",
        "eligible", "reason", "return_window_days", "window_source",
        "delivered_at", "last_return_day", "as_of", "data_issues",
        "refund_needs_human_approval", "restocking_fee_may_apply",
        "policy_ids"}. `reason` is one of "within_window", "window_passed",
        "not_delivered_yet", "already_refunded", "cancelled", or
        "inconsistent_record". For an inconsistent record, `eligible` and
        `last_return_day` are None: the deadline cannot be known from the
        record, so a human must decide.
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
        store_product_ids = {p.id for p in db.list_products(conn, order.store_id)}
        as_of = db.world_asof(conn)

    facts = load_facts()
    override = store.return_window_days_override if store else None
    window = effective_return_window_days(facts["return_window_days"], override)
    restocking = bool(store and store.restocking_fee_opt_in)
    policy_ids = ["cw-returns"]
    if override is not None:
        policy_ids.append("cw-store-overrides")
    if restocking:
        policy_ids.append("cw-restocking-fees")
    store_policy = f"store-{store.slug}-policy" if store else None
    if store_policy in {doc.policy_id for doc in load_policy_docs()}:
        policy_ids.append(store_policy)

    issues: list[str] = []
    last_day = None
    if order.status != "delivered":
        eligible: bool | None = False
        reason = STATUS_REASONS.get(order.status, f"status_{order.status}")
    else:
        issues = _record_issues(order, store_product_ids, as_of)
        if issues:
            eligible, reason = None, "inconsistent_record"
        else:
            last_day = order.delivered_at + timedelta(days=window)
            eligible = is_refund_eligible(
                status=order.status,
                delivered_at=order.delivered_at,
                as_of=as_of,
                return_window_days=window,
            )
            reason = "within_window" if eligible else "window_passed"

    result = {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "store_name": store.name if store else None,
        "eligible": eligible,
        "reason": reason,
        "return_window_days": window,
        "window_source": "store_override" if override is not None else "platform_default",
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "last_return_day": last_day.isoformat() if last_day else None,
        "as_of": as_of.isoformat(),
        "data_issues": issues,
        "refund_needs_human_approval": (
            refund_needs_approval(order.total_usd, facts["refund_auto_approve_threshold_usd"])
            if eligible
            else None
        ),
        "restocking_fee_may_apply": restocking,
        "policy_ids": policy_ids,
    }
    if issues:
        result["note"] = (
            "the order record is inconsistent, so the return deadline cannot be "
            "determined; do not estimate one, escalate to a human"
        )
    return result
