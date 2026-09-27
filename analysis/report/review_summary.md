# Homework 4 review summary

Error analysis over the Homework 3 trace store: 261 conversations, 250 scenarios, one
agent, one model. 102 conversations were read and annotated by hand.

All labels and decisions in this report are the reviewer's. Where a code rule produced a
judgment, the rule is stated and its agreement with the reviewer's own coding is reported.

## Size and composition of the reviewed sample

**102 of 261 conversations (39%).** 188 free-text annotations, each attached to a quoted
span of a specific reply. 8 final failure modes. 816 trace-mode judgments in Part E.

The sample was not drawn uniformly. It was built in four batches, each with a different
purpose, and the composition below reflects those purposes rather than the population:

| batch | n | how it was drawn |
|---|---|---|
| 1 | 30 | stratified on `record_state`, quotas fixed before any outcome was examined |
| 2 | 30 | uniformly at random from all 261 |
| 3 | 27 | depth searches: traces matching a candidate mode's signature, plus close negatives |
| 4 | 19 | uniformly at random from conversations never sampled, reviewed, or returned by a search |

Composition of the 102:

| dimension | breakdown |
|---|---|
| role | shopper 86, merchant 9, support 7 |
| intent | refund 38, order_status 24, product_search 14, cancellation 12, policy_question 6, store_policy_question 5, account_change 3 |
| difficulty | well_specified 71, boundary 16, missing_information 12, ambiguous 3 |
| group | coverage 73, challenge 29 |
| access relationship | own_record 86, other_in_scope 11, other_out_of_scope 5 |
| record state | order_past_window 31, order_in_window 21, damaged_record 12, none 10, order_above_threshold 7, order_placed 7, order_shipped 5, store_policy_page 5, product 4 |
| user style | neutral_conversational 42, requests_short_plain_answer 13, operational_shorthand 12, typo_heavy 11, terse_fragmentary 10, repetitive_pressuring 6, confused_rambling 5, frustrated_impatient 3 |
| structure | 15 multi-turn, 5 permission-denied, 12 damaged-record |

Batch 3 is the reason the fractions below are not prevalence: a depth search finds traces
because they already look like the mode, so it inflates that mode's share of the sample by
construction. Homework 5 estimates prevalence from the full trace store.

## Final taxonomy and sample fractions

Every mode was applied to every one of the 102 traces, present or absent, with no judgment
left open. Fractions are **within the reviewed sample**, not prevalence estimates.

| mode | present | absent | sample fraction | decided by | requirement |
|---|---|---|---|---|---|
| `cites_policy_by_internal_id` | 50 | 52 | 49.0% | code rule | RESP-1 (revised) |
| `tool_call_malformed` | 17 | 85 | 16.7% | code rule | TOOL-3 |
| `contradicts_eligibility_flag` | 15 | 87 | 14.7% | code rule, 1 by hand | RESP-2, RESP-3 |
| `irrelevant_policy_detail` | 9 | 93 | 8.8% | human reading | RESP-5 |
| `unwarranted_offer` | 10 | 92 | 9.8% | human reading | RESP-3, ESC-4 |
| `detail_level_ignores_the_ask` | 5 | 97 | 4.9% | human reading | RESP-3 |
| `abandons_mid_task` | 4 | 98 | 3.9% | code rule | RESP-3 |
| `missing_escalation` | 3 | 99 | 2.9% | code rule, 5 by hand | ESC-2, ESC-3, ESC-4 |

Five modes have a deterministic check. Each rule was validated against the reviewer's own
coding before being trusted, and all five finished in complete agreement with it. The other
three turn on whether a rule governs the case, whether an offer applies, and whether the
detail fits the ask; no rule decides those, so each label is a human reading of a
shortlisted candidate.

Three modes have confirmed positives outside the reviewed 102, found by search across all
261 and recorded as supporting evidence rather than labelled: `abandons_mid_task`
(support-0016, 0052, 0060) and `detail_level_ignores_the_ask` (support-0110, 0121).

## New modes in the final 15 traces

**Zero.**

Batch 4 was drawn for exactly this test: 15 conversations never sampled, never reviewed,
and never returned by any depth search, so nothing about them was known in advance.

Of the 15, **8 were clean** and **7 contained a failure**. Every one of those seven mapped
to a mode that already existed:

- `cites_policy_by_internal_id` — support-0033, 0059, 0088, 0133
- `tool_call_malformed` — support-0008, 0088, 0198
- `abandons_mid_task` — support-0022

No observation in the batch required a new category, and no observation was set aside as
unclassifiable. The handout's instruction to review a further batch if several new modes
appear did not trigger.

Two of the seven — support-0008 and support-0059 — had been marked "no failure observed"
on first reading and were caught by a code rule: a rejected `search_products` call in one,
a printed `cw-refunds` identifier in the other. On re-reading, the reviewer confirmed both
as oversights rather than a difference of interpretation. They are the same two issues
already noted many times over elsewhere in the sample, and they were missed late in a long
review. Both are labelled present. They are the clearest argument in this analysis for
writing deterministic rules where a mode admits one: a rule does not get tired at the
fortieth conversation.

One caveat worth stating plainly: a batch that produces no new modes shows the taxonomy is
stable **against the kinds of failure this dataset contains**. All 261 conversations came
from one agent, one model, and one seeded world. Stability here is not evidence that the
taxonomy would hold against a different agent.

## One taxonomy revision

Three revisions were made after the taxonomy first stabilised. The most consequential:

### `abandons_mid_task` and `contradicts_eligibility_flag` were sorting on the wrong thing

Both modes concern refund conversations, so during axial coding traces were sorted by
**what the conversation was about** rather than **what went wrong**. The error only became
visible when a code rule was written for each definition and checked against the existing
coding: the rules disagreed with the human labels in eight places, and every disagreement
was a misfiled trace rather than a bad rule.

`abandons_mid_task` is defined as the reply announcing a step and the turn ending with
nothing delivered. Of its ten example traces, three matched. Five were conditional offers
("let me know and I can open a ticket") that do complete the turn. One (support-0039) was
a missing escalation and one (support-0083) an unwarranted offer.

The leak ran both ways. Three traces filed under `contradicts_eligibility_flag` —
support-0068, 0217, 0241 — end mid-task without stating any conclusion. That mode requires
the reply to reach *the opposite* conclusion to the eligibility flag, and no conclusion is
not the opposite one. support-0022 was listed as a *close negative* for
`abandons_mid_task` while ending "Now I need to check Northwind Books' specific return
window" and stopping.

**The revision:** sort by what went wrong. One question decides it — *did the user get an
answer?* If no, `abandons_mid_task`, whatever the topic. If yes, and the answer is the
opposite of the flag, `contradicts_eligibility_flag`. Four traces moved in, two moved out
to their correct modes, five were dropped as correct behaviour.

**Effect:** both detectors went from disagreeing with the human coding to agreeing with it
completely. The revision is recorded in `analysis/state/patterns.json` under each mode's
`revision` key.

### Two further revisions, recorded in `patterns.json`

`irrelevant_policy_detail` was narrowed. Naming a store's override as the governing rule
while mentioning the 30-day platform default as contrast is **correct** behaviour — it
explains why the number differs from what the shopper expected. Eight traces accepted
under the older, looser reading were reversed. What remains is the default presented as if
it governs, a threshold that decided nothing, a fee the store never opted into, or policy
recited after the matter was already settled.

`detail_level_ignores_the_ask` was rewritten around a rejection pattern. Five candidates
were shortlisted on the heuristic "terse user, long reply" and the reviewer rejected all
five, accepting only the candidate where a decision was stated without its basis. Length
is therefore not the signal; omitting the deciding rule, the window, or the dates is. This
matters for Homework 5, because a length-based judge was the obvious build and would have
been the wrong one.

Every reversal keeps a `revised_from` field. No human note was rewritten or deleted; the
ten records removed during reconciliation were duplicates the interface created when a
suggestion was accepted, all carrying `from_suggestion: true`.

## Comparison with the AgentDebug taxonomy

AgentDebug names 17 error types across five modules. Five of the eight modes here map onto
it: `contradicts_eligibility_flag` to `outcome_misinterpretation`, `abandons_mid_task` to
`progress_misjudge`, `missing_escalation` to `constraint_ignorance`, `tool_call_malformed`
to `parameter_error`, `unwarranted_offer` to `misalignment`.

Two AgentDebug types were tested against this data and found absent:

- **`hallucination`** — 38 damaged-record conversations exist to bait exactly this. The
  agent invented no product name, price, or delivery date in any of them, and no annotation
  uses the word.
- **`memory_retrieval_failure`** — in 34 multi-turn conversations the agent never re-asks
  for something established in an earlier turn.

**`inefficient_plan`** looked like a match for the repetition observations in
`observations_not_elevated.md`, but it is not: no reviewed conversation calls the same tool
three or more times. Those notes are about the agent *saying* the same thing twice, not
doing the same thing twice. The published name did not rescue the observation, so no mode
was added.

No mode was added from this comparison, which is the correct outcome under the rule that a
published category only becomes a mode when the reviewer's own traces support it.

The comparison was more useful in reverse. `cites_policy_by_internal_id`,
`irrelevant_policy_detail` and `detail_level_ignores_the_ask` have no AgentDebug
counterpart at all. AgentDebug was built on ALFWorld, GAIA and WebShop, where an agent acts
on an environment and no person reads its prose. Cartwheel's output *is* prose sent to a
customer, and those three modes all describe a conversation where the task succeeded and
the message was still wrong — an axis the published taxonomy has no room for.

## Specification revision

`analysis/report/spec_revisions.md` proposes one change to `SPEC.md`.

**RESP-1** currently reads *"Cite the policy identifier for every claim derived from a
policy document."* The agent complies literally, printing `[cw-returns]` and
`[store-second-stitch-apparel-policy]` into customer replies.

**Motivating annotation:** support-0028 —

> "Dont include internal label/function, just say per internal policy"

It is the note that names both halves of the fix: stop printing the identifier, and say
the thing in words instead. Eighteen further annotations record the same behaviour —
19 in total across 14 conversations (support-0015, 0019, 0025, 0028, 0033, 0041, 0062,
0063, 0067, 0070, 0074, 0079, 0088, 0133) — including two that sharpen it to a redundancy
argument rather than a secrecy one:

> support-0067: "Don't need to add label if you've already cited the return policy
> verbally."
>
> support-0070: "Dont need internal modifier if policy referenced"

The mode was renamed from `leaks_internal_policy_id` to `cites_policy_by_internal_id` at
the reviewer's request: printing an internal label in a reply is over-sharing, not a leak,
and the original name asserted a security framing the evidence does not support.

This is the one mode whose status depended on the specification changing. Under the
original RESP-1 the agent was compliant, and 50 of 102 conversations could not have been
counted as failures at all. **The revision was applied to `SPEC.md` line 107 on
2026-09-22**, so the mode now has a live requirement source and is the most common failure
in the sample.

Two consequences worth stating. First, the agent is unchanged: it takes its instructions
from the system prompt in `agent/agent.py`, not from `SPEC.md`, so it still prints
identifiers. Fixing that is a prompt change, outside this assignment, and it would
invalidate the traces this analysis rests on. Second, three records in `hw1-session.jsonl`
are assessed against RESP-1 and marked met while printing identifiers. Those judgments were
correct against the specification as it then read and have been left as the reviewer made
them. A requirement changing under an earlier assessment is what a specification revision
means; it is not an error in the earlier work.

## Readiness for Homework 5

Homework 5 needs at least 30 present and 30 absent labels per mode to split and validate a
judge. Against the reviewed sample:

- `cites_policy_by_internal_id` clears it (50 / 52).
- The other seven are short on the present side, `missing_escalation` most severely at 3.

Closing those gaps means generating scenarios that target each mode, which is Homework 5
work. The absent side is comfortable everywhere.

## Observations recorded but not elevated

Three are documented in `analysis/report/observations_not_elevated.md`: repetition of
facts already stated, `asserts_records_against_the_user`, and `defers_what_was_asked`.
Each records why it was kept out and what would justify revisiting it.
