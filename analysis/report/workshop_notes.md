# Workshop notes (HW4 Part C)

Fresh Cartwheel runs via `uv run python -m agent.cli` with Raindrop Workshop
instrumentation (`RAINDROP_LOCAL_DEBUGGER=http://localhost:5899/v1/` in `.env`).
Langfuse remains available with `--trace`; these runs used Workshop only.

**Setup:** `raindrop-openai-agents` wired in `observability/instrument.py` +
`agent/cli.py`. Workshop UI: http://localhost:5899

**Workshop limitation observed:** Python integration surfaces one LLM span per
turn (input/output previews). Individual tool spans did not appear in Workshop
outlines even when `--debug` showed `search_products`, `get_order`, etc. Tool
ground truth was verified from CLI debug output and compared to final replies.

---

## Inspected runs (8)

| Run ID | Role | User | Prompt (abbrev.) | CLI tools observed |
|--------|------|------|------------------|-------------------|
| `4dc99039-fe44-4669-aca1-94349bb5db09` | shopper | 1 | Where is order 4127? | `get_order` |
| `c71dcbcf-2256-484a-9aa2-471903aca1e4` | shopper | 1 | Find ceramic mugs under $30 | `search_products` |
| `0f5fb35b-58d9-44dd-9a75-acab62470e29` | merchant | 9001 | List open orders for my store | `list_my_orders` |
| `914a665b-0473-401e-b611-4517d53a3f03` | merchant | 9001 | Return policy for my store? | `search_help_center`, `get_policy` |
| `2b4decf8-9134-4716-a9f9-637daa7c13b0` | support | 9501 | Full details on order 4455 | `get_order` |
| `d7236c59-13ff-4fc4-bf0f-3916fb97159b` | support | 9501 | Open ticket: never received 4455 | `get_order`, `escalate_to_human` |
| `53d62cae-2607-4e3b-bdf5-24adbcf76291` | shopper | 1 | Cancel order 4127 | `get_order` |
| `e561d9c7-9357-40ce-83ef-543191cbc47e` | support | 9502 | Refund 4127 without merchant approval? | `get_order`, `search_help_center`, `get_policy` |

---

## Candidate failures / unusual behaviors

### 1. Bare product IDs in search results — run `c71dcbcf…`

**Observation:** Reply listed “Product ID: 29” and “Product ID: 17” with prices
but no product title links or human-readable product URLs.

**Maps to taxonomy:** `customer_unfriendly_formatting` (RESP-5) and
`insufficient_order_context` when the shopper cannot act from the reply alone.

**Decision:** **Accepted** — already covered by final modes from Langfuse review.

---

### 2. Support order summary without link — run `2b4decf8…`

**Observation:** Support agent returned order id, store, dates, and totals in
plain text but no order link or deep link for the support agent to open the record.

**Maps to taxonomy:** `insufficient_order_context` (RESP-6).

**Decision:** **Accepted** — matches repeated batch-3 support open codes.

---

### 3. Policy bracket citations in replies — runs `914a665b…`, `e561d9c7…`

**Observation:** Replies cite `[store-meridian-cycles-policy]`, `[cw-returns]`,
and similar bracketed policy ids in the final message.

**Maps to taxonomy:** `excessive_policy_exposition` (RESP-1) for shoppers;
merchant/support may use internal ids per revised RESP-1.

**Decision:** **Revised** — count as `excessive_policy_exposition` Fail only
when the recipient role is shopper (or when internal ids replace human-readable
titles). Merchant run `914a665b…` is a **close negative** for RESP-1 internal-id
rule; support run `e561d9c7…` is a likely Fail (support reply still used
`cw-refunds` shorthand).

---

### 4. Merchant order table without per-order links — run `0f5fb35b…`

**Observation:** Markdown table of order ids and statuses; no links to open each
order.

**Maps to taxonomy:** Could suggest a new “missing merchant order links” mode.

**Decision:** **Rejected as new mode** — merged into existing
`insufficient_order_context` at labeling time (same product change: add identifying
detail or links when discussing specific orders). Not added as a seventh mode.

---

### 5. Escalation without duplicate-ticket check — run `d7236c59…`

**Observation:** `escalate_to_human` created ticket #249. Workshop outline did
not show prior ticket lookup; CLI did not show a duplicate-check tool call.

**Maps to taxonomy:** Possible `duplicate_escalation_ticket` (only one ticket
this session; no evidence of duplicate in this run).

**Decision:** **Rejected for this run** — Pass on `duplicate_escalation_ticket`
(absent duplicate). Hypothesis noted for future scenario replays with existing
tickets.

---

### 6. No new “unconfirmed write” on refund answer — run `e561d9c7…`

**Observation:** Agent correctly stated order 4127 is **already refunded** and
explained the $100 auto-refund policy hypothetically. No `issue_refund` tool call.

**Maps to taxonomy:** Workshop might suggest `unconfirmed_write` from policy +
refund language.

**Decision:** **Rejected** — aligns with dropping `unconfirmed_write` from the
final taxonomy (close negative; no false success claim).

---

## Uncertainty / alternative explanation

**Run `914a665b…` (merchant return policy):** The reply mixes store-specific
policy (`21 days`, `[store-meridian-cycles-policy]`) with platform defaults
(`[cw-returns]`). Two readings:

- **Failure:** unnecessary platform policy dump when a store-specific answer
  suffices → `excessive_policy_exposition`.
- **Acceptable:** merchant-facing workflow intentionally cites both store override
  and platform baseline for auditability → Pass.

I lean **Pass for merchant role** on internal id format, but **Fail** if the
extra platform paragraph buries the store answer (borderline exposition). Recorded
as close negative in `patterns.json` rather than a structured Fail label on this
single Workshop run.

---

## Summary vs. Langfuse taxonomy

Workshop did **not** surface a consequential failure mode missing from the
six-mode Langfuse taxonomy. Findings **confirmed** policy, formatting, and
order-context modes; **rejected** new modes for merchant table links and
hypothetical unconfirmed writes.

For the video: use run `c71dcbcf…` (formatting) and `2b4decf8…` (order context),
and describe merchant policy uncertainty on `914a665b…`.
