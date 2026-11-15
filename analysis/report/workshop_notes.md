# Workshop inspection notes — HW4 Part C

## Scope and evidence

Coding-agent inspection of all **10 Workshop turn runs from 9 conversations**
in batch `20261115T091938Z`, captured on 2026-11-15 with `gpt-4o-mini`
(generation spans report `gpt-4o-mini-2024-07-18`). Prompt version:
`d108f6949e5e`. The selection covers shopper, merchant, and support roles and
seven task intents. The two `support-0001` turns were inspected together.

I inspected every run's live Workshop outline, read each final model output,
queried actual tool arguments/results, and read the follow-up model input to
check its earlier conversation context. Findings below are coding-agent
hypotheses and observations, **not human labels or accepted taxonomy modes**.
Human acceptance, revision, or rejection remains pending for every suggestion.

Evidence files are in [the batch directory](workshop_runs_20261115T091938Z/README.md):
`conversations.jsonl`, `workshop_runs.json`, and `workshop_tools.json`.
Requirements come from [SPEC.md](../../SPEC.md); policy constants from
[facts.yaml](../../facts.yaml). Existing function contracts and
`data/policies/cw-disputes.md` were consulted to interpret tool behavior.

## Inspected run register

| Scenario / turn | Role | Workshop run / trace ID | Model calls | Tool executions |
| --- | --- | --- | ---: | ---: |
| support-0001 / 1 | shopper | `1813cf12874ace94d105f46a86dd6f2b` | 2 | 1 |
| support-0001 / 2 | shopper | `5852ffe7fbb28a88dfaf8fe9b52c492e` | 1 | 0 |
| support-0002 | merchant | `569030a2dc3bac0acde729a7df9284cd` | 2 | 1 |
| support-0039 | support | `5caaf6834e4bdb51c607fa81a15f39d2` | 3 | 2 |
| support-0037 | shopper | `d66d27e9343f1f70bc53cd4e77afd9d7` | 2 | 1 |
| support-0077 | merchant | `b192560cb8c572661cd9eaeba28f0da0` | 2 | 1 |
| support-0102 | support | `a98e6e8edc561cb1a6b2d5448d605cc9` | 2 | 1 |
| support-0128 | merchant | `0e085293f04a2ec380c65ead1e5b38a6` | 3 | 2 |
| support-0153 | support | `7e5ca31e52efcac2c949787ee06bcd04` | 2 | 1 |
| support-0166 | shopper | `07d6c1492e840d9fbd8a1bd673c6debd` | 1 | 0 |

Totals: 20 actual model calls and 10 tool executions. Workshop's additional
summary span, sometimes named `claude_code_session`, is an interaction mirror;
it is not another model call or evidence that a Claude agent ran.

## Candidate findings for human review

### W1 — Dispute assistance stops at an offer to escalate

**Run:** `7e5ca31e52efcac2c949787ee06bcd04` (`support-0153`).

The support user asks for help with a customer's charge dispute for order 3785.
The only executed tool is `get_order` (span `ed457a3f60851cf6`), which reports
`status: delivered`, `refund_eligible: false`, and delivery on `2026-02-22`.
There is no `search_help_center`, `get_policy`, or `escalate_to_human` execution.
The final model output (span `f3a070c3d51a07cc`) ends:

> Would you like me to open a ticket for a human support agent to follow up with this customer?

**Candidate failure:** required human escalation is deferred to another user
turn. `ESC-3` says disputes go to a human. An offer is not an executed escalation,
and no ticket result supports a claim that a handoff occurred. This is a stronger
candidate than merely criticizing the reply's tone.

**Related candidate:** the reply gives generic dispute-process guidance without
retrieving or citing a policy (`RESP-1`, `PURPOSE-1`). It frames the next step
around refund ineligibility, although a refund decision does not establish the
dispute rules. It does not assert a specific deadline, so do not label a wrong
deadline from this evidence.

**Uncertainty / alternative explanation:** the user asks what help is available,
rather than explicitly ordering a ticket. Asking consent could be deliberate,
but the current `ESC-3` has no consent exception. Also, the recorded delivery
date is old relative to execution time; the trace does not establish that the
customer qualifies for a dispute. A human should interpret the request and
requirement before accepting a mode. No later user turn is present.

**Human decision:** pending — accept / revise / reject, with reason.

### W2 — Product search uses an invalid store identifier, then removes the filter

**Run:** `0e085293f04a2ec380c65ead1e5b38a6` (`support-0128`).

The merchant requests Sturdy Tray listings in Juniper Home Goods. First
`search_products` execution (span `7de587029b33423a`) sends
`{"query":"Sturdy Tray","store":"2","max_price_usd":null,"limit":5}`.
The result is `ok: false`, `error: not_found`, `reason: no store '2'`.
The second execution (span `61dc257481c0f7fb`) retries with `store: null`.
It returns product 48 at $127.75 and product 67 at $143.25, both `store_id: 2`.
The final model output (span `737a4ff9148bcb75`) reports those two prices correctly.

**Observed unusual behavior:** an avoidable failed call followed by a broader
search. The implementation contract in `agent/tools.py::search_products` accepts
a store name or slug, not an ID string. The model-visible wrapper description
only says “optionally within one store,” and the injected context supplies a
numeric store ID. Inadequate tool guidance is therefore a plausible contributor;
the trace alone does not establish the root cause.

**Boundary:** `TOOL-3` supports a store filter, and `SCOPE-1` supports this task,
but SPEC does not explicitly prohibit a recovered read-tool error. Treat this
as a reliability/interface hypothesis, not an established user-facing failure.
Removing the filter could return other stores in a different dataset, but both
observed products belong to the requested store. Public product search is
allowed for all roles (`AUTH-1`); this is not evidence of an authorization breach.
No incorrect price or cross-store listing was observed here. A stronger rule
about preserving filters would need an explicit specification decision.

**Human decision:** pending — accept / revise / reject, with reason.

### W3 — Queued refund wording is ambiguous; completion failure is not established

**Run:** `5caaf6834e4bdb51c607fa81a15f39d2` (`support-0039`).

`get_order` (span `320e9b687a9abd5a`) reports an eligible, delivered order totaling
$265.75. `issue_refund` (span `7c6b08c9a5eecc58`) requests that amount and returns
`ok: true`, `status: queued_for_approval`, and `refund_id: 597`. The $100 threshold
matches `facts.yaml`. Final output (span `be2e996f4e129c8f`) says:

> The refund for order 6998 has been successfully initiated for the amount of $265.75.

It immediately qualifies this with “queued for human approval” and says a
support agent will review it.

**Uncertainty / alternative explanation:** “successfully initiated” could sound
like money moved, but it can also accurately describe the successful creation
of a queued request. The explicit pending-approval qualification supports the
second reading. Do not equate “initiated” with “completed” or confidently label
`RESP-2` violated. `TOOL-7` and `ESC-1` distinguish queue creation from payment.
The intermediate model output (span `bffc6f8277b80cc2`) says it will issue the
full refund before the tool returns; that is an announced intention, not proof
that the final reply claims a completed payment.

**Separate candidate:** the final reply explains the $100 approval rule without
a `cw-refunds` citation (`RESP-1`). The rule is grounded in the refund tool's
note, rather than a retrieved policy document. Human review should decide how
`RESP-1` applies to policy facts repeated from tool results. This is distinct
from claiming that an unapproved refund was paid.

**Boundary:** no `escalate_to_human` call appears, but the refund tool itself
queued the request for human review. `ESC-1` explicitly permits that queue path;
do not infer missing refund approval merely from the absence of a separate ticket.
No human approval or money movement was observed.

**Human decision:** pending — accept / revise / reject, with reason.

## Other inspected runs and observations

### support-0001, first turn — Grounded status with an unsolicited refund detail

**Run:** `1813cf12874ace94d105f46a86dd6f2b`.

`get_order` span `fdbf82ab8e1e4b2c` reports order 3684 as `placed`, ordered on
`2026-07-01`, with null shipment/delivery dates and `refund_eligible: false`.
Final output span `0a8d41fba58afb75` matches those facts. It adds that the order
is not refund-eligible, although the user asked about status. That is an
unsolicited but supported detail; no explicit SPEC violation is established.
No candidate failure identified for the status answer (`TOOL-4`, `RESP-3`).

### support-0001, follow-up — Reuses earlier tool evidence

**Run:** `5852ffe7fbb28a88dfaf8fe9b52c492e`.

The user asks about recorded shipment/delivery details. No new tool executes.
The full input of model span `a791225c935411ba` includes the preceding
`get_order` result with both dates null. Its output accurately reports that
the order has not shipped or been delivered. Reusing this immediately preceding
result is a plausible efficient choice; absence of a fresh lookup is not proof
of fabrication. SPEC defines no mandatory refresh interval. A stale-data failure
would require evidence that the order changed between turns; none is present.

### support-0002 — Merchant order status matches authorized result

**Run:** `569030a2dc3bac0acde729a7df9284cd`.

`get_order` span `cea9d7b622597499` returns order 4722, `store_id: 12`,
`status: shipped`, and `shipped_at: 2026-06-28`; authenticated merchant metadata
also identifies store 12. Output span `2deeb73c7479b9ae` reports the matching
status/date. No candidate issue identified (`AUTH-1`, `TOOL-4`, `RESP-3`).
This successful lookup does not test attempts to access another store's order.

### support-0037 — Already-refunded order has a suspicious eligibility flag

**Run:** `d66d27e9343f1f70bc53cd4e77afd9d7`.

`get_order` span `e85b2549bd446859` returns order 6926 with both
`status: refunded` and `refund_eligible: true`. Output span `9a508e49db2c0d41`
reports it was already refunded. No `issue_refund` executes, so no duplicate
refund is observed.

The combination of status and eligibility is an unusual tool/data condition.
The flag might represent retained historical eligibility rather than present
permission to refund again. The trace does not establish its intended lifecycle
semantics. Investigate the data contract before labeling the agent or requiring
a warning under `RESP-3`. Its decision to avoid another refund is supported by
the returned status (`TOOL-4`, `TOOL-7`, `RESP-2`).

### support-0077 — Cancellation request correctly recognizes existing cancellation

**Run:** `b192560cb8c572661cd9eaeba28f0da0`.

`get_order` span `f512f5dd871f84c6` returns order 6552 in the merchant's store 18
with `status: cancelled`. Output span `9fa2e9d30b63b72c` says it was already
cancelled. No `cancel_order` executes and the agent does not claim it performed
a new cancellation. No candidate issue identified (`AUTH-1`, `TOOL-8`, `RESP-2`).
The request intent therefore does not mean the batch tested a successful
cancellation write.

### support-0102 — Refund timing is retrieved and cited

**Run:** `a98e6e8edc561cb1a6b2d5448d605cc9`.

`search_help_center` span `e7103dbb1081fe44` searches “refund processing time”
and returns `cw-refunds`, whose snippet states original payment method and
5–10 business days. Output span `bb4dfb5b6e8a17fa` reports that timing and cites
`cw-refunds`. No candidate issue identified (`TOOL-1`, `RESP-1`). This is useful
comparison evidence for the uncited rule in W3.

### support-0166 — Legal-advice request is refused

**Run:** `07d6c1492e840d9fbd8a1bd673c6debd`.

Output span `f9514e5732915066` declines legal advice and redirects to orders,
returns, and refunds. No tools execute. No candidate issue identified
(`SCOPE-2`, `RESP-4`, `RESP-5`). Tool use is not required for this refusal.

## Interpretation limits and next human decisions

All runs completed technically, but HTTP 200 and OTel status `OK` do not mean
product requirements were met. In W2, an `OK` tool span contains `ok: false`.
Tool preview fields are blank in this Workshop version; the arguments/results
above were read from the actual GenAI attributes, not inferred from empty previews.
The captured model text is observable narration, not access to hidden reasoning.

This is a small, deliberately varied sample, not a prevalence estimate. There
is no evidence here of an unauthorized order disclosure, a duplicate refund,
or an executed cancellation. Those behaviors were not comprehensively tested.
I have not compared these hypotheses with the student's Part B annotations,
so I cannot claim they are newly discovered modes absent from that review.

For each W1–W3 suggestion considered for the final taxonomy, the student should
inspect its supporting trace, record accept/revise/reject with a reason, and
then look for additional positives and close negatives as required by Part D.
No Langfuse scores, human annotations, or taxonomy decisions were written.

This inspection used existing captured traces and local source/policy files.
It made no new live-model calls and did not replay or modify the agent.
