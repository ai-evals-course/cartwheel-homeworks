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
from datetime import timedelta
from difflib import SequenceMatcher
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
    return {"ok": False, "error": "not_found", "reason": f"no policy doc with id '{policy_id}'"}


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
        return {"ok": False, "error": "invalid_argument", "reason": "empty query"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "max_price_usd must be positive",
        }
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    with db.connection() as conn:
        store_id = None
        if store is not None:
            found = db.get_store_by_name(conn, store)
            if found is None:
                return {"ok": False, "error": "not_found", "reason": f"no store named '{store}'"}
            store_id = found.id
        products = db.list_products(conn, store_id)
    matches = []
    for product in products:
        text = f"{product.title} {product.description}".lower()
        if not all(token in text for token in tokens):
            continue
        if max_price_usd is not None and product.price_usd > max_price_usd:
            continue
        matches.append(product)
    matches.sort(key=lambda p: (p.price_usd, p.id))
    results = [
        {
            "product_id": p.id,
            "store_id": p.store_id,
            "title": p.title,
            "price_usd": p.price_usd,
        }
        for p in matches[:limit]
    ]
    return {"ok": True, "products": results, "count": len(results)}


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
            "reason": (
                "support staff have no orders of their own; "
                "look up specific orders with get_order"
            ),
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT)
        else:
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT)
    results = [order.to_public_dict() for order in orders]
    return {"ok": True, "orders": results, "count": len(results)}


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
    query_words = _search_words(query)
    if not query_words:
        return {"ok": False, "error": "invalid_argument", "reason": "query names no product"}
    if ctx.role == "shopper":
        scope: dict[str, Any] = {"user_id": ctx.user_id}
    elif ctx.role == "merchant" and ctx.store_id is not None:
        scope = {"store_id": ctx.store_id}
    elif ctx.role == "support":
        scope = {"all_orders": True}
    else:
        return permission_denied(f"role '{ctx.role}' may not search orders")
    with db.connection() as conn:
        candidates = db.list_order_search_candidates(conn, **scope)
        titles = {p.id: p.title for p in db.list_products(conn)}
    matches = []
    for order in candidates:
        if _title_matches(query, query_words, titles.get(order.product_id, "")):
            matches.append(order.to_public_dict())
            if len(matches) == FIND_ORDER_LIMIT:
                break
    return {"ok": True, "orders": matches}


FIND_ORDER_LIMIT = 5
FUZZY_WORD_RATIO = 0.85
# Words that describe the purchase rather than the product, e.g. the
# "I bought last week" in "earmuffs I bought last week".
_QUERY_STOPWORDS = frozenset(
    "a an the my me i i'm im we our you your it its this that these those of for "
    "to from in on at with and or some any one ago last past this week weeks month "
    "months year years day days yesterday today recently recent bought buy ordered "
    "order orders purchased purchase got get where is was are were did do find show "
    "need want looking about".split()
)


def _search_words(text: str) -> list[str]:
    """Lowercase alphanumeric words of `text`, minus purchase-context filler."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in _QUERY_STOPWORDS]


def _title_matches(query: str, query_words: list[str], title: str) -> bool:
    """Case-insensitive substring match, else any query word fuzzily equal to a
    title word (tolerates plurals and small typos such as "vases" or "teapto")."""
    if not title:
        return False
    if query.strip().lower() in title.lower():
        return True
    title_words = _search_words(title)
    return any(
        SequenceMatcher(None, qw, tw).ratio() >= FUZZY_WORD_RATIO
        or (len(tw) >= 4 and qw.startswith(tw))
        for qw in query_words
        for tw in title_words
    )


# ---------------------------------------------------------------------------
# Student-added tools (HW1 Part A extension). All three are read-only.
# ---------------------------------------------------------------------------

RECENT_ORDERS_IN_SUMMARY = 5


def _store_policy_id(slug: str) -> str | None:
    """The store's own policy doc id, if the corpus has one."""
    policy_id = f"store-{slug}-policy"
    if any(doc.policy_id == policy_id for doc in load_policy_docs()):
        return policy_id
    return None


def check_refund_eligibility(
    ctx: AuthContext, order_id: int, amount_usd: float | None = None
) -> dict[str, Any]:
    """Explain whether an order can be refunded. Risk tier: read.

    Same scope as get_order: shoppers their own orders, merchants their
    store's orders, support any order. Scope is checked before anything about
    the order is returned.

    Args:
        ctx: The caller's auth context.
        order_id: The order to check.
        amount_usd: The refund amount being considered; defaults to the order
            total. Must be positive and no more than the order total.

    Returns:
        {"ok": True, "order_id", "refund_eligible", "status", "delivered_at",
        "as_of", "return_window_days", "window_source", "window_ends",
        "days_since_delivery", "days_remaining", "amount_usd",
        "needs_human_approval", "approval_threshold_usd", "reasons",
        "data_issues", "policy_ids"}. `refund_eligible` is the order's stored
        flag, which is what issue_refund enforces. `data_issues` lists
        inconsistent dates; when it is non-empty, escalate instead of
        asserting a deadline. Errors: not_found, permission_denied,
        invalid_argument.
    """
    facts = load_facts()
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
        product_store_ids = {p.id: p.store_id for p in db.list_products(conn)}

    amount = order.total_usd if amount_usd is None else amount_usd
    if amount <= 0 or amount > order.total_usd:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                f"amount must be positive and at most the order total "
                f"${order.total_usd:.2f}"
            ),
        }

    override = store.return_window_days_override if store else None
    window = effective_return_window_days(facts["return_window_days"], override)
    threshold = facts["refund_auto_approve_threshold_usd"]

    data_issues = []
    if order.status == "delivered" and order.delivered_at is None:
        data_issues.append("order is marked delivered but has no delivery date")
    if order.shipped_at and order.delivered_at and order.shipped_at > order.delivered_at:
        data_issues.append("recorded shipment date is after the delivery date")
    if order.delivered_at and order.delivered_at > as_of:
        data_issues.append("recorded delivery date is in the future")
    if product_store_ids.get(order.product_id) not in (None, order.store_id):
        data_issues.append("order's store differs from the store that sells its product")

    reasons = []
    window_ends = days_since = days_remaining = None
    if order.status != "delivered":
        reasons.append(f"only delivered orders can be refunded; status is '{order.status}'")
    if order.delivered_at is not None and not data_issues:
        window_ends = order.delivered_at + timedelta(days=window)
        days_since = (as_of - order.delivered_at).days
        days_remaining = max(0, window - days_since)
        if days_since > window:
            reasons.append(
                f"delivered {days_since} days ago; the {window}-day return window "
                f"ended {window_ends}"
            )
    computed = order.delivered_at is not None and is_refund_eligible(
        status=order.status,
        delivered_at=order.delivered_at,
        as_of=as_of,
        return_window_days=window,
    )
    if computed != order.refund_eligible and not data_issues:
        data_issues.append("stored eligibility flag disagrees with the return-window rule")

    policy_ids = ["cw-returns", "cw-refunds"]
    store_policy = _store_policy_id(store.slug) if store else None
    if override is not None and store_policy:
        policy_ids.append(store_policy)
    return {
        "ok": True,
        "order_id": order_id,
        "refund_eligible": order.refund_eligible,
        "status": order.status,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "as_of": as_of.isoformat(),
        "return_window_days": window,
        "window_source": "store_override" if override is not None else "platform_default",
        "window_ends": window_ends.isoformat() if window_ends else None,
        "days_since_delivery": days_since,
        "days_remaining": days_remaining,
        "amount_usd": amount,
        "needs_human_approval": refund_needs_approval(amount, threshold),
        "approval_threshold_usd": threshold,
        "reasons": reasons,
        "data_issues": data_issues,
        "policy_ids": policy_ids,
    }


def get_store_info(ctx: AuthContext, store: str) -> dict[str, Any]:
    """Public store details and the policies that override platform defaults.

    Every role may read this; it returns only public store fields.

    Args:
        ctx: The caller's auth context. Unused; store info is public.
        store: Store name or slug, matched case-insensitively like
            agent.db.get_store_by_name.

    Returns:
        {"ok": True, "store_id", "name", "slug", "category",
        "return_window_days", "return_window_source",
        "platform_return_window_days", "restocking_fee": {"opt_in",
        "max_percent", "opened_items_only"}, "store_policy_id",
        "policy_ids"}. `store_policy_id` is None when the store has no policy
        doc of its own. Errors: invalid_argument (empty store), not_found.
    """
    if not store.strip():
        return {"ok": False, "error": "invalid_argument", "reason": "empty store name"}
    facts = load_facts()
    with db.connection() as conn:
        found = db.get_store_by_name(conn, store.strip())
    if found is None:
        return {"ok": False, "error": "not_found", "reason": f"no store named '{store}'"}
    platform_window = facts["return_window_days"]
    override = found.return_window_days_override
    store_policy = _store_policy_id(found.slug)
    policy_ids = ["cw-store-overrides", "cw-returns"]
    if found.restocking_fee_opt_in:
        policy_ids.append("cw-restocking-fees")
    if store_policy:
        policy_ids.append(store_policy)
    return {
        "ok": True,
        "store_id": found.id,
        "name": found.name,
        "slug": found.slug,
        "category": found.category,
        "return_window_days": effective_return_window_days(platform_window, override),
        "return_window_source": "store_override" if override is not None else "platform_default",
        "platform_return_window_days": platform_window,
        "restocking_fee": {
            "opt_in": found.restocking_fee_opt_in,
            "max_percent": facts["restocking_fee_max_percent"] if found.restocking_fee_opt_in else 0,
            "opened_items_only": facts["restocking_fee_opened_items_only"],
        },
        "store_policy_id": store_policy,
        "policy_ids": policy_ids,
    }


def summarize_order_history(ctx: AuthContext) -> dict[str, Any]:
    """Summarize all orders in the caller's own scope. Risk tier: read.

    Shoppers get their own orders, merchants their store's orders. Support
    staff have no orders of their own, so they get an invalid_argument error
    (as with list_my_orders). Scope comes from ctx, never from arguments.

    Returns:
        {"ok": True, "scope": "shopper"|"merchant", "order_count",
        "by_status": {status: count}, "total_value_usd",
        "refund_eligible_count", "first_order_at", "last_order_at",
        "recent_orders": [...]} where total_value_usd (spent for shoppers,
        sales for merchants) excludes cancelled and refunded orders, and each
        recent order is to_public_dict() plus
        "product_title" (None when the catalog has no title, never invented).
    """
    if ctx.role == "shopper":
        scope: dict[str, Any] = {"user_id": ctx.user_id}
    elif ctx.role == "merchant" and ctx.store_id is not None:
        scope = {"store_id": ctx.store_id}
    elif ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": (
                "support staff have no orders of their own; "
                "look up specific orders with get_order"
            ),
        }
    else:
        return permission_denied(f"role '{ctx.role}' may not summarize orders")
    with db.connection() as conn:
        orders = db.list_order_search_candidates(conn, **scope)
        titles = {p.id: p.title for p in db.list_products(conn)}
    by_status: dict[str, int] = {}
    for order in orders:
        by_status[order.status] = by_status.get(order.status, 0) + 1
    spent_cents = sum(
        o.total_cents for o in orders if o.status not in ("cancelled", "refunded")
    )
    recent = []
    for order in orders[:RECENT_ORDERS_IN_SUMMARY]:
        payload = order.to_public_dict()
        payload["product_title"] = titles.get(order.product_id) or None
        recent.append(payload)
    return {
        "ok": True,
        "scope": ctx.role,
        "order_count": len(orders),
        "by_status": by_status,
        "total_value_usd": spent_cents / 100,
        "refund_eligible_count": sum(1 for o in orders if o.refund_eligible),
        "first_order_at": orders[-1].ordered_at.isoformat() if orders else None,
        "last_order_at": orders[0].ordered_at.isoformat() if orders else None,
        "recent_orders": recent,
    }
