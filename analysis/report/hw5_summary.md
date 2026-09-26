# HW5 summary: LLM judge for `mishandles_vague_requests`

## Mode chosen

`mishandles_vague_requests` — merged during HW5 label collection from two
HW4 modes (`no_clarifying_question` + `asks_for_unusable_information`), then
broadened further to also cover redundant speculative tool-call looping and
unsupported "maybe it exists" assertions made in response to a vague
request. See `analysis/state/patterns.json` for the full definition history
and `analysis/report/review_summary.md` for the HW4-side merge reasoning.

Chosen over the alternatives (`ignores_data_quality_anomaly`,
`leaks_internal_terminology`, etc.) because, after the HW4 mode merges, it
had the strongest evidence base (50 positive examples pre-dedup) and — per
its `evaluator_type` in `patterns.json` — is checkable primarily from the
conversation text and tool-call sequence, without needing external ground
truth the way `ignores_data_quality_anomaly` does (that one needs the
seeded data-quality table to know which records are corrupted).

## Label collection

Started from HW4's 8 Fail / 94 Pass for the pre-merge `no_clarifying_question`.
Generated two batches of new scenarios (40, then 28 more) specifically
targeting the merged mode's failure shape — biased toward pairing ambiguity
with a *write* action (refund/cancel), since read-only "check my order"
requests turned out to already be handled well and didn't produce new
Fails. Categories: false-confidence time narrowing, social pressure/urgency,
vague scope on a write action, referencing nonexistent history,
duplicate-title-plus-action, and staff-role-plus-action. ~20 of these were
multi-turn, to see the agent's follow-through, not just its opening move.

A full review-notes sweep (catching several deferred "bonus evidence" items
and three fabricated trace-id bugs from earlier bookkeeping) brought the
final count to **50 Fail, 142 Pass** before deduplication.

## Part B: inputs and split

`analysis/run_judges.py`'s `prepare_inputs()` exports one record per
distinct conversation — plain trace content only, no labels/annotations/
scenario metadata, so the judge can't see the answer. Deduplicated 197
reviewed traces down to **158** by collapsing groups that test the exact
same underlying record with only phrasing varied (the 5-variant
data-quality cases from HW3, and the repeated Heavy-Duty Vase scenarios) --
everything else (different customers/orders, even if thematically similar)
counted as independent.

`split_data()` used `split_labels` at 20/40/40, seed=7:

| split | Fail | Pass | total |
|---|---|---|---|
| train | 8 | 24 | 32 |
| dev | 15 | 48 | 63 |
| test | 15 | 48 | 63 |

## Part C: prompt iteration (`gpt-4o-mini`, exposed via `CARTWHEEL_JUDGE_MODEL`)

**v0** (`analysis/prompts/mishandles_vague_requests-v0.txt`): task, Pass/Fail
definitions, 3 training-split examples (clear Fail, clear Pass, one
borderline), structured critique-then-verdict output.

Dev: **TPR 0.81, TNR 0.53** — the judge was missing nearly half of real
Fails.

**v1** (revision 1): inspected all 16 dev disagreements. Found the judge
anchored on the conversation's opening turn and excused everything after it
("this technically does not break the initial Pass"). Added: an explicit
instruction to judge the whole conversation, not just the opening; a
stronger statement that a redundant search loop is a Fail even with a good
ending; 2 new examples (unusable-option-alongside-a-usable-one; redundant
looping + an unsupported claim, in one worked example).

Dev: **TPR 0.77, TNR 0.73** — TNR up 20 points, TPR dipped slightly.

**v2** (revision 2, the handout's cap): inspected the new 15 dev
disagreements. Found a fresh over-correction -- the judge now penalized
*any* missing question, even when the agent's own tool lookup had already
fully resolved the ambiguity (e.g. "every order is already shipped, nothing
is cancellable regardless of which one"). Also found the escalation
exclusion wasn't landing (the judge's own critique would note a correct
escalation, then still fail the trace for "not asking first"). Fixed: a
hard escalation gate ("if escalation is present and appropriate, stop
evaluating and return Pass"), a new PASS clause for tool-lookup-resolves-
ambiguity with a contrasting worked example, and an explicit
"shopper/customer name" addition to the unusable-info list.

Dev: **TPR 0.85, TNR 0.73** — best dev result, and the two-revision cap
was reached, so this is where iteration stopped per the handout.

## A robustness bug found and fixed along the way

Twice, on unusually long traces (20+ orders dumped in one tool result), the
model returned a `result` value outside `{"Pass", "Fail"}` (once literally
`"Not found"`). A plain retry never recovered because DocETL's completion
cache serves the same response for an identical (prompt, content) pair --
confirmed by forcing a bypass and getting a different, valid answer.
Fixed in `analysis/helpers/scale.py`: `_run_docetl_map` now retries only
the invalid trace ids with the cache bypassed, instead of crashing the
whole batch.

## Part D: frozen test results — the real finding

All three versions were run once on the same untouched 63-trace test split,
for comparison:

| | dev TPR | dev TNR | test TPR | test TNR |
|---|---|---|---|---|
| v0 | 0.81 | 0.53 | 0.85 [0.73, 0.93] | 0.60 [0.36, 0.80] |
| v1 | 0.77 | 0.73 | 0.77 [0.63, 0.87] | 0.60 [0.36, 0.80] |
| v2 (frozen) | 0.85 | 0.73 | 0.75 [0.61, 0.85] | 0.53 [0.30, 0.75] |

**TNR is essentially flat across all three on test (0.53-0.60), regardless
of the 20-point gain v1/v2 showed on dev.** v0 -- the simplest, least
engineered prompt -- has the best test TPR and ties for best test TNR
despite being dev's weakest performer. This is the textbook signature of
overfitting to dev: each revision was built by reading exactly what was
wrong in dev's specific disagreements, and some of that specificity (new
examples, exclusion clauses) captured dev-set quirks rather than the
general pattern, so it didn't transfer to test's different instances of
the same failure types.

Confidence intervals are wide (n=63, ~15 in the minority class each split),
so small differences between versions shouldn't be over-read -- but a TNR
stuck at 0.53-0.60 regardless of which version is used is a real, load-
bearing finding, not noise.

**Would I use this judge?** Not as a standalone judge of record for this
failure mode. A TNR around 0.5-0.6 means it misses roughly 40-50% of real
failures no matter which prompt wording is used, and that ceiling looks
like it's set by training-data size and diversity (32 Fail examples split
three ways, several from a narrow set of generated scenario templates)
rather than by prompt wording. The fix isn't a third prompt revision --
it's substantially more labeled Fail examples spread across more of the
failure's actual variety, before iterating on wording further. It could
still be useful today as a cheap first-pass filter to prioritize traces for
human review (its TPR is reasonably solid), just not as the sole detector.

## One development disagreement, in detail (for the video)

`live-46db4e4` (v0): customer asks for anything "pink" that fits a small
room. The agent asks a genuinely good opening clarifying question, then
runs ~30 speculative search variants after the first one already returned
zero results, and closes by asserting "even if the color isn't in the
title, we can often find the right style keywords" with nothing supporting
that. v0's judge returned Pass, with a critique that explicitly said this
"does not break the initial Pass" -- directly exposing the anchoring bug
that motivated v1's "evaluate the whole conversation" fix.

## Files

- `analysis/prompts/mishandles_vague_requests-v{0,1,2}.txt`
- `analysis/state/hw5_trace_inputs.json`, `analysis/state/splits.json`
- `analysis/state/judges/` (all registered versions, predictions, critiques)
- `analysis/report/dev-*.json`, `analysis/report/test-*.json`
- `analysis/run_judges.py` (`prepare_inputs`, `split_data`, `run_development`, `run_test`)
