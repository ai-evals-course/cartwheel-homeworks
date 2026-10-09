# Homework 6 — CI for agent evaluations

**Agent model:** `rl-muse-spark-1-1-playground`, used for the baseline, both CI runs and
the trial comparison.
**Cases:** 12, across 4 failure modes observed in Homework 4.
**Classification:** 2 regression, 10 capability, all from five baseline runs each.

## Part A — the cases and what classifying them showed

Twelve cases, each built on a real order from the seeded world, covering four Homework 4
failure modes:

| mode | cases | decided by |
|---|---|---|
| `contradicts_eligibility_flag` | e-001 … e-005 | code: `refund_status`, `no_refund_row` |
| `missing_escalation` | e-006, e-007 | code: `tool_called: escalate_to_human` |
| `cites_policy_by_internal_id` | e-008 … e-010 | code: `reply_not_contains` |
| `irrelevant_policy_detail` | e-011, e-012 | the frozen Homework 5 judge |

Only the last pair needs a judge. Everything else reduces to an exact fact — a tool call,
a database row, a string in the reply — which is what the handout asks for and which
sidesteps the Homework 5 judge's wide TNR interval.

### Results

```
regression   e-007  missing_escalation            5/5
             e-010  cites_policy_by_internal_id   5/5

capability   e-001  contradicts_eligibility_flag  0/5     e-008  0/5
             e-002  contradicts_eligibility_flag  0/5     e-009  2/5
             e-003  contradicts_eligibility_flag  0/5     e-011  0/5
             e-004  contradicts_eligibility_flag  0/5     e-012  0/5
             e-005  contradicts_eligibility_flag  0/5
             e-006  missing_escalation            4/5
```

The five `contradicts_eligibility_flag` cases are 0/5 between them. Fifteen rollouts
across three stores, every order refund-eligible and under $100, and the agent issued a
refund in none of them. Homework 3 measured that at 12% across 250 varied scenarios;
under repetition with the world reseeded identically each time, it is zero.

### What writing the cases taught, which was not what I expected

**Negative and judge-only cases can be passed by an agent that does nothing.** e-004 and
e-005 require the agent *not* to refund an out-of-window order, and `no_refund_row` plus
`no_write_tools` are both satisfied by an agent that says "let me look that up" and
stops. e-012 is decided by a judge, and a judge cannot fail a reply that contains no
policy claim at all — it returned **pass on all five rollouts while the agent called zero
tools**. In all three, the `tool_called` check is the only thing separating a correct
answer from no answer. A negative check needs a positive companion.

**Two of my Homework 1 tools are nearly redundant.** `find_order` returns every field
`get_order` does except `store_name`, including `refund_eligible` — the value that
decides every refund. The system prompt tells the agent to call `get_order` before any
refund decision, but `find_order` has already answered that question, so the agent skips
it. Four of my cases were penalising a reasonable choice. I removed the check where it
was redundant (e-001 to e-003, where `refund_status` already implies the lookup) and kept
it where it was load-bearing, recording the reason on each case.

## Part B — pass@k and pass^k

`pass_at_k`, `pass_hat_k` and `case_passes` are implemented in `tests/eval/passk.py` and
reproduce the lecture's worked numbers exactly.

The distinction is not academic. From the first CI run:

| case | passed | pass@1 | pass@3 | pass^5 | decision |
|---|---|---|---|---|---|
| e-009 | 3/5 | 0.600 | **1.000** | **0.000** | pass |
| e-010 | 4/5 | 0.800 | **1.000** | **0.000** | block |

Both read as *"retry three times and it will work"* and *"it will not work five times in
a row."* CI uses the reliability view, because merging on the grounds that one run in
three succeeded would let a broken behaviour through.

## Part D — the regression, caught and reverted

Full record in `ci-runs.json`. Both runs come from pull request #1 on the same branch.

The instruction removed was one added in Homework 1, after the agent tried to handle an
account change itself:

> *Account changes of any kind are always handled by a human: decline to make the change
> yourself and escalate.*

`SPEC.md` ESC-2 still required the behaviour; only the instruction telling the agent about
it was gone.

| run | commit | e-007 | e-009 | e-010 | gate |
|---|---|---|---|---|---|
| regression | `b30ffdd` | **0/5** | 3/5 | 4/5 | BLOCK |
| reverted | `3097c6f` | **4/5** | 2/5 | 5/5 | BLOCK |

**The gate worked in both directions.** Removing one sentence took e-007 from 5/5 to 0
of 5 across five clean trials; restoring it brought the behaviour back.

**The second run still blocks, and that failure is kept.** The handout says a second-run
failure without an infrastructure error is new evidence and the commit must not be rerun.
That trial called **no tool at all** and failed on `tool escalate_to_human called` — the
narrate-before-calling behaviour described below, not a return of the injected
regression. It means e-007's 5/5 baseline was optimistic: the behaviour runs at about
80%, and five runs pinned it tighter than it deserved.

That is the same lesson Part E makes quantitative, arriving unprompted.

## Part E — fifteen runs of one capability case

e-009 was chosen because it is genuinely intermittent. A case at 0/5 or 5/5 shows nothing
as k grows; only a case that sometimes works makes the comparison say anything.

```
sequence:  x x x x x . . x . x . x . . x

    n   passes   rate    pass@1   pass@3   pass@5   pass@10   pass@15
    5        0   0.00     0.000    0.000    0.000
   10        3   0.30     0.300    0.708    0.917
   15        6   0.40     0.400    0.815    0.958     1.000     1.000
```

**The first five trials all failed.** Stopping at five would have reported
`pass@5 = 0.000` -- the agent can never do this. Fifteen runs report a 40% rate and
`pass@5 = 0.958` -- give it five attempts and it almost certainly works. Same case, same
world, same model, opposite conclusions.

**Fifteen runs did not produce a stable estimate.** `pass@1` moved 0.000 -> 0.300 ->
0.400 and was still climbing between n=10 and n=15. The handout asks for this to be
stated plainly rather than presented as settled, so: it is not settled.

At each fixed n, pass@k increases with k, as it must.

The wider evidence agrees. Four separate five-run samples of e-009 exist across this
homework -- the baseline, both CI runs, and the first five of this batch -- and they gave
**0%, 40%, 40% and 60%**. The five-run classification that Part A depends on cannot
distinguish a 0% case from a 60% one for behaviour that really sits near 40%.

That is the same finding Part D produced by accident. e-007 was classified `regression`
from a 5/5 baseline and then failed once in the reverted run: its real rate is about 80%,
and five runs pinned it as perfect.

## The biggest finding: 47% of rollouts call no tool at all

Across all 60 baseline rollouts, **28 called no tool whatsoever** — 5 of 5 in one case.
The agent replies "let me pull up your order" and the conversation ends.

The cause is an instruction in the system prompt:

> *You MUST explain your reasoning in plain text before every tool call. State what you
> are about to look up and why, in one sentence. Do not call a tool without explaining
> first.*

With this model the explanation arrives as its own turn, the framework reads a text-only
reply as the final answer, and the run stops. This is `abandons_mid_task` from Homework 4,
and repeated trials show it is far more common than single-run review suggested.

It is **not** the world-date bug, which remains unfixed and which drove the Homework 3 and
Homework 5 refund refusals. No reply in these runs reasons about dates, because the agent
rarely gets far enough to reason about anything.

Neither bug was fixed during this homework: the handout requires one fixed system across
the baseline, CI and trial comparison. Both are Module 5 improvement targets with measured
baselines already attached.

## Endpoint conditions

Three batches were lost to endpoint failures over two days: 6 of 15 trials, then 1 of 15,
then **15 of 15** on the first Part E attempt. The models take turns being overloaded —
on 2026-09-29, `1-1` was healthy in the morning while `1-2` returned `service_overloaded`,
and the reverse held that evening.

This is why the harness records an infrastructure error as *no reward* rather than a
failure. Scored as failures, that lost Part E batch would have read e-009 at 0/15 and
looked like a total capability collapse. Reported honestly, it reads "15 trials did not
produce a reward" and the number is discarded.

## Substitutions

Harbor, Docker and GitHub-hosted evaluation runs were unavailable; see
`analysis/report/hw6-ci-substitution.md` for the full record. In summary: the course's own
replay engine replaces Harbor's containers, results are written in Harbor's shape and
summarised by `harbor_adapter.summary.summarize_job`, so the report table and the CI gate
are the course's code calling the graded `passk` functions. The workflow is complete in
`.github/workflows/evals.yml`, and its credential-free `offline-checks` job does run on
GitHub Actions from pull request #1.
