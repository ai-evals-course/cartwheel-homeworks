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
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20

# find_order tuning. The query is natural language ("earmuffs I bought last
# week"), so the filler words are dropped before scoring and a match must
# clear MATCH_THRESHOLD to count.
FIND_ORDER_LIMIT = 5
MATCH_THRESHOLD = 0.65
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "ago", "about", "back", "bought", "buy", "did", "for",
        "from", "get", "i", "in", "is", "it", "last", "me", "month", "my", "of",
        "on", "order", "ordered", "orders", "purchase", "purchased", "recently",
        "that", "the", "this", "to", "week", "was", "were", "what", "when",
        "where", "with", "year",
    }
)


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
    tokens = query.strip().lower().split()
    if not tokens:
        return {"ok": False, "error": "invalid_argument", "reason": "empty query"}
    if max_price_usd is not None and max_price_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": f"max_price_usd must be positive, got {max_price_usd}",
        }
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))

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

        matches = []
        for product in db.list_products(conn, store_id):
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
            "reason": (
                "support staff have no orders of their own; "
                "look up a specific order with get_order instead"
            ),
        }

    with db.connection() as conn:
        if ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)
        else:
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)

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
        # Scope before state: an out-of-scope caller gets the same denial
        # whatever the order's status, so the error leaks nothing about it.
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
    if not query.strip():
        return {"ok": True, "orders": []}

    with db.connection() as conn:
        products = db.list_products(conn)
        titles = {product.id: product.title for product in products}
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)
        elif ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)
        else:
            # Support searches every store. agent/db.py has no "all orders"
            # helper, so union the per-store lists rather than writing SQL here.
            orders = []
            for store_id in sorted({product.store_id for product in products}):
                orders.extend(
                    db.list_orders_for_store(conn, store_id, DEFAULT_ORDER_LIMIT)
                )

    scored = []
    for order in orders:
        title = titles.get(order.product_id, "")
        score = _match_score(query, title)
        if score >= MATCH_THRESHOLD:
            scored.append((score, order, title))

    # Best match first; ties keep the newest order first.
    scored.sort(key=lambda row: (-row[0], -row[1].ordered_at.toordinal(), -row[1].id))
    matches = []
    for score, order, title in scored[:FIND_ORDER_LIMIT]:
        payload = order.to_public_dict()
        payload["product_title"] = title
        matches.append(payload)
    return {"ok": True, "orders": matches}


def _match_score(query: str, title: str) -> float:
    """How well a natural-language query matches one product title, 0.0 to 1.0.

    Substring containment either way scores 1.0 ("my blue heron mug" contains
    the title "Blue Heron Mug"). Otherwise the query's content words are
    compared with the title's words, so a near miss ("earmufs") or a partial
    name still matches. Uses the standard library's difflib rather than an
    extra fuzzy-matching dependency.
    """
    if not title:
        return 0.0
    query_text, title_text = query.lower().strip(), title.lower()
    if title_text in query_text or query_text in title_text:
        return 1.0

    title_words = _WORD_RE.findall(title_text)
    query_words = [
        word
        for word in _WORD_RE.findall(query_text)
        if len(word) > 2 and word not in _STOPWORDS
    ]
    best = SequenceMatcher(None, query_text, title_text).ratio()
    for query_word in query_words:
        for title_word in title_words:
            # Both sides must be substantial: a one-letter title word is a
            # substring of nearly every query word ("c" in "ceramic").
            if len(title_word) > 2 and (
                query_word in title_word or title_word in query_word
            ):
                best = max(best, 0.9)
            else:
                # A misspelled word is a weaker signal than a clean hit, so
                # its similarity is discounted before it competes with one.
                best = max(
                    best, SequenceMatcher(None, query_word, title_word).ratio() * 0.9
                )
    return best
