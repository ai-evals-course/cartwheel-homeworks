# Homework 5 — an LLM judge for `irrelevant_policy_detail`

**Failure mode:** the agent explains a policy rule that does not govern the customer's
case.
**Requirement:** `SPEC.md` RESP-5 — *"Use direct and respectful language that explains the
relevant decision."*
**Judge:** `irrelevant_policy_detail-v6`, prompt `analysis/prompts/irrelevant_policy_detail-v1.txt`,
model `rl-muse-spark-1-1-playground`, frozen 2026-09-27.

## Headline result

| | TPR | 95% CI | TNR | 95% CI | agreement |
|---|---|---|---|---|---|
| development | 1.00 | [0.94, 1.00] | 1.00 | [0.34, 1.00] | 1.00 |
| **test (held out)** | **0.93** | **[0.82, 0.97]** | **0.60** | **[0.23, 0.88]** | **0.90** |

On test the judge caught **3 of 5** real failures and raised **4 false alarms** across 54
clean traces.

**Would I use this judge? No.** Two independent reasons, below.

Reproduce from saved predictions, no model call:

```bash
.venv/bin/python analysis/run_judges.py recalc
```

## Why this mode needed a judge

The `write-judge-prompt` skill requires code-based options to be exhausted first. Of the
eight Homework 4 modes, five have a working deterministic check and three do not. This is
one of the three, and the evidence that a rule cannot do it is direct: a grounded
heuristic was built, and the reviewer rejected 4 of its 14 candidates, after which a
boundary revision reversed 5 more of its accepted ones. The heuristic matched surface
wording — the strings `$100` and `30-day` — and repeatedly got the governing rule wrong.

Deciding whether a cited rule *governs* needs the store's window override, the order total
against the $100 threshold, the store's restocking opt-in, the order's status, and then a
reading of whether the reply applied them. That is a judgment, not a pattern.

## The definition, and how it changed

Final form, two tests, failing on either:

> 1. Does the rule the reply cites govern the path the agent actually took?
> 2. Does that rule bear on what the customer actually asked?

It began as one test and four failure shapes. It ended as two tests and two shapes, and
every change came from reading a trace in full that a label had mischaracterised.

**Shape 1 was removed as unobserved.** "The platform default stated as the operative rule
while the store's real window is never named" has **zero** instances in 149 labelled
conversations. Both traces originally filed under it name the store's window correctly;
the reason recorded for one of them was written from a truncated excerpt that cut off one
sentence before the window appeared. Sixteen scenarios were then generated specifically to
provoke it, placing orders in the gap between a store's window and the platform default
where the two rules give opposite answers. The agent was correct in 15, and the 16th was a
different shape.

The mechanism is clean and worth stating: across 67 conversations involving an override
store, the agent called `get_store_info` in 38 and named the governing window in **all
38**; in the other 29 it named no window at all. Perfect correlation, both directions.
`get_store_info` is the tool added to the agent in Homework 1, precisely because it had
applied the platform default without checking for an override. This homework measures that
the fix held.

**Test 2 was added** because of `support-0034`: a refund auto-approved, then the reply
explains the under-$100 rule that made it instant. The rule genuinely governed, so it
passes test 1, and it is still correct behaviour — it answers what the customer asked.
Whereas `support-0248` explains the same rule to someone who only asked whether their
money had been sent. Relevance is judged against the question, not merely against whether
the rule ever applied.

## One development disagreement, and the response

Four dev disagreements. **Three were our label errors; one was a judge error.** That ratio
is the most useful thing this homework produced.

### The judge error: `support-0221`

The customer is past Northwind Books' 45-day window. The agent declines, then says
*"refunds over $100 are queued for a human agent to review"*, then escalates to ask for an
exception to the window.

The judge called it Pass, reasoning:

> *"Order total is $189.25 which exceeds $100, and the agent actually took the path this
> rule requires by calling escalate_to_human and opening ticket #185. It is not a
> threshold cited for a path not taken; the ticket was opened."*

The reasoning is precise and wrong. A human *is* involved, but not because of the amount —
the refund was refused on the window, and the escalation asks for an exception to that
window. No refund is moving toward approval, so the threshold decided nothing. The judge
had treated co-occurrence as causation.

**Response: prompt revision v1.** The Pass rule became *"the reply is taking the path it
cites, AND the rule is the reason it took it"*, with the distinction spelled out: a refund
queued *because* the amount exceeds $100 passes; a refund refused on the window and
escalated for an exception fails, even though `escalate_to_human` appears in the trace.

No few-shot example was added. Training contained no trace of this shape, and the trace
that exposed it is in the dev split — using it would be leakage. That is a direct cost of
having only nine failures to divide across three splits.

**Effect:** dev TNR 0.50 → 1.00, and TPR stayed at 1.00, so the rule did not over-correct
onto genuine over-$100 escalations.

### The three label errors

- **`support-0038`** — $129.50, escalated. Identical in shape to three traces already
  rejected as Passes. Its recorded reason was still the unresolved candidate text.
- **`support-0026`** — the judge distinguished *"there's no restocking fee for this store"*
  (a store-level fact) from *"since your item is unopened, no restocking fee would apply"*
  (a condition-based exemption implying a charge that cannot happen). It inferred that
  boundary from the training examples; we had not articulated it.
- **`support-0218`** — a two-turn conversation whose second turn asks *"how long does it
  actually take to say yes or no to a refund?"* The $100 threshold determines exactly that.
  The original note addressed turn 1 only.

Correcting these, with no prompt change, moved dev TNR from 0.20 to 0.50. **The first
measurement was scoring our inconsistency, not the judge's skill.**

## Why revision stopped after one

The handout allows two. After v1 the dev split contained 2 failures and the judge agreed
on both. A second revision could only have been validated against those same two traces,
which is fitting to noise. Stopping was a measurement limit, not a quality judgment.

## The dev-to-test drop

TNR fell from 1.00 to 0.60, TPR from 1.00 to 0.93. This is the held-out split doing its
job. Dev is where three labels were corrected and one prompt revised, so the judge had
effectively been tuned against it. Test is the first data that influenced no decision.

**One test disagreement deserves reporting, and was deliberately not acted on.** The judge
called `support-0214` a Fail, reasoning that *"'because it's still sealed, you wouldn't be
charged a restocking fee' does not govern, because `restocking_fee_opt_in` is false for
Saltbox Pantry, so no restocking fee could ever apply"* — word for word the reasoning that
makes `support-0048` a Fail in the training set. It is very likely another label
inconsistency of the same kind dev exposed.

The label was **not** changed. Correcting a test label after seeing the test prediction
fits the model to the held-out set and destroys the measurement. The reported 0.60 stands.
The judge is probably better than that figure; demonstrating it would require a fresh set
of labels it has never been scored against.

## Would I use this judge?

**No, on two independent grounds.**

**The interval is too wide to support a decision.** TNR is 0.60 with a 95% interval of
[0.23, 0.88]. The true detection rate could plausibly be a quarter or nine-tenths. Nothing
should be automated on a measurement that loose. The cause is the label count: 9 confirmed
failures, 5 of them in test. See `analysis/report/hw5-labelling-outcome.md`.

**The dev-to-test drop shows the development loop was partly fitting our own labels.**
Three of four dev "judge errors" were ours. That is a healthy thing to have discovered,
and it means the dev scores measured label consistency as much as judge quality.

**What it is good for.** As a triage aid over unlabelled traces it would be useful now: a
TPR of 0.93 means it rarely bothers a reviewer with a clean trace, so it could rank a
backlog for human attention. What it cannot do is decide unsupervised, or support a
prevalence estimate — a Rogan-Gladen correction inherits the TNR interval and would produce
a range too wide to act on.

## A note on the judge versions in `analysis/state/judges/`

There are seven, and only two ran a complete evaluation. `register_judge` increments a
version on every call, including calls that then failed against the endpoint, so v0 to v3
are empty records left by the four infrastructure problems described below, and v4 holds
20 predictions from a run that died partway. They are kept rather than deleted because
they are the honest record of what it took to get a judge running against this endpoint.

The two that matter:

- **v5** — prompt v0, 59 dev predictions. The first working run.
- **v6** — prompt v1, 118 predictions (59 dev + 59 test), **frozen**. The judge reported
  above.

## Substitutions

Four, each documented in `analysis/report/workshop_notes.md`:

| handout expects | used instead | why |
|---|---|---|
| Langfuse | local OTel file export | Docker could not be installed |
| Raindrop Workshop | local search tooling | piped installer, MCP server, writes to `.env` |
| `gpt-4o-mini` | `rl-muse-spark-1-1-playground` | the endpoint serves three models, none of them OpenAI's |
| DocETL map operation | direct classifier, `analysis/tools/muse_classify.py` | the endpoint accepts only `tool_choice: "auto"` and rejects DocETL's named-function schema enforcement |

The third was turned to advantage. The agent under test ran on
`rl-muse-spark-1-3-sglang-playground`; the judge runs on `1-1`. A judge sharing the model
it grades is least likely to notice that model's own kinds of mistake, so the constraint
bought independence the handout's own setup does not require.

The fourth keeps the rest of the pipeline intact: `run_judge` accepts a `classify`
callable in place of the DocETL backend, and the replacement returns the same
predictions-plus-critiques structure, so caching, resume, alignment and disagreement
review all work unchanged.
