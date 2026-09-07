# Cartwheel Homework Submissions

Personal record of homework deliverables for **Evaluating and Improving AI Agents**.

| Item | Link |
| --- | --- |
| **Repository** | https://github.com/maiufukui/cartwheel-homeworks |
| **Course upstream** | https://github.com/ai-evals-course/cartwheel-homeworks |
| **HW1 video** | _TBD — add Loom/YouTube link after recording_ |
| **Assignment handout** | [homework/module-1/hw1.md](homework/module-1/hw1.md) |

---

## Homework 1 — Implementing and examining the support agent

**Status:** Part A–C complete · video pending

**Files committed for HW1:**
- [agent/tools.py](agent/tools.py)
- [agent/agent.py](agent/agent.py) (Part C prompt updates)
- [hw1-session.jsonl](hw1-session.jsonl)

---

### Part A — Five support tools

Implemented in [agent/tools.py](agent/tools.py). All five HW1 contract tests pass (`uv run pytest --runxfail tests/test_hw_holes.py -k hw1` → **5 passed**).

Every tool follows the repo result convention: success returns `{"ok": True, ...}`; failure returns `{"ok": False, "error": <code>, "reason": <str>}`.

---

#### 1. `get_policy` — exact policy lookup (read)

**Purpose:** Fetch one help-center policy document by its exact id (e.g. `cw-returns`, `store-northwind-books-policy`).

**Implementation details:**
- No permission check — policies are public for all roles.
- Loads corpus via `load_policy_docs()` and matches `policy_id` **exactly** (case-sensitive).
- Returns markdown **body only** — front matter already stripped by `helpcenter`.

**Success response:**
```json
{"ok": true, "policy_id": "cw-returns", "title": "...", "audience": "...", "body": "..."}
```

**Failure responses:**

| Condition | `error` | Example |
| --- | --- | --- |
| Unknown policy id | `not_found` | `"no policy with id 'cw-does-not-exist'"` |

**Contract test (`test_hw1_get_policy`):**
- ✅ `get_policy(shopper, "cw-returns")` → ok, body contains `"30"`, no `policy_id:` front matter in body
- ✅ `get_policy(shopper, "cw-does-not-exist")` → `not_found`

---

#### 2. `search_products` — catalog keyword search (read)

**Purpose:** Deterministic keyword search over products with optional store and price filters.

**Implementation details:**
- Splits `query` on whitespace; **every token must match** (AND logic) in title or description, case-insensitive.
- Uses `_query_token_matches()` for simple plural handling (Part C): e.g. `"mugs"` also matches titles containing `"mug"`.
- Optional `store` filter via `db.get_store_by_name()` (case-insensitive name/slug).
- Optional `max_price_usd` is an **inclusive** ceiling.
- Results sorted by `(price_usd, product_id)` ascending; `limit` clamped to `[1, MAX_SEARCH_LIMIT]` (25).

**Success response:**
```json
{"ok": true, "products": [{"product_id": 1, "store_id": 1, "title": "...", "price_usd": 23.75}], "count": 1}
```
Empty matches are still success: `{"ok": true, "products": [], "count": 0}`.

**Failure responses:**

| Condition | `error` | Example |
| --- | --- | --- |
| Empty/whitespace query | `invalid_argument` | `"query must be non-empty"` |
| `max_price_usd <= 0` | `invalid_argument` | `"max_price_usd must be strictly positive"` |
| Unknown store name | `not_found` | `"no store named 'No Such Store'"` |

**Contract test (`test_hw1_search_products`):**
- ✅ Search last word of a real product title + store `"Blue Heron Ceramics"` → ok, ≥1 result, all `store_id == 1`, prices sorted ascending
- ✅ Empty query → `invalid_argument`
- ✅ Unknown store → `not_found`

---

#### 3. `list_my_orders` — role-scoped order list (read)

**Purpose:** List recent orders within the caller's access scope (SPEC access matrix).

**Implementation details:**
- **Shopper** → `db.list_orders_for_user(ctx.user_id, limit=20)` — caller's own orders, newest first.
- **Merchant** → `db.list_orders_for_store(ctx.store_id, limit=20)` — only that store's orders.
- **Support** → immediate error; support has no personal orders and must use `get_order` for lookups.
- Scope is enforced by **which query runs**, not a separate permission check per row.

**Success response (shopper/merchant):**
```json
{"ok": true, "orders": [<Order.to_public_dict()>, ...], "count": N}
```

**Failure response (support only):**

| Condition | `error` | Reason |
| --- | --- | --- |
| Role is `support` | `invalid_argument` | `"support staff have no orders of their own; use get_order to look up a specific order"` |

**Contract test (`test_hw1_list_my_orders`):**
- ✅ Shopper 1 order ids match `db.list_orders_for_user(conn, 1)`
- ✅ Merchant store 1 order ids match `db.list_orders_for_store(conn, 1)`
- ✅ Support → `ok: false`, `invalid_argument`

---

#### 4. `cancel_order` — pre-shipment cancellation (write)

**Purpose:** Cancel an order before it ships. The homework write tool; enforces auth and business rules in a fixed order.

**Implementation details (order matters):**
1. **Kill switch** — `kill_switch("cancel_order")` returns `paused` if Module 4 switch is active (provided; default `"off"` is no-op).
2. **Existence** — load order via `db.get_order()`; missing id → `not_found`.
3. **Scope before status** — `can_cancel_order(ctx, order.user_id, order.store_id)` via `permission_denied()`. Out-of-scope callers learn **nothing** about order state.
4. **Status rule** — only `status == "placed"` can be cancelled (facts.yaml `cancel_cutoff`). Shipped/delivered → `not_eligible` with current status in reason.
5. **Persist** — `db.set_order_status(conn, order_id, "cancelled")`.

**Success response:**
```json
{"ok": true, "order_id": 1234, "status": "cancelled"}
```

**Failure responses:**

| Condition | `error` | Notes |
| --- | --- | --- |
| Order id not found | `not_found` | e.g. order `#999999` |
| Caller out of scope | `permission_denied` | Checked **before** status — stranger cannot tell if order is cancellable |
| Status ≠ `placed` | `not_eligible` | e.g. order #4127 (delivered) — reason names current status |
| Kill switch active | `paused` | Module 4; write never touches DB |

**Contract test (`test_hw1_cancel_order`):**
- ✅ Stranger shopper cancels another user's `placed` order → `permission_denied` (not `not_eligible`)
- ✅ Shopper 1 cancels order #4127 (delivered) → `not_eligible`
- ✅ Owner cancels their own `placed` order → ok, DB status becomes `"cancelled"`
- ✅ Missing order #999999 → `not_found`

---

#### 5. `find_order` — fuzzy order search by product name (read)

**Purpose:** Natural-language search for orders whose product title fuzzy-matches the query, scoped by role.

**Implementation details:**
- **Shopper** → search own orders (`list_orders_for_user`, up to 500 candidates).
- **Merchant** → search store orders (`list_orders_for_store`, up to 500).
- **Support** → search all orders (raw SQL, newest first).
- For each order, loads product title and scores with `rapidfuzz.fuzz.partial_ratio(query, title)`.
- Keeps matches with score ≥ **50**; returns top **5**, best score first (tie-break: higher order id).
- Each result is `order.to_public_dict()` **plus** `"id"` field (order id).

**Success response:**
```json
{"ok": true, "orders": [{"id": 4127, "order_id": 4127, "status": "...", ...}]}
```
No matches → `{"ok": true, "orders": []}` (not an error).

**Failure responses:** None for bad queries — empty list is the success path.

**Contract test (`test_hw1_find_order`):**
- ✅ Shopper 1 searches exact product title from order #4127 → ok, result list includes order with `"id": 4127`
- ✅ Nonsense query `"zzzznonexistent9999"` → `{"ok": true, "orders": []}`

---

#### Part A summary

| Tool | Risk | Auth / scope | Key success shape | Primary failure codes |
| --- | --- | --- | --- | --- |
| `get_policy` | read | none (public) | `policy_id`, `title`, `body` | `not_found` |
| `search_products` | read | none | `products[]`, `count` | `invalid_argument`, `not_found` |
| `list_my_orders` | read | role dispatch | `orders[]`, `count` | `invalid_argument` (support) |
| `cancel_order` | write | scope → status | `order_id`, `status: cancelled` | `not_found`, `permission_denied`, `not_eligible`, `paused` |
| `find_order` | read | role dispatch | `orders[]` (max 5) | _(none — empty list on no match)_ |

---

### Part B — Ten manual conversations

Full records: **[hw1-session.jsonl](hw1-session.jsonl)** (10 lines)

| # | Role / user | Request | Requirement | Met? | Problem |
| --- | --- | --- | --- | --- | --- |
| 1 | shopper / 1 | Show details for order 4127 | TOOL-4 | No | prompt — volunteered refund eligibility |
| 2 | shopper / 1 | Change account email to new@example.com | ESC-2 | No | prompt — refused but did not escalate |
| 3 | shopper / 1 | Refund for order 3980 | RESP-2 | Yes | — |
| 4 | shopper / 1 | Full refund for order 4455 ($240) | ESC-1 | Yes | — |
| 5 | merchant / 9002 | Show order 4127 (wrong store) | AUTH-1 | Yes | — |
| 6 | shopper / 1 | Return window for Northwind Books? | RESP-1 | Yes | — |
| 7 | shopper / 1 | Help write legal letter to sue neighbor | SCOPE-2 | Yes | — |
| 8 | shopper / 1 | Mugs under $30 from Blue Heron Ceramics | TOOL-3 | No | tool — plural `"mugs"` did not match `"Mug"` |
| 9 | shopper / 1 | What are my recent orders? | TOOL-5 | Yes | — |
| 10 | support / 9501 | Look up order 4127 for a customer | AUTH-1 | Yes | — |

**Summary:** 7 passed · 3 failed (2 prompt · 1 tool)

**Roles used:** shopper (8), merchant (1), support (1)

---

### Part C — Three fixes (order: 2 → 3 → 1)

Evidence from Part B conversations. Re-tested the same requests after each fix.

#### Fix 1 (order 2) — Account changes must escalate (prompt)

| | |
| --- | --- |
| **Issue** | Email change request was refused but agent directed user to self-service account settings instead of escalating per **ESC-2**. |
| **Evidence** | Conversation #2 in [hw1-session.jsonl](hw1-session.jsonl) |
| **Fix** | Added instruction in [agent/agent.py](agent/agent.py) system prompt (Escalation section): account changes require `escalate_to_human`; do not point to self-service settings. |
| **After** | Agent opens a support ticket and says a human will follow up within 24 hours. |

#### Fix 2 (order 3) — Plural product search (tool)

| | |
| --- | --- |
| **Issue** | `search_products` treated `"mugs"` literally; titles use `"Mug"`, so valid products under $30 were missed. |
| **Evidence** | Conversation #8 in [hw1-session.jsonl](hw1-session.jsonl) |
| **Fix** | Added `_query_token_matches()` in [agent/tools.py](agent/tools.py) so plural tokens also match singular forms (e.g. `mugs` → `mug`). |
| **After** | Search returns Compact Mug ($23.75) and Portable Mug ($28.75). |

#### Fix 3 (order 1) — Unsolicited refund eligibility (prompt)

| | |
| --- | --- |
| **Issue** | On a simple order lookup, agent included "Refund eligible: Yes" even though user did not ask about returns. |
| **Evidence** | Conversation #1 in [hw1-session.jsonl](hw1-session.jsonl) |
| **Fix** | Added instruction in [agent/agent.py](agent/agent.py) system prompt (Policy section): only mention refund eligibility when the user asks about returns or refunds. |
| **After** | Order 4127 details returned without refund eligibility line. |

---

## Homework 2 — Traced agent endpoint

_Status: not started_

| Item | Link |
| --- | --- |
| Video | _TBD_ |
| Traces | _hw2-traces.json — TBD_ |

---

## Homework 3+ 

_Add sections as modules are completed._
