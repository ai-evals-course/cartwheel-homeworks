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

from difflib import SequenceMatcher
from typing import Any

from agent import db
from agent.auth import AuthContext, can_cancel_order, permission_denied
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20
FIND_ORDER_LIMIT = 5
MIN_PRODUCT_NAME_SCORE = 70


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
        "reason": f"no policy with id {policy_id}",
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
            "reason": "max_price_usd must be strictly positive",
        }
    clamped_limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    tokens = query.lower().split()
    with db.connection() as conn:
        store_id = None
        if store is not None:
            found = db.get_store_by_name(conn, store)
            if found is None:
                return {
                    "ok": False,
                    "error": "not_found",
                    "reason": f"no store matching {store!r}",
                }
            store_id = found.id
        candidates = db.list_products(conn, store_id)
    matches: list[Any] = []
    for product in candidates:
        haystack = f"{product.title} {product.description}".lower()
        if not all(token in haystack for token in tokens):
            continue
        if max_price_usd is not None and product.price_usd > max_price_usd:
            continue
        matches.append(product)
    matches.sort(key=lambda p: (p.price_usd, p.id))
    truncated = matches[:clamped_limit]
    products = [
        {
            "product_id": p.id,
            "store_id": p.store_id,
            "title": p.title,
            "price_usd": p.price_usd,
        }
        for p in truncated
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
                "look up a specific order with get_order"
            ),
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(
                conn, ctx.user_id, limit=DEFAULT_ORDER_LIMIT
            )
        else:
            orders = db.list_orders_for_store(
                conn, ctx.store_id, limit=DEFAULT_ORDER_LIMIT
            )
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
                    "orders can be cancelled only before shipment"
                ),
            }
        db.set_order_status(conn, order_id, "cancelled")
        return {"ok": True, "order_id": order_id, "status": "cancelled"}


_QUERY_FILLER = frozenset(
    {
        "i",
        "a",
        "an",
        "the",
        "my",
        "bought",
        "buy",
        "purchased",
        "purchase",
        "ordered",
        "order",
        "got",
        "get",
        "last",
        "week",
        "weeks",
        "yesterday",
        "today",
        "ago",
        "looking",
        "want",
        "need",
        "find",
        "please",
    }
)


def _partial_ratio(left: str, right: str) -> float:
    """0-100 score matching thefuzz.fuzz.partial_ratio."""
    if not left or not right:
        return 0.0
    if len(left) <= len(right):
        shorter, longer = left, right
    else:
        shorter, longer = right, left
    matcher = SequenceMatcher(None, shorter, longer)
    scores: list[float] = []
    for block in matcher.get_matching_blocks():
        start = block.b - block.a
        if start < 0:
            start = 0
        window = longer[start : start + len(shorter)]
        ratio = SequenceMatcher(None, shorter, window).ratio()
        if ratio > 0.995:
            return 100.0
        scores.append(ratio)
    return 100.0 * max(scores) if scores else 0.0


def _product_name_score(query: str, title: str) -> float:
    """Score a natural-language query against a product title, 0-100."""
    query = query.lower()
    title = title.lower()
    score = _partial_ratio(query, title)
    for token in query.split():
        if token in _QUERY_FILLER or len(token) < 3:
            continue
        if token in title:
            return 100.0
        score = max(score, _partial_ratio(token, title))
    return score


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
    query = query.strip()
    if not query:
        return {"ok": True, "orders": []}
    with db.connection() as conn:
        products = {product.id: product for product in db.list_products(conn)}
        if ctx.role == "shopper":
            candidates = db.list_orders_for_user(conn, ctx.user_id, limit=10_000)
        elif ctx.role == "merchant":
            candidates = db.list_orders_for_store(
                conn, ctx.store_id, limit=10_000
            )
        else:
            candidates = []
            for store_id in {product.store_id for product in products.values()}:
                candidates.extend(
                    db.list_orders_for_store(conn, store_id, limit=10_000)
                )
    scored: list[tuple[float, Any]] = []
    for order in candidates:
        product = products.get(order.product_id)
        if product is None:
            continue
        score = _product_name_score(query, product.title)
        if score < MIN_PRODUCT_NAME_SCORE:
            continue
        scored.append((score, order))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    return {
        "ok": True,
        "orders": [
            order.to_public_dict() for _, order in scored[:FIND_ORDER_LIMIT]
        ],
    }


def get_store_info(ctx: AuthContext, store: str) -> dict[str, Any]:
    """Look up public information about a Cartwheel store. Risk tier: read.

    Every role may call this. The catalog of stores is public: name, category,
    return-window override, and restocking-fee opt-in. Matching uses
    agent.db.get_store_by_name (case-insensitive name or slug).

    Args:
        ctx: The caller's auth context. Unused here; every role may read stores.
        store: Store name or slug, e.g. "Juniper Home Goods".

    Returns:
        On success: {"ok": True, "store_id": int, "name": str, "slug": str,
        "category": str, "return_window_days_override": int | None,
        "restocking_fee_opt_in": bool, "platform_return_window_days": int,
        "effective_return_window_days": int} where the effective window is
        the store override if set, otherwise the platform default from
        facts.yaml.
        Empty or whitespace-only store: {"ok": False, "error":
        "invalid_argument", "reason": ...}.
        Unknown store: {"ok": False, "error": "not_found", "reason": ...}.
    """
    store = store.strip()
    if not store:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "store name must be non-empty",
        }
    with db.connection() as conn:
        found = db.get_store_by_name(conn, store)
    if found is None:
        return {
            "ok": False,
            "error": "not_found",
            "reason": f"no store matching {store!r}",
        }
    platform_window = load_facts()["return_window_days"]
    override = found.return_window_days_override
    return {
        "ok": True,
        "store_id": found.id,
        "name": found.name,
        "slug": found.slug,
        "category": found.category,
        "return_window_days_override": override,
        "restocking_fee_opt_in": found.restocking_fee_opt_in,
        "platform_return_window_days": platform_window,
        "effective_return_window_days": (
            override if override is not None else platform_window
        ),
    }
