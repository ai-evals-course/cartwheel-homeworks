# HW6 notes for teaching

Concrete terminology and case studies from turning HW4's failure modes into
CI-enforced eval cases with Harbor. See [concepts.md](concepts.md) for
generic framing.

## Terminology: case vs. run/trial vs. baseline runs

Easy to conflate with HW3/4's "trace" vocabulary, so worth pinning down
precisely:

- **Case (evaluation case)** — one reusable, scripted test definition: one
  line in `eval_cases/cases.jsonl`, with a fixed `input` (role, user,
  message), an `initial_state` (what the seeded DB should look like), and
  an `expected` (checks/judges that decide pass or fail). A case is closer
  to a unit test than to a one-off HW4 trace review — it's written once,
  committed, and meant to be re-run indefinitely, not read once and moved
  past.
- **Run / trial** — one actual execution of a case: Harbor spins up a
  fresh Docker container, the real agent processes the case's scripted
  input, and the result (the conversation + tool calls it produces) is
  scored against that case's `checks`/`judges`. This is the thing that
  resembles an HW3/4 trace — except it's reproducible on demand from the
  case definition, rather than a one-time observed record.
- **Baseline runs** — the batch of 5 runs Part A has you execute for each
  *newly written, not-yet-classified* case, specifically to decide its
  `kind` (`regression` if 5/5 pass, `capability` with a recorded
  `baseline_pass_rate` otherwise). This is a one-time classification step,
  separate from every later CI run of the same case (which also runs it
  5×, but for a pass/fail CI decision, not to reclassify it).

So "10 evaluation cases" means 10 distinct scripted scenarios committed to
`cases.jsonl` — not 10 traces to review. Each one costs 5 live-model runs
just for its baseline classification (10 cases x 5 = the 50 baseline runs
in the handout's scale math), and costs another 5 on every subsequent CI
run of the same PR.

## Why classification needs multiple trials, not one

A single run of a case can't distinguish "this reliably works" from "this
happened to work once." The same case, run against the same model and the
same scripted input, can still produce a different trajectory each time —
model sampling, tool-call ordering, or a borderline judge call can all
flip one run's outcome relative to another. Five runs is the minimum
that lets a case's classification rest on an actual observed pattern
(5/5, or some fraction like 3/5) instead of one draw that might not
represent the case's true reliability.

This directly motivates why HW6 defines two different metrics instead of
one (Part B):

- **pass@k** (`pass_at_k`) — chance of *at least one* success in k
  attempts, estimated from n observed runs. Used for **capability**
  cases: something not yet reliable, where the question is "can the
  agent do this at all, at least sometimes."
- **pass^k** (`pass_hat_k`) — chance that *all* k attempts succeed, from
  the same observations. Used for **regression** cases: something that
  currently works every time, where the CI question is "does it still
  work every time," and a single failure among many runs is itself the
  signal, not noise to average away.

The classification (`kind`) a case gets from its 5 baseline runs
determines which of these two questions is even the right one to ask
about it going forward — which is why baseline classification is a
one-time, load-bearing step, not a formality.

## pass@k: definition and worked examples

**Definition.** pass@k is the probability that *at least one* of k
independent attempts succeeds, estimated from n observed runs (n >= k)
with c of them successful:

```
pass@k = 1 - C(n - c, k) / C(n, k)
```

`C(n - c, k)` is the number of ways to pick a size-k subset containing
*only failures*; dividing by all possible size-k subsets and subtracting
from 1 gives "the chance a random k-subset contains at least one
success." When there are fewer than k failures (`n - c < k`), no such
all-failure subset exists, so pass@k = 1.0 exactly, regardless of k.

**Worked example (course reference numbers, n=8, c=6):**

| k | Calculation | pass@k |
|---|---|---|
| 1 | `1 - C(2,1)/C(8,1)` = `1 - 2/8` | 0.750 |
| 2 | `1 - C(2,2)/C(8,2)` = `1 - 1/28` | 0.9643 |
| 4 | `1 - C(2,4)/C(8,4)` — only 2 failures, can't fill a 4-subset | 1.000 |

**Worked example (our own e-002 baseline, n=5, c=3):**

| k | Calculation | pass@k |
|---|---|---|
| 1 | `1 - C(2,1)/C(5,1)` = `1 - 2/5` | 0.600 |
| 3 | `1 - C(2,3)/C(5,3)` — only 2 failures, can't fill a 3-subset | 1.000 |
| 5 | `1 - C(2,5)/C(5,5)` — same reason | 1.000 |

Reading this: e-002 passed 3 of 5 baseline runs, so a single attempt has
a 60% chance of success (pass@1), but if the agent gets to try **3 or
more** times, it's *certain* (pass@k = 1.0) to succeed at least once,
because there are only 2 ways for it to fail and a subset of 3+ attempts
can't be made entirely of those 2 failures. This is exactly why pass@k
is the right lens for a **capability** case: it answers "can the agent
get this right at all, given enough tries," which rises (or stays flat)
as k grows.

## pass^k: definition and worked examples

**Definition.** pass^k ("pass hat k") is the probability that *all* k
independent attempts succeed, from the same n observed runs with c
successes:

```
pass^k = C(c, k) / C(n, k)
```

This is "the chance a random k-subset of the observed runs is entirely
successes." When there are fewer than k successes (`c < k`), no
all-success subset of that size exists, so pass^k = 0.0 exactly.

**Worked example (course reference numbers, n=8, c=6):**

| k | Calculation | pass^k |
|---|---|---|
| 2 | `C(6,2)/C(8,2)` = `15/28` | 0.5357 |
| 4 | `C(6,4)/C(8,4)` = `15/70` | 0.2143 |
| 8 | `C(6,8)/C(8,8)` — only 6 successes, can't fill an 8-subset | 0.000 |

**Worked example (our own e-002 baseline, n=5, c=3):**

| k | Calculation | pass^k |
|---|---|---|
| 1 | `C(3,1)/C(5,1)` = `3/5` | 0.600 |
| 3 | `C(3,3)/C(5,3)` = `1/10` | 0.100 |
| 5 | `C(3,5)/C(5,5)` — only 3 successes, can't fill a 5-subset | 0.000 |

Reading this: the *same* case (e-002, 3/5) that looked perfect under
pass@k (1.000 at k=3 and k=5) looks essentially broken under pass^k —
by k=5 it's *certain* (0.000) that not all 5 attempts would succeed,
because there are only 3 successes to draw from. This is the concrete
illustration of the handout's own warning: pass@k rises with k, pass^k
falls with k, and using the wrong one for the wrong kind of case would
either wrongly block CI on a capability case that's making real progress,
or wrongly let a regression case merge because it happened to succeed
once. That's why regression cases are gated on pass^k (all-must-succeed)
and capability cases are only ever reported via pass@k (can-succeed).

### Summary checklist

| Metric | What it measures | Why use it? |
| --- | --- | --- |
| pass@1 | Single-shot accuracy | Measures **reliability** on one try. Matters when the user only ever sees a single answer (e.g. a direct chat reply). |
| pass@k (k > 1) | Multi-sample capability | Measures the model's **knowledge bound** — can it get there at all, given several attempts. Matters for agent loops, re-ranking, or self-correction pipelines where several attempts are generated. |
| pass^k | Deterministic consistency | Measures whether the model passes **all** k attempts back to back, without flaking out. Matters for CI gating a behavior that's supposed to already work every time. |
