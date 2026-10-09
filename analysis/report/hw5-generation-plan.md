# Homework 5 — plan for generating additional Fail labels

**Mode:** `irrelevant_policy_detail`
**Position:** 10 Fail / 116 Pass. The handout needs 30 of each, so Pass is done and Fail
is 20 short.

## Why generation is needed

The existing 261 conversations cannot supply 30 Fails. A shape-targeted search over the
149 unlabelled traces produced 24 candidates, of which the reviewer confirmed 4 — a 17%
hit rate on a deliberately enriched sample. The remaining unlabelled pool would yield
roughly 7 more at the observed base rate, and the targeted search has already skimmed the
likely ones.

The reason is structural rather than behavioural. **Only 4 of 20 stores override the
return window**, so shape 1 can only occur on orders from Juniper Home Goods (14 days),
Northwind Books (45), Meridian Cycles (21) and Saltbox Pantry (7). Homework 3 spread 250
scenarios evenly across all 20 stores, so the opportunity for this failure was rare by
construction. Generation concentrates the opportunity.

## What the labelled data says about when this failure happens

Measured over 126 labelled conversations.

| user style | Fail rate |
|---|---|
| `frustrated_impatient` | **3/4 — 75%** |
| `typo_heavy` | 3/13 — 23% |
| `terse_fragmentary` | 2/18 — 11% |
| `neutral_conversational` | 2/51 — 4% |
| `requests_short_plain_answer` | 0/13 |
| `operational_shorthand` | 0/16 |
| `repetitive_pressuring` | 0/6 |
| `confused_rambling` | 0/5 |

| situation | Fail rate |
|---|---|
| `refund` + `order_in_window` | 4/23 — 17% |
| `refund` + `order_past_window` | 3/18 — 17% |
| `cancellation` + `order_shipped` | 1/6 — 17% |
| `refund` + `order_above_threshold` | 1/13 — 8% |
| `product_search`, `policy_question`, `store_policy_question` | 0 across 29 |

A frustrated user makes this failure roughly twenty times more likely than a neutral one.
The plausible mechanism is that the agent becomes defensive under pressure and
over-justifies, stacking policy behind an answer the user is pushing against. **Four cases
is a thin base**, so this is a lead rather than an established fact, and the design below
tests it rather than assuming it.

All 10 confirmed Fails are `shopper`. No merchant or support conversation has produced one.

## Design

**60 scenarios in two waves**, so the second wave can be sized from the first wave's
measured rate rather than a guess. This is the pilot pattern from Homework 3, which caught
a bad batch before it cost hours.

### Allocation by shape

Each shape needs a situation the failure can actually occur in. Order counts are live
counts from the current database.

| shape | situation to build | orders available | scenarios |
|---|---|---|---|
| 1, default as operative | delivered order from an override store, still inside that store's window | 67 | 16 |
| 2, threshold, no path taken | delivered order past every window **and** over $100, so the refund must be declined | 6,034 | 14 |
| 3, fee not opted into | delivered order from one of the 18 stores with no restocking opt-in, inside the 30-day window | 457 | 16 |
| 4, recited after settled | eligible order **under** $100, so the refund completes inside the conversation | 137 | 14 |

### Allocation by user style

Weighted toward the styles that produce failures, with a deliberate control group.

| style | scenarios | why |
|---|---|---|
| `frustrated_impatient` | 24 | the strongest measured lever |
| `typo_heavy` | 18 | second strongest |
| `terse_fragmentary` | 9 | moderate |
| `neutral_conversational` | 9 | **control** — see below |

**The control group is not optional.** If every generated Fail comes from a frustrated
user, the judge can reach the right verdict by reading tone instead of policy, and it will
score well on this data and fail on anything else. The neutral scenarios exist so the
training and development sets contain Fails with calm users and Passes with frustrated
ones, which denies the judge that shortcut. If the neutral group produces no Fails at all,
that is worth knowing before the judge prompt is written.

### Expected yield

Applying the measured rates to the wave-1 mix:

- if `frustrated_impatient` holds near 75%: roughly 23 Fails from 60 scenarios
- if it regresses to 40%, which a base of four should make us expect: roughly 15

Either reaches or approaches 30 total. Wave 1 of 24 scenarios settles which.

## Realism constraint

Homework 3's scenario skill warns against scenarios written backwards from a desired
failure. The risk here is real: a message engineered to trip the agent stops resembling a
customer, and a judge trained on those examples learns a caricature.

The rule for writing these: **set up the situation, not the failure.** The scenario picks a
store, an order and a mood. It does not hint at a policy, quote a window, or ask a question
shaped to invite a recital. A frustrated shopper asking "so can I send this back or not"
about a Saltbox order is realistic; one asking "what does your platform default return
window say" is not, and would not test anything.

Each generated message will be checked against the same critic pass used in Homework 3:
no invented order numbers, prices or product names; no user quoting internal policy ids;
no followup that assumes a particular agent reply.

## Honesty about what this sample is

These scenarios are deliberately enriched for failure. That is sanctioned — the
`validate-evaluator` skill says to *"use balanced splits even if real-world prevalence is
skewed"* — but it has consequences that must be stated wherever the numbers appear:

- The Fail fraction in this label set is **not** a prevalence estimate, and is further from
  one than the Homework 4 sample fractions were.
- TPR and TNR measured on this set describe the judge's agreement with human labels **on
  this distribution**, not its behaviour on live traffic.
- Generated scenarios are tagged `hw5-gen-*` and kept distinguishable from the Homework 3
  set, so any later analysis can separate them.

## Steps

1. Select orders per shape from the live database, recording the facts each expected
   outcome depends on: store, override window, total, delivery date, restocking opt-in.
2. Write the tuples, then the user messages, keeping generation of the message separate
   from the expected outcome so the message cannot be written to fit the answer.
3. Critic pass, then `python -m scenarios.validate` on the new file.
4. **Review point:** the reviewer reads a sample before any model call, as in Homework 3.
5. Run wave 1 (24 scenarios) through the Cartwheel endpoint. At roughly 90 seconds per
   scenario this is about 35 minutes.
6. Measure the actual Fail rate by style and shape. Size wave 2 from it.
7. Label every generated conversation by hand in the review interface. A generated
   scenario is not a label; the reviewer decides each one, same as every other trace.

## What could go wrong, and the answer

**The frustration effect does not reproduce.** Four cases is thin, and the effect may be
noise. Wave 1 reveals this after 35 minutes rather than two hours, and wave 2 can shift
weight to `typo_heavy` and the situational levers instead.

**The agent has improved on shape 1.** Seven of the reviewer's rejections in the last round
were variants of "cites the store's policy as an override" — the agent is often correct
here. Shape 1 may produce few Fails regardless of volume. If wave 1 confirms that, shapes 3
and 4 absorb the reallocation.

**The judge learns tone instead of policy.** Addressed by the control group above, and
checkable before the prompt is written: if every Fail is frustrated and every Pass is calm,
the split is unusable no matter how many labels it contains.
