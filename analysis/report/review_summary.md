# Review summary (HW4 Part E)

## Sample size and composition

107 traces sampled, 5 excluded (see below), **102 valid traces in the final
review set** — all individually open-coded (Part B), cross-checked with
Raindrop Workshop (Part C), and labeled present/absent against every final
mode (Part E).

| batch | method | count |
| --- | --- | --- |
| 1 | 15 uniform random + 15 cluster representatives (shape features: turn count, tool-call count, distinct tools, retrieval, tokens) | 30 |
| 2 | dimension slice on `intent`, chosen before looking at outcomes, weighted toward previously-uncovered values (`cancellation`, `dispute`) | 30 |
| 3 | depth search: every scenario tagged with a seeded `data_quality_case_id`, to check `ignores_data_quality_anomaly` coverage | 25 |
| 4 | final uniform random check, reviewed last, for taxonomy saturation | 15 |
| supplementary | live-chat follow-up investigations (3) + Workshop/close-negative re-run searches (4) | 7 |

**Excluded (5)**: `support-0201` through `support-0205` (`dq-product-missing-title`).
A generator bug leaked an internal placeholder string ("that item (empty
title in the catalog)") directly into the simulated customer's message,
producing an input no real customer would ever send. Once the input itself
is garbled, the agent's response can't be fairly judged against it, so these
were excluded rather than scored pass/fail. See `notes/hw4-notes.md`.

## Mode counts and sample fractions

9 final modes. Counts and fractions are **sample fractions**, not prevalence
estimates — batches 2 and 3 deliberately oversample specific dimensions
(intent values, data-quality cases), so these numbers describe this
constructed sample, not the overall trace population. Homework 5's complete
Module 1 trace store is needed for an actual prevalence estimate.

| mode | present | / 102 | fraction |
| --- | --- | --- | --- |
| `ignores_data_quality_anomaly` | 21 | 102 | 20.6% |
| `leaks_internal_terminology` | 14 | 102 | 13.7% |
| `no_clarifying_question` | 8 | 102 | 7.8% |
| `asks_for_unusable_information` | 7 | 102 | 6.9% |
| `escalation_handling_failure` | 5 | 102 | 4.9% |
| `inefficient_tool_use` | 5 | 102 | 4.9% |
| `missing_policy_citation` | 3 | 102 | 2.9% |
| `fails_to_refuse_out_of_scope` | 3 | 102 | 2.9% |
| `continues_past_refusal` | 1 | 102 | 1.0% |

Every mode's judgment is written as a Langfuse score (name = mode, value =
0/1) against its trace, and mirrored in `analysis/state/labels/<mode>.jsonl`.
3 of 102 traces (the live-chat-exported ones, prefixed `live-`) don't carry a
native Langfuse trace id, so their scores exist only in the local label
files, not in Langfuse — a known, documented limitation of the live-chat
tool built for this homework, not a gap in the labeling itself.

## New modes in the final 15 (batch 4)

Exactly **1** new consequential mode appeared in the final uniformly-sampled
batch: `support-0222` (a merchant permission-denied lookup where the agent
offered to "check access" on an order it could never legitimately access)
surfaced what became `inappropriate_escalation_channel`, later merged into
`escalation_handling_failure`. The other 14 traces either matched existing
modes (2: `missing_policy_citation`, `leaks_internal_terminology`) or showed
no failure (10) — the vast majority "no new failure," well under the
handout's "several new modes → review another batch" threshold, so Part B
was considered complete after this batch.

## One taxonomy revision

`ignores_data_quality_anomaly` was tightened mid-review. Its original
definition allowed "hedging or escalating" as equally acceptable responses
to a data-quality anomaly. Investigating order 8002 (`dq-order-missing-delivery-date`)
via live re-runs showed the agent hedging (flagging the missing date) in
3 of 5 fresh runs without ever calling `escalate_to_human` — which read as
a plausible close negative under the original wording, but 0 of those 5
runs ever escalated, so treating hedging alone as sufficient would have
under-counted a mode that's actually 100% reliable for this case. The
definition was revised to require escalation specifically; hedging in the
reply text alone no longer counts as passing. This changed several
previously-tentative close-negative candidates back into confirming
positives before anything was committed.

## Rejected search suggestions

`analysis/state/suggestions.json` holds 5 candidates from targeted per-mode
scans during Part E, all rejected with reasoning kept alongside (e.g. a
"not refund-eligible" mention flagged for `missing_policy_citation` was
rejected because it's a plain field lookup, not a claim derived from a
policy document -- RESP-1 doesn't cover raw eligibility flags). The review
interface's own accept/reject UI discards a rejected suggestion with no
record, so these were persisted directly to satisfy the "at least one
rejected suggestion" requirement honestly rather than losing the reasoning.

## Planned agent improvements (not yet implemented)

Two changes identified during HW4/HW5 review, deliberately deferred rather
than implemented now (mid-way through HW5 label collection against the
current agent behavior -- changing it now would shift what's being labeled).

1. **Add a store lookup by numeric `store_id`.** `get_store_info` and
   `search_products`'s `store` filter both resolve only by name/slug
   (`db.get_store_by_name`) -- there is no tool that accepts a bare
   `store_id`. Observed twice: the `support-0151` live-chat investigation
   and a `hw5-ncq` trace both show the agent guessing `get_store_info(store="1")`,
   getting `not_found`, then retrying with the store name it already had
   from a different tool result. Either add a new tool (e.g.
   `get_store_by_id`) or extend `get_store_info`'s `store` parameter to
   accept a numeric id as well as a name/slug -- the smaller, more contained
   change.
2. **Add a system-prompt instruction to confirm before acting on any
   request**, not just escalations. Motivated by the `no_clarifying_question`
   /`escalation_handling_failure` findings throughout this review: the
   agent's willingness to ask-first varies by case (e.g. `support-0160`'s
   family reliably asks before escalating; several `no_clarifying_question`
   positives act on an assumption instead). A general confirm-before-acting
   rule would unify this rather than relying on per-case judgment.

Both require an update to `SPEC.md`/the system prompt when implemented,
with these findings as the motivating annotations.

## Other notes

- No `SPEC.md` revisions were made during this homework — all findings were
  observational (taxonomy/labeling), not implementation changes.
- Two modes (`inefficient_tool_use`, `no_clarifying_question`) have no
  backing `SPEC.md` requirement id — they're human-judgment quality bars the
  review surfaced, not violations of a written rule. See `patterns.json`'s
  `requirement_source` field per mode.
- Full mode definitions, boundaries, evaluator types, requirement sources,
  positive examples, and close negatives live in `analysis/state/patterns.json`.
