# Homework 5 — why labelling stopped at 9 confirmed failures

**Mode:** `irrelevant_policy_detail`
**Handout minimum:** 30 Pass and 30 Fail.
**Reached:** 140 Pass, **9 Fail**.

The handout permits this and asks for an explanation:

> **Stop early.** If you can't find enough Pass or Fail cases, explain why you stopped.

## The short version

The agent commits this failure rarely, and two rounds of targeted generation established
that it is rare *because the agent is good at the thing*, not because the search was
weak. Manufacturing 21 more instances would have meant roughly 300 further scenarios,
about eight hours of machine time, to produce cases the agent produces about 3% of the
time even when the situation is built to provoke them.

## What was tried

| step | scenarios or traces | Fails found |
|---|---|---|
| Homework 4 review, 102 conversations | — | 6 |
| Shape-targeted search over 149 unlabelled traces | 24 candidates read | 4 |
| Generated wave 1 and 2, built to provoke four shapes | 58 run, 23 candidates read | 2 |
| Development disagreement review | 4 disagreements | **−3** (label corrections) |

Net: 9.

The generation was not a failure of design. Sixty scenarios were built on real orders,
each placed in a situation where the failure could occur — orders in the gap between a
store's window and the platform default, refunds declined above the threshold, stores
that charge no restocking fee, refunds that complete inside the conversation. The
per-scenario yield was 3%.

## Why the failure is rare: three structural reasons

**Only 4 of 20 stores override the return window.** Juniper Home Goods (14 days),
Northwind Books (45), Meridian Cycles (21), Saltbox Pantry (7). Homework 3 spread 250
scenarios evenly across all 20 stores, so situations where the override matters are
uncommon by construction.

**Only 2 of 20 stores charge a restocking fee**, so the fee rule is almost always
irrelevant — but the agent mostly does not raise it.

**The agent reliably retrieves the store's window.** This is the strongest finding, and
it is the reason one whole failure shape was removed from the taxonomy as unobserved:

> 67 conversations concern an order from an override store. In 38 the agent called
> `get_store_info`, and in **all 38** it named the store's governing window in the reply.
> In the other 29 it named no window at all, having abandoned the turn or been asked
> something else. **No conversation states the 30-day default as operative while
> concealing the override.**
>
> 16 scenarios were generated specifically to provoke this, placing orders in the gap
> between the two windows where the rules give opposite answers. The agent was correct in
> 15, and the 16th turned out to be a different shape.

The correlation with `get_store_info` is perfect in both directions across 67
conversations. That tool was added to the agent in Homework 1, by this student, because
the agent had applied the platform default without checking whether the store overrode
it — correct at the time only by luck. Homework 5 measures that the fix held.

## What the shortfall costs

**The test split holds 2 Fails.** TNR is therefore measurable only as 0, 0.5 or 1.0, with
a 95% Wilson interval of roughly [0.09, 0.91] whatever the result. That is not a
precision problem to be argued around; the judge cannot be validated to any useful
tolerance on this data.

This is stated plainly rather than presented as a score, and it drives the answer to the
handout's question about whether the judge would be used: **no, not on this evidence.**
The development process found real problems — three inconsistent human labels and one
prompt gap — but a TNR that could be anywhere from 9% to 91% cannot support a decision to
deploy.

## Where the splits came from

`split_labels` refuses to split at the handout's default `min_per_class=10`, because
there are fewer than ten Fails in total. The guard was lowered to 4, deliberately and in
one place, with the reason recorded in `analysis/run_judges.py`. Fractions stayed at the
handout's 20 / 40 / 40.

## What was rejected, and why

**A third generation wave.** The best-performing shape yielded 6% per scenario. Forty more
scenarios would have produced two or three Fails for 70 minutes of machine time and 20
minutes of review, landing at 11 or 12 rather than 30.

**Switching to a mode with more failures.** `contradicts_eligibility_flag` has 17 Fails
and would generate freely, since the agent measures dates against the real calendar rather
than the seeded one. It was rejected because a deterministic check already detects it, and
the `write-judge-prompt` skill requires code-based options to be exhausted before reaching
for a judge. Building an LLM judge for something a regex resolves is the case the skill
names as an anti-pattern.

**Relaxing the definition to admit more cases.** The boundary was tightened four times
during this homework, each time because a trace read in full did not contain the failure
its label claimed. Loosening it to reach a label count would have inverted the exercise.

## If a later module needs a better-validated judge

Everything required to build one now exists and is reproducible: labelling
(`analysis/tools/label.py`), export in the Homework 5 convention
(`export_hw5_labels.py`), candidate search (`find_candidates.py`), scenario generation
(`.hw5-logs/select_orders.py` and friends), the judge pipeline (`analysis/run_judges.py`)
and a working classifier for this endpoint (`analysis/tools/muse_classify.py`). A second
judge on a more common mode is an evening's work, and Homework 5 permits additional judges
as an optional extension.
