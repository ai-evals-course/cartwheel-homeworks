# HW4 review summary

## Overview

I reviewed **100 distinct Cartwheel support traces** from the live Langfuse project
(Module 1 HW3 runs; ~662 scenario-linked traces in the store). For each trace I
wrote an open code (first failure or “no failure observed”), grouped observations
into a **6-mode binary taxonomy**, and applied every final mode to every trace
(600 Pass/Fail judgments synced to Langfuse and `analysis/state/labels/`).

Review interface: `analysis/review_app/` (port 8021). Comparison notes:
`analysis/report/interface_comparison.md`. Workshop inspection (Part C):
`analysis/report/workshop_notes.md`.

---

## Reviewed sample composition

All five required batches; **no trace counted in more than one batch**
(`analysis/state/sample_manifest.json`).

| Batch | Strategy | Traces | Purpose |
|-------|----------|--------|---------|
| 1 | Uniform random | 15 | Baseline coverage |
| 2 | Cluster representatives | 15 | Feature diversity (tool count, tokens, role) |
| 3 | Role stratified | 30 | 10 shopper / 10 merchant / 10 support |
| 4 | Depth search | 25 | Neighbors of candidate modes + close negatives |
| 5 | Uniform random (stability) | 15 | Check for new modes after taxonomy draft |
| **Total** | | **100** | |

**Role mix in the full 100-trace set:** ~70 shopper, ~16 merchant, ~14 support
(inferred from trace metadata).

**Open coding:** 100 open codes in `analysis/state/annotations.json`; ~20 traces
with no first failure observed (~80 with a noted failure). Batch 4 (depth) had
the lowest clean rate (3/25), as expected when searching near known failure
language.

---

## Final failure taxonomy

Six final modes in `analysis/state/patterns.json` (status: `final`). Five
candidate modes were rejected or merged (documented in `rejected_modes`):

| Rejected / merged | Reason |
|-------------------|--------|
| `unconfirmed_write` | Single open-code instance; overlaps RESP-2 and escalation modes |
| `premature_refund_offer` | Single positive; depth neighbors were close negatives |
| `insufficient_refusal_explanation` | Single example; boundary unclear vs policy / next-step modes |
| `inefficient_tool_strategy` | Single example; no confirmation in depth search |
| `invalid_product_in_results` | Merged into `customer_unfriendly_formatting` |

### Final modes (definitions abbreviated)

1. **`excessive_policy_exposition`** (RESP-1) — Internal policy ids, policy dumps, or wrong-store platform policy in shopper replies.
2. **`insufficient_order_context`** (RESP-6) — Order/product discussion without link or enough identifying detail.
3. **`customer_unfriendly_formatting`** (RESP-5) — Machine-oriented formatting, bare ids, invalid product presentation.
4. **`duplicate_escalation_ticket`** (ESC-3) — New ticket without checking for an existing one.
5. **`permission_mechanism_overshare`** (RESP-4) — Permission denial exposes store ids or auth internals.
6. **`abrupt_no_next_step`** (ESC-3) — Reply ends without ask, escalate offer, or actionable guidance when needed.

---

## SPEC revisions

Two requirements were revised after review; both are motivated by repeated open
codes before axial coding finalized.

**RESP-1 (revised after batch 1).** Original wording required citing a policy
*identifier*, which conflicted with shopper-facing internal ids like `cw-returns`.
Motivating observation: open code on trace `db615d177ce3d84057cdbe4d08198b45`
(annotation `oc1789602313783`) — policy id in a shopper reply. Revision:
shoppers get human-readable policy titles; merchants/support may still see
internal ids when useful.

**RESP-6 (added after batch 3).** Missing order/product links appeared across
roles, especially support. Motivating observation: open code on trace
`00ea96a6b16b657950bb80907a08e2e1` (annotation `oc1789660561215`) — “should
provide link to order or product so support can do more research.”
`insufficient_order_context` now cites RESP-6.

---

## Taxonomy revision

**Primary revision — RESP-1 and `excessive_policy_exposition`.** After batch 1,
open codes repeatedly cited internal policy ids (`cw-returns`) and policy dumps
in shopper replies. I revised RESP-1 so shopper-facing replies must use
human-readable policy titles, then tightened the mode boundary to Fail on
internal ids, operational ids, wrong-store platform policy, and unnecessary policy
body text. This was the main taxonomy-shaping change; later batches mostly
confirmed or refined the same mode.

**Secondary merge — `invalid_product_in_results` → `customer_unfriendly_formatting`.**
Batch-3 codes noted bare product ids and invalid listings (e.g. trace
`009f30cb85e4978239747e0880792143`). I merged invalid/misleading product
presentation into formatting rather than adding a seventh mode.

---

## Rejected depth-search suggestion

During batch 4 I retrieved semantic neighbors of **`premature_refund_offer`**
(3 traces). Two returned traces were reviewed as **close negatives**:

| Trace | Search signal | Open-code outcome |
|-------|---------------|-------------------|
| `0500ad44a6eb6ec1ed8bf4b7cc9418b0` | `premature_refund_offer` neighbor | “no issue” |
| `068c89e996aedc0b6795a496b413a8f2` | `premature_refund_offer` neighbor | “no issue” |

**Boundary:** The agent offered or discussed refunds only after order context was
established or the user explicitly requested refund help — not “refund before
confirming the right order.” I rejected adding `premature_refund_offer` as a
final mode. Recorded in `analysis/state/suggestions.json`.

---

## Structured labeling (Part E)

**600 judgments** (100 traces × 6 modes) in `analysis/state/labels/<mode>.jsonl`,
synced to Langfuse scores.

**Sample fractions** (Fail count / 100 — descriptive only, not population
prevalence):

| Mode | Fail | Pass | Sample fraction (Fail) |
|------|------|------|------------------------|
| `excessive_policy_exposition` | 30 | 70 | **30.0%** |
| `insufficient_order_context` | 28 | 72 | **28.0%** |
| `customer_unfriendly_formatting` | 7 | 93 | **7.0%** |
| `duplicate_escalation_ticket` | 9 | 91 | **9.0%** |
| `permission_mechanism_overshare` | 2 | 98 | **2.0%** |
| `abrupt_no_next_step` | 4 | 96 | **4.0%** |

**Trace-level summary:** 33 traces Pass on all six modes; 67 traces Fail on at
least one mode; max 3 modes on a single trace. Most common co-occurrence:
`excessive_policy_exposition` + `insufficient_order_context` (3 traces).

**Homework 5:** Only `excessive_policy_exposition` meets the ≥30 Pass and ≥30
Fail threshold for LLM judge development. The other five modes need targeted
labeling in HW5 (four have fewer than 15 Fails in this sample).

---

## Taxonomy stability (final 15 traces)

Batch 5 (stability random sample): **0 new consequential modes.**

Two traces raised “should have offered to open a ticket in the first response”
(`f10e49d7…`, `312eb34d…`); both fit existing **`abrupt_no_next_step`** (delayed
escalation), not a new category. Remaining batch-5 codes mapped to existing
policy, formatting, or order-context modes, or were clean.

---

## Workshop (Part C)

Eight fresh CLI runs inspected in Raindrop Workshop (`workshop_notes.md`).
Workshop did **not** surface a consequential mode missing from the Langfuse
taxonomy; it confirmed formatting, order-context, and policy-exposition
patterns. Merchant policy citations on run `914a665b…` were borderline under
revised RESP-1 (internal ids allowed for merchants); treated as close negative
rather than a new mode. See `analysis/report/workshop_notes.md` for run ids and
accept/revise/reject decisions.

---

## Interface note (for video)

One design change after inspecting traces: **session grouping** — Langfuse stores
one trace per turn; the review app merges turns by `cartwheel.session_id` (with
backfill for Module 1 traces) so tool calls from earlier turns stay visible.
See `interface_comparison.md`.
