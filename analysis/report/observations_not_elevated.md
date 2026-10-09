# Observations recorded but not elevated to failure modes

## Repetition of facts already stated

**Notes:** 6, across support-0062, support-0067, support-0108, support-0028.
Examples: the order number restated after it was already given; the delivery timeline
printed twice in one reply; "not refund-eligible" said in two different ways.

**Why not a mode.** Split from `irrelevant_policy_detail` on 2026-09-18. The test from the
handout is whether one product change would correct both behaviours. Stopping the agent from
quoting a rule that does not govern the case is a relevance problem. Stopping it repeating
a fact it already gave is an output-structure problem. Different fixes, so they cannot share
a mode.

Of the two, quoting an inapplicable rule is the one that misleads a customer: a shopper told
about a 30-day window when their store allows 14 may act on the wrong number. Repetition is
untidy but not misleading. With the taxonomy at its limit of 5 to 8 modes, the misleading one
was elevated and this one was not.

**Kept here** so the decision, and the notes behind it, remain inspectable.


## asserts_records_against_the_user

**Notes:** 4, across support-0001, support-0006, support-0025. The agent states a system
record as settled fact when the user reports the opposite, e.g. insisting an order was
delivered when the shopper says it never arrived.

**Why not a final mode.** Four notes is thin, and the observations overlap
`detail_level_ignores_the_ask`: in each case the reply is too curt to acknowledge the
conflict rather than actively disputing the user. With the taxonomy at its limit, and with
Homework 5 needing 30 Fail labels per mode, a four-instance mode would have to be topped up
with synthetic scenarios before it could be validated. Worth revisiting if the remaining
batches produce more.

## defers_what_was_asked

**Notes:** 4, across support-0188, support-0039, support-0241. The agent offers to retrieve
something the user explicitly asked for instead of retrieving it.

**Why not a final mode.** The boundary is real and well drawn -- support-0142 offers
something adjacent to the request and is correct, support-0188 offers the thing itself and
is not -- but four instances cannot support an LLM judge, which is what deciding "was this
asked for?" requires. `abandons_mid_task` was elevated in its place: a deterministic check
and a distinct fix. The two are genuinely different failures and this was a capacity
decision, not a merge.

**Revisited 2026-09-22.** The original reasoning cited `abandons_mid_task` at 21 instances,
which was a looser search than that mode's own definition allowed. Under the revised
boundary it has 7 confirmed traces, 4 of them inside the reviewed sample -- closer to this
observation's 4 than the original comparison suggested. The decision still stands, because
capacity was not the only reason: `abandons_mid_task` has a deterministic check and this
does not, and the taxonomy is at the handout's limit of 5 to 8 modes. But the two are now
near neighbours in size, and if Homework 5 generates scenarios targeting either, this is
the first observation that should be reconsidered for promotion.
