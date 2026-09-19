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
from difflib import SequenceMatcher
from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, permission_denied
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20
FUZZY_MATCH_THRESHOLD = 0.85


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
    all_policies = {doc.policy_id: doc for doc in load_policy_docs()}
    if policy_id not in all_policies:
        return {"ok": False, "error": "not_found", "reason": f"Policy ID '{policy_id}' not found."}
    policy = all_policies[policy_id]
    return {"ok": True, "body": policy.body, "policy_id": policy_id, "title": policy.title, "audience": policy.audience}


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
    
    if len(query.strip()) == 0:
        return {"ok": False, "error": "invalid_argument", "reason": "Query must be non-empty after stripping whitespace."}
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    with db.connection() as conn:
        store_info = db.get_store_by_name( conn, store) if store else None
        store_id = store_info.id if store_info else None
        if store_id is None and store is not None:
            return {"ok": False, "error": "not_found", "reason": f"Store '{store}' not found."}
        if max_price_usd is not None and max_price_usd <= 0:
            return {"ok": False, "error": "invalid_argument", "reason": "max_price_usd must be strictly positive if given."}
        all_products = db.list_products(conn, store_id=store_id)
        all_products = [
            {"product_id": product.id, "store_id": product.store_id, "title": product.title,
        "price_usd": product.price_cents / 100.0} for product in all_products
        if product.price_cents is not None and (max_price_usd is None or product.price_cents / 100.0 <= max_price_usd) and 
        all(token.lower() in (product.title + " " + product.description).lower() for token in query.split())
        ]
        all_products.sort(key=lambda x: (x["price_usd"], x["product_id"]))
        if len(all_products) > limit:
            all_products = all_products[:limit]

    return {"ok": True, "products": all_products, "count": len(all_products)}


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
    if ctx.role == "shopper":
        with db.connection() as conn:
            orders = db.list_orders_for_user(conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT)
            return {"ok": True, "orders": [order.to_public_dict() for order in orders], "count": len(orders)}
    elif ctx.role == "merchant":
        with db.connection() as conn:
            orders = db.list_orders_for_store(conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT)
            return {"ok": True, "orders": [order.to_public_dict() for order in orders], "count": len(orders)}
    elif ctx.role == "support":
        return {"ok": False, "error": "invalid_argument", "reason": "Support staff have no orders of their own; use get_order to look up specific orders."}


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

    if ctx.store_id is None and ctx.role == "merchant":
        return permission_denied(reason="Merchant auth context requires a store_id.")
    with db.connection() as conn:
        order_info = db.get_order(conn, order_id)
    if order_info is None:
        return {"ok": False, "error": "not_found", "reason": f"Order {order_id} not found."}
    if not can_cancel_order(ctx, order_info.user_id, order_info.store_id):
        return permission_denied(reason=f"Role '{ctx.role}' is not allowed to cancel order {order_id}.")
    order_status = order_info.status
    
    if order_status != "placed":
        return {"ok": False, "error": "not_eligible", "reason": f"Order {order_id} is in status '{order_status}'; orders can be cancelled only before shipment."}
    with db.connection() as conn:
        db.set_order_status(conn, order_id, "cancelled")
    return {"ok": True, "order_id": order_id, "status": "cancelled"}


_WORD_RE = re.compile(r"[a-z0-9]+")
# Filler words that appear in natural-language queries ("the earmuffs I bought
# last week") but never identify a product on their own.
_QUERY_STOP_WORDS = frozenset(
    "a an the my me i and or of for in on at to with from that this it is was "
    "did have has had can you get one some any bought ordered order orders "
    "purchased got last week month year ago yesterday recently please find "
    "where which what about want need item items product products thing "
    "stuff".split()
)


def _fuzzy_match(query: str, reference: str) -> float:
    """Score how well ``query`` names the product ``reference``, 0.0 to 1.0.

    A whole-word, case-insensitive substring match scores 1.0, so an exact or
    partial product title always wins ("earmuffs" in "Wool Earmuffs", but not
    "tea" in "Steamer Basket"). Otherwise every content word of the query is
    compared with every word of the reference using difflib, and the score is
    the average of two numbers: the best single-word ratio, which keeps recall
    high ("earmufs I bought last week" scores 0.93 against "Wool Earmuffs"),
    and the mean best ratio across query words, which ranks "Heavy-Duty Vase"
    above "Ceramic Vase" for the query "heavy duty vase". Filler words such as
    "the" or "last" and words shorter than three characters are ignored; a
    query with no content words scores 0.0.

    Compare the result with FUZZY_MATCH_THRESHOLD to decide whether it counts
    as a match, and sort candidates by score with a stable sort so ties keep
    the caller's newest-first order.
    """
    query_text = query.casefold().strip()
    reference_text = reference.casefold().strip()
    if not query_text or not reference_text:
        return 0.0
    if re.search(rf"\b{re.escape(query_text)}\b", reference_text):
        return 1.0
    query_words = {
        word
        for word in _WORD_RE.findall(query_text)
        if len(word) >= 3 and word not in _QUERY_STOP_WORDS
    }
    reference_words = {
        word for word in _WORD_RE.findall(reference_text) if len(word) >= 3
    }
    if not query_words or not reference_words:
        return 0.0
    best_per_word = [
        max(
            SequenceMatcher(None, query_word, reference_word).ratio()
            for reference_word in reference_words
        )
        for query_word in query_words
    ]
    return (max(best_per_word) + sum(best_per_word) / len(best_per_word)) / 2


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
    if ctx.role == "shopper":
        with db.connection() as conn:
            orders = db.list_order_search_candidates(conn, user_id=ctx.user_id)
    elif ctx.role == "merchant":
        with db.connection() as conn:
            orders = db.list_order_search_candidates(conn, store_id=ctx.store_id)
    elif ctx.role == "support":
        with db.connection() as conn:
            orders = db.list_order_search_candidates(conn, all_orders=True)
    else:
        return permission_denied(reason=f"Role '{ctx.role}' is not supported for find_order.")

    with db.connection() as conn:
        products = {product.id: product.title for product in db.list_products(conn)}
    scored_orders = [
        (order, _fuzzy_match(query, products.get(order.product_id, "")))
        for order in orders
    ]
    scored_orders.sort(key=lambda x: (-x[1], -x[0].id))  # Sort by score descending, then order ID descending
    top_orders = [order.to_public_dict() for order, score in scored_orders if score >= FUZZY_MATCH_THRESHOLD][:5]
    return {"ok": True, "orders": top_orders}
    


# ---------------------------------------------------------------------------
# Additional tool (HW1 Part A, student-defined).
#
# Evidence for the gap: in a recorded Part B conversation the agent got
# `store_id: 2` back from search_products, could not turn that id into a store
# name or policy, and wrongly told the shopper the 30-day platform window
# applied to a Juniper Home Goods item (the store's window is 14 days).
# ---------------------------------------------------------------------------

PLATFORM_RETURN_POLICY_ID = "cw-returns"


def get_store_info(
    ctx: AuthContext,
    store_id: int | None = None,
    store_name: str | None = None,
) -> dict[str, Any]:
    """Look up one store's public details and return rules. Risk tier: read.

    Store names and store policy overrides are public help-center content, so
    every role may call this tool and it needs no permission check. It returns
    no order, shopper, or sales data.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        store_id: A store id, for example the `store_id` field on a product
            or an order.
        store_name: A store name or slug, matched case-insensitively with
            agent.db.get_store_by_name.
        Exactly one of the two must be given; otherwise return
        {"ok": False, "error": "invalid_argument", "reason": ...}.

    Returns:
        On success: {"ok": True, "store": {...}} where store holds
            "store_id", "name", "category",
            "return_window_days": the window that applies to this store,
            "has_return_window_override": True when the store sets its own,
            "platform_return_window_days": the facts.yaml default,
            "restocking_fee_opt_in": bool,
            "restocking_fee_max_percent": the facts.yaml cap, or None when
                the store has not opted in,
            "store_policy_id": the store's own policy doc id, or None when
                the store has no policy doc,
            "return_window_policy_id": the policy id to cite for the window.
        If no store matches: {"ok": False, "error": "not_found", "reason": ...}
        naming what was looked up.
    """
    name = store_name.strip() if store_name is not None else None
    if (store_id is None) == (not name):
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "provide exactly one of store_id or store_name",
        }
    with db.connection() as conn:
        store = db.get_store(conn, store_id) if store_id is not None else db.get_store_by_name(conn, name)
    if store is None:
        looked_up = f"id {store_id}" if store_id is not None else f"name '{name}'"
        return {"ok": False, "error": "not_found", "reason": f"no store with {looked_up}"}

    facts = load_facts()
    platform_window = facts["return_window_days"]
    has_override = store.return_window_days_override is not None
    policy_ids = {doc.policy_id for doc in load_policy_docs()}
    candidate = f"store-{store.slug}-policy"
    store_policy_id = candidate if candidate in policy_ids else None
    return {
        "ok": True,
        "store": {
            "store_id": store.id,
            "name": store.name,
            "category": store.category,
            "return_window_days": store.return_window_days_override if has_override else platform_window,
            "has_return_window_override": has_override,
            "platform_return_window_days": platform_window,
            "restocking_fee_opt_in": store.restocking_fee_opt_in,
            "restocking_fee_max_percent": (
                facts["restocking_fee_max_percent"] if store.restocking_fee_opt_in else None
            ),
            "store_policy_id": store_policy_id,
            "return_window_policy_id": (
                store_policy_id if has_override and store_policy_id else PLATFORM_RETURN_POLICY_ID
            ),
        },
    }
