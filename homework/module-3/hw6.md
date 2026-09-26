# Homework 6, CI for agent evaluations

In Homework 6, you will turn reviewed examples from Module 2 into evaluation cases that run on every pull request. You will use the baseline results to separate behavior that works from behavior that is not reliable yet.

## Work through the assignment with a coding agent

Paste this prompt at the start of a coding agent session in your repository:

> Guide me through Homework 6 in `homework/module-3/hw6.md`, one part at a time. Read `AGENTS.md`, the handout, `eval_cases/README.md`, and my Homework 4 and Homework 5 artifacts before changing files. Keep the Cartwheel case and judge formats. Use the supplied adapter to generate Harbor tasks. Do not ask me to write Harbor task directories by hand.
>
> Help me create at least 10 evaluation cases from at least two failure modes I observed in Homework 4. Run each case five times before classifying it. My final set must contain at least one regression case and one capability case. Use code checks for exact facts. If a result requires interpreting language, use only a judge I accepted in Homework 5. Preserve its frozen prompt, model, input, and verdict parser. Help me implement pass@k and pass^k, configure GitHub Actions to run Harbor with Docker, produce one CI run with an intentional regression and another after I revert it, and compare pass@k after 5, 10, and 15 observed runs. Before a paid run, show me the model, tasks, agent runs, and judge calls, then wait for my approval. Never print or commit secret values. Leave the final classifications and video to me.

## What you will submit

1. At least 10 evaluation cases from at least two failure modes observed in Homework 4.
2. Five baseline runs for every case.
3. At least one regression case and one capability case, based on the baseline results.
4. Two GitHub Actions runs from the same pull request. One includes an intentional regression, and the other runs after you revert it.
5. A 15 run analysis of one capability case.
6. A video of no more than 5 minutes.

Ten cases require 50 baseline agent runs. Two full CI runs require another 100, and Part E requires 15. The minimum is 165 agent runs. Each case that uses an LLM judge also makes one judge call per run. You may need more baseline runs if your first 10 cases do not include both classifications.

## Tools used in this homework

We use two tools:

1. [Harbor](https://www.harborframework.com/docs/tasks) runs repeated trials in fresh Docker containers and records rewards. Reward Kit, which is part of Harbor, runs the code checks and accepted judge prompts.
2. GitHub Actions starts the Harbor job on its own runner when a pull request changes.

The supplied dataset adapter converts `eval_cases/cases.jsonl` into Harbor tasks. The supplied agent adapter runs Cartwheel inside each task. An accepted Homework 5 judge receives the full conversation and tool trace through the same DocETL prompt wrapper and Pass or Fail parser used in Homework 5. Do not edit or commit the generated `.harbor/tasks` directory.

## Preparation

Run these commands from the repository root:

```bash
uv sync
uv tool install 'harbor==0.23.0'
```

Choose the model you want Cartwheel to use and set `CARTWHEEL_MODEL` in your shell. Keep the same model for the baseline, CI, and trial-count comparison so the results describe one system.

```bash
export CARTWHEEL_MODEL="YOUR_MODEL"
```

Set the provider key required by that model in `.env`. The model is your choice. For a provider not named in `.env.example`, use its LiteLLM `provider/model` name so the adapter can identify the key. The agent model is separate from the frozen model used by an accepted Homework 5 judge.

If you did not finish Homework 5 or did not accept a judge, download the Git LFS files and apply the reference bundle:

```bash
git lfs pull
git apply homework/module-3/hw5-reference.patch
```

The reference judge detects unsupported policy claims and uses Claude. Use it only for that failure mode. A local or CI run that uses the reference judge needs `ANTHROPIC_API_KEY`, even when the Cartwheel agent uses a different provider.

You do not need to seed the database. Each Harbor task creates its starting state inside a fresh Docker container.

## Part A, write and classify the evaluation cases

Add cases to `eval_cases/cases.jsonl`. Start each new case without `kind` or `baseline_pass_rate`. You will add those fields after its five baseline runs.

The following case is based on scenario `full-053`. The shopper needs the refund amount, payment destination, timing, and next step. The agent should answer without issuing a refund.

```json
{
  "id": "e-001",
  "mode": "uninformative_response",
  "input": {
    "role": "shopper",
    "user_id": 110,
    "message": "I got a dry bag from Meridian Cycles and it has a tear in it. Can I get a refund?"
  },
  "initial_state": {
    "world": "reseed",
    "fixture": null,
    "assumes": "Order 8594 is delivered, eligible, worth $45.50, and owned by user 110."
  },
  "expected": {
    "assertions": [
      "The reply gives the refund amount, payment destination, timing, and next step without irrelevant detail."
    ],
    "checks": [{"check": "tool_called", "name": "get_order"}],
    "judges": {"uninformative_response": "pass"}
  }
}
```

The example assumes that `uninformative_response` is a judge you accepted in Homework 5. Use your own judge name. If you applied the reference patch, use `unsupported_policy_claim` only for a case about unsupported policy claims.

Use a code check when the result is an exact tool call or database value. Use an accepted Homework 5 judge when the result depends on the meaning of the reply. Do not introduce a new judge in this homework.

`assertions` explain the expected behavior to a reader. Harbor decides whether a run passed from `checks` and `judges`.

Run one unclassified case five times:

```bash
uv run python scripts/export_harbor_tasks.py \
  --baseline \
  --case e-001
PYTHONPATH="$PWD" harbor run \
  --env-file .env \
  -p .harbor/tasks \
  -a harbor_adapter.agent:CartwheelAgent \
  -m "$CARTWHEEL_MODEL" \
  -e docker \
  --n-attempts 5 \
  --job-name hw6-baseline-e-001 \
  --jobs-dir .harbor/jobs
uv run python scripts/summarize_harbor_job.py \
  .harbor/jobs/hw6-baseline-e-001 \
  --expected-attempts 5 \
  --classify
```

The summary tells you what to record:

1. Five passes means `kind` is `regression`.
2. Any failure means `kind` is `capability`. Record the observed fraction as `baseline_pass_rate`.

Do not classify a case if a trial has an infrastructure error or no reward. Fix the infrastructure problem and rerun only that baseline job.

Repeat the baseline run for every case. Finish with at least 10 cases from at least two observed failure modes. If the first 10 cases have the same classification, add cases until you have at least one regression and one capability. Do not change a classification to produce the required pair.

The stretch goal is 30 cases. Keep the classification produced by each case's five baseline runs.

## Part B, calculate pass@k and pass^k

Implement three functions in `tests/eval/passk.py`:

1. `pass_at_k(n, c, k)` estimates the chance of at least one success in `k` attempts from `n` observed runs with `c` passes. Use pass@k for a capability.
2. `pass_hat_k(n, c, k)` estimates the chance that all `k` attempts succeed from the same observations. The metric is written pass^k. Use pass^k for reliability.
3. `case_passes` blocks CI when any run of a regression case fails. A capability case reports its results without blocking CI.

Run the supplied checks:

```bash
uv run pytest --runxfail tests/test_hw_holes.py -k "hw6_pass or hw6_case"
```

You should see three passing tests.

A regression case passed five times during its baseline, but future runs can still fail. If `r` regression cases each have per-run reliability `p`, the chance that all five runs of every case pass is `p^(5r)`. Treat each completed failure as evaluation evidence instead of rerunning it until it passes.

## Part C, run the classified cases in GitHub Actions

Generate the final Harbor tasks. The command rejects any case that is still missing its classification.

```bash
uv run python scripts/export_harbor_tasks.py
```

Complete `.github/workflows/evals.yml`. The pull request job must:

1. Install `harbor==0.23.0`.
2. Generate the classified Harbor tasks.
3. Run every task in a fresh Docker container with `--n-attempts 5`.
4. Pass the agent provider key and every judge provider key to Harbor.
5. Run `scripts/summarize_harbor_job.py` with `--expected-attempts 5` and `if: always()`.
6. Upload `.harbor/jobs/hw6-evals` as a workflow artifact with `if: always()`.

Use the supplied adapter and a fixed job location:

```bash
PYTHONPATH="$PWD" harbor run \
  -p .harbor/tasks \
  -a harbor_adapter.agent:CartwheelAgent \
  -m "$CARTWHEEL_MODEL" \
  -e docker \
  --n-attempts 5 \
  --job-name hw6-evals \
  --jobs-dir .harbor/jobs \
  --yes
```

Set `CARTWHEEL_MODEL` as a GitHub Actions repository variable. Add the agent provider key and every judge provider key as repository secrets. The scaffold includes the providers configured in `.env.example`; add the corresponding workflow environment entry if you choose another provider. Do not put secret values in the workflow file.

The job summary must show each case's pass count, pass@1, pass@3, pass@5, pass^5, and CI decision. A regression blocks the job when any of its five runs fails. A capability never blocks the job.

## Part D, run an intentional regression

1. Add a temporary prompt instruction that should make one regression case fail.
2. Push the change and save the GitHub Actions URL.
3. Revert the prompt instruction, push again, and save the second URL.
4. Record both URLs, the case ID, the second run's result, and a short explanation in `ci-runs.json`.

Both runs must come from the same pull request. The first run must reach the verifier and fail the selected case. The second run shows whether the original behavior returned. If the second run fails without an infrastructure error, keep the failure as new evidence and do not rerun the same commit.

## Part E, compare trial counts

`n` is the number of runs you observed. The `k` in pass@k is the number of attempts the product could make. Harbor calls its number of runs `--n-attempts`, so use the long flag in this homework.

Run one capability case 15 times:

```bash
PYTHONPATH="$PWD" harbor run \
  --env-file .env \
  -p .harbor/tasks \
  --include-task-name "*YOUR_CASE_ID" \
  -a harbor_adapter.agent:CartwheelAgent \
  -m "$CARTWHEEL_MODEL" \
  -e docker \
  --n-attempts 15 \
  --job-name hw6-capability-15 \
  --jobs-dir .harbor/jobs \
  --yes
```

Create the analysis file:

```bash
uv run python scripts/analyze_harbor_job.py \
  .harbor/jobs/hw6-capability-15 \
  --case YOUR_CASE_ID \
  --out eval_results/YOUR_CASE_ID-15.json
```

The file reports:

| Runs observed | Metrics |
| --- | --- |
| `n = 5` | pass@1, pass@3, pass@5 |
| `n = 10` | pass@1, pass@3, pass@5 |
| `n = 15` | pass@1, pass@3, pass@5, pass@10, pass@15 |

The analysis uses the trial order stored in Harbor's `result.json`. It records each trial name, result, and the selected agent model so another person can reproduce each subset.

At a fixed `n`, pass@k should not decrease as `k` grows. At a fixed `k`, the estimate may move when you add runs because the new outcomes add evidence. If the estimate still moves substantially between 10 and 15 runs, state that 15 runs did not produce a stable estimate.

## Files to commit

1. `eval_cases/cases.jsonl`.
2. `tests/eval/passk.py`.
3. `.github/workflows/evals.yml`.
4. `ci-runs.json`.
5. `eval_results/<case-id>-15.json`.

Do not commit `.harbor/tasks`, API keys, or local Harbor job directories.

## Video

Record one continuous video of no more than 5 minutes:

1. Show 10 cases and the two or more Homework 4 failure modes they cover.
2. Show one regression and one capability case, including their five baseline results.
3. Explain pass@k and pass^k using your results.
4. Show the two GitHub Actions runs and explain the second result.
5. Show the capability result after 5, 10, and 15 observed runs.
