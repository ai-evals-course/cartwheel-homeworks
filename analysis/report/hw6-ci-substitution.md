# Homework 6 — running the evaluation suite without Docker

The handout's path is Harbor running repeated trials in fresh Docker containers, started
by GitHub Actions on a pull request. Two parts of that are unavailable here. This records
what was substituted, what was kept exactly, and what the substitution costs.

## What is unavailable, and why

**Docker cannot be installed.** Every `harbor run` in the handout passes `-e docker`, in
Parts A, B, C, D and E. `devfeature install docker_uv` needs interactive sudo and Duo, and
can leave `~/.config/uv/uv.toml` with a duplicate-key error that breaks `uv run` entirely.
Agent-first devservers with container internet access are supposed to work; this machine
is not one.

**The model credential cannot go to GitHub Actions.** `CARTWHEEL_MODEL` here is
`openai/rl-muse-spark-*` against `OPENAI_BASE_URL=https://api.ai.meta.com/v1` — an
internal gateway, not OpenAI. Two separate problems follow: a GitHub-hosted runner cannot
reach that host at all, and `OPENAI_API_KEY` is an internal credential. Sending it to a
third-party CI provider is against policy, confirmed independently by another student with
MetaMate. A student using a personal key for a public provider has neither problem.

## What replaced them

The course ships its own replay engine, and it does everything Harbor would do here
except containerise:

| Harbor in Docker | used instead | same? |
|---|---|---|
| fresh container per trial | `replay.rollout.world_reset` re-seeds a deterministic world before every rollout | equivalent isolation, no container |
| Harbor agent adapter | `replay.rollout.run_case` runs the real agent in process | same agent, same tools |
| Reward Kit code checks | `replay.rollout.apply_checks` | **identical, unmodified** |
| Reward Kit judge call | the frozen Homework 5 judge | same prompt, same model, same parser |
| reward per trial | pass/fail per rollout | same |
| `--n-attempts 5` | `replay.harness.replay_case(n=5)` | same contract, including infra retries |
| CI block/pass decision | `tests/eval/passk.case_passes` | **identical, the graded function** |

`scripts/run_baseline_local.py` and `scripts/run_ci_local.py` are thin drivers over those.
Nothing course-provided was modified.

## Two adaptations that were necessary, not cosmetic

**The judge is not called through `replay.rollout.judge_reply`.** That helper parses
`"answer": "pass"` and sets no `max_tokens`. This judge emits
`{"critique": ..., "result": "Pass"}`, and the models on this endpoint return *empty
content* when the token budget is too small, which `judge_reply` would fall through to
`return "pass"`. Using it unchanged would have scored **every case as a silent pass** with
nothing appearing broken. `analysis/tools/muse_classify` parses the real format and sets a
16k budget, so it is reused.

**Timeouts are raised as `ReplayInfraError`.** The handout is explicit that a case must not
be classified from a trial with an infrastructure error. A `litellm.Timeout` produces no
data, so it is wrapped and the harness resets and retries that rollout, up to its own
limit. A model that answers and answers wrongly is a real failure and is never retried.

## The agent model was changed, and the reason is measured

Homework 3, 4 and 5 ran the agent on `rl-muse-spark-1-3-sglang-playground`. On
2026-09-28 that model degraded badly. A fixed three-model probe, run on two consecutive
days against the same tiny prompt:

| model | 2026-09-27 | 2026-09-28 |
|---|---|---|
| `rl-muse-spark-1-1-playground` | 5.3s | 5.3s |
| `rl-muse-spark-1-2-playground` | 64.1s | 73.7s |
| `rl-muse-spark-1-3-sglang-playground` | 7.0s | **timeout at 300s** |

One baseline rollout took **669 seconds** on `1-3-sglang` and **133 seconds** on `1-1`.
At the former rate the homework's 175 required runs would take about 32 hours.

The agent therefore runs on `rl-muse-spark-1-1-playground` for all of Homework 6. The
handout permits this — *"Choose the model you want Cartwheel to use"* — and requires only
that the same model be used for the baseline, CI and trial-count comparison, which it is.

**The cost is judge independence on two cases.** The frozen Homework 5 judge also runs on
`1-1`, so for `e-011` and `e-012` a model grades output from the same model. That was
avoided deliberately in Homework 5. The other ten cases are decided entirely by code
checks and are unaffected.

**What did not change:** the failure modes themselves. `e-001` fails identically on both
models — an eligible order under $100, and no refund issued — and `e-006` passes on both.
The cases were designed around behaviour observed with `1-3-sglang` and reproduce on
`1-1`.

## Concurrency was tried and abandoned

Running cases in parallel processes, each with a private world, was built and tested:
`scripts/run_baseline_parallel.py`. Two cases at once produced one timeout and took longer
than running them one after another, because the endpoint was already degraded. The
baseline was run serially instead. The script is kept because it is correct and may help
when the endpoint is healthy.

Note for anyone reusing it: parallelism here must be **by process, not by thread**.
`world_reset` sets `CARTWHEEL_DB` in `os.environ`, which is process-global, so two cases
sharing a process would repoint each other's database mid-run and read the wrong world.

## What is still genuinely run on GitHub Actions

`.github/workflows/evals.yml` is completed in full, as the handout requires, and is the
workflow a fully provisioned environment would run.

Its **`offline-checks` job needs no model key** — it is pure pytest with no live calls —
and that job does run on real GitHub Actions and genuinely passes. The
**`complete-evaluations` job**, the one needing the model and judge credentials, is the
only part never sent to GitHub. Its equivalent runs locally through
`scripts/run_ci_local.py`, applying the same `case_passes` decision the workflow would.

For Part D there are no Actions URLs, so `ci-runs.json` records local commit SHAs and job
log paths instead, with the substitution stated. The handout's actual requirements —
inject a regression, show it blocks, revert it, show the second result — work identically.
Only *where it ran* differs.
