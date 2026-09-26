# Homework 7, monitor agent behavior after deployment

Homework 6 checks known cases before a change is merged. In Homework 7, you will measure one failure mode after deployment. You will compare two complete runs of the same 50 scenarios, estimate the failure rate with a frozen Homework 5 judge, and schedule the monitor in GitHub Actions. Cartwheel has no live traffic, so the two runs stand in for two deployment periods.

## Work through the assignment with a coding agent

Paste this prompt at the start of a coding agent session in your repository:

> Guide me through Homework 7 in `homework/module-3/hw7.md`, one part at a time. Read `AGENTS.md`, the handout, the files in `monitoring/`, and my Homework 3, Homework 5, and Homework 6 artifacts before changing files. Use one frozen judge that I chose to use after Homework 5. Preserve its prompt, model, inputs, and verdict parser. Compare the 50 scenarios saved in Homework 3 with one new run of the same scenarios and Cartwheel model. Keep the random sample separate from the risk groups because only the random sample estimates the failure rate. Before any paid run, show me the model, number of agent runs, and number of judge calls, then wait for my approval. Never print or commit secret values. Leave the dashboard interpretation and final video to me.

## What you will submit

1. Two comparable 50 scenario runs for one Cartwheel model.
2. One monitor that samples traces and runs a frozen judge.
3. A two period failure rate history and chart.
4. Langfuse scores and a dashboard for the monitored failure mode.
5. A scheduled GitHub Actions workflow.
6. A video of no more than 5 minutes.

## Tools

1. Langfuse stores traces and scores.
2. DocETL runs the frozen Homework 5 judge.
3. GitHub Actions runs the monitor each day.

## Preparation

Start from your completed Homework 6 repository. Confirm that `scenarios/monitoring_scenarios.jsonl` contains the 50 scenarios selected in Homework 3.

If you did not finish Homework 6, apply the reference mechanics:

```bash
git lfs pull
git apply homework/module-3/hw6-reference.patch
```

The patch implements the pass metrics and Harbor workflow. It does not invent evaluation cases or model results.

Choose one judge that you froze, tested, and decided to use in Homework 5. The monitor must use the exact prompt, model, inputs, and verdict parser that you validated. Confirm that you can call the frozen model before you start.

If you did not finish Homework 5 or did not choose a judge, apply the reference judge:

```bash
git lfs pull
git apply homework/module-3/hw5-reference.patch
```

The reference judge detects `unsupported_policy_claim` and is pinned to `claude-opus-4-6`. Confirm that your course credits or provider account cover this model. A run with the reference judge needs `ANTHROPIC_API_KEY`.

Do not point the same prompt at another model and reuse the saved test results. A different model is a different judge, so you must rerun the Homework 5 held out validation and freeze the new judge first. The reference bundle does not include the held out trace contents needed to validate another model. If you cannot use the reference model, ask the instructors for a supported reference judge before starting Homework 7.

Set the Langfuse variables and the provider keys for the Cartwheel model and frozen judge in `.env`. Never put secret values in a committed file.

Read these starter files before you write the monitor:

```text
monitoring/sample.py
monitoring/correct.py
monitoring/run_judges.py
monitoring/write_scores.py
monitoring/chart.py
```

Install the dependencies from the repository root:

```bash
uv sync
```

## Part A, create two comparable periods

Use the 50 scenarios in `scenarios/monitoring_scenarios.jsonl` for both periods. Use the same Cartwheel model.

The first period is the original Homework 3 run. Find one complete time range in Langfuse that contains the 50 scenario IDs. Do not combine separate retries.

The second period is one new run of the current agent. Reset the database, start the server, and record the UTC time before and after the run:

```bash
uv run python -m seed.generate
uv run uvicorn server.app:app --port 8010
```

```bash
uv run python -m scenarios.runner scenarios/monitoring_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/hw7-after-results.jsonl
```

Confirm that all 50 new scenario results completed. Both time ranges must contain every scenario ID. A scenario with several turns may create several traces.

Record the UTC start and end time for both periods in `monitoring/config.json`:

```json
{
  "judge_id": "YOUR_FROZEN_JUDGE_ID",
  "judge_mode": "YOUR_FAILURE_MODE",
  "model": "YOUR_CARTWHEEL_MODEL",
  "random_rate": 0.2,
  "risk_groups": ["policy_lookup"],
  "threshold": 0.15,
  "periods": [
    {
      "label": "before",
      "from": "START_TIME_UTC",
      "to": "END_TIME_UTC"
    },
    {
      "label": "after",
      "from": "START_TIME_UTC",
      "to": "END_TIME_UTC"
    }
  ]
}
```

Choose at least one risk group from `DEFAULT_RISK_GROUPS` in `monitoring/sample.py`. The supplied groups select conversations with a policy lookup, a write action, or more than one user turn. Choose a threshold before you inspect either period's judge results. The threshold is the corrected failure rate that starts a new error analysis.

The monitor must reject a period if any of the 50 scenario IDs is missing or if an eligible trace uses a different model. Do not combine separate retries into one period.

## Part B, sample and judge each period

Implement `select_traces` in `monitoring/sample.py`.

First group the Langfuse traces by scenario ID. Combine the ordered trace text into one conversation record per scenario. Use the final trace ID as the record ID so Langfuse can receive the score. The period must produce exactly 50 conversation records.

For each period, select:

1. A uniform random sample of 20 percent of the conversation records, which produces 10 random records in each comparison period.
2. Every conversation record in each configured risk group.

Risk groups help you inspect traces that may fail more often. They do not estimate the overall failure rate because they are not a random sample.

A conversation can appear in both selections. Judge the union once, then keep its random and risk memberships separate.

Complete `monitoring/run.py`. It must:

1. Read one period from `monitoring/config.json`.
2. Fetch the matching traces from Langfuse.
3. Validate the scenario IDs and Cartwheel model, then build the 50 conversation records.
4. Record the tool names and number of user turns for each conversation. Build risk groups from this trace evidence. Do not infer a risk field from the agent reply.
5. Prepare the normalized conversation text used by Homework 5. Include the ordered turns and tool evidence. Do not include human labels, failure annotations, or scenario metadata in the text.
6. Call `select_traces`.
7. Show the number of selected traces and judge calls before running the judge.
8. Call `judge_sample` once on the union, using the configured judge ID.
9. Save the random and risk verdicts separately.

Use 1 when the failure is present and 0 when it is absent.

Run the sampling test:

```bash
uv run pytest --runxfail tests/test_hw_holes.py -k hw7_sampling
```

## Part C, estimate the failure rate

The judge makes mistakes, so its raw flag rate is not the final estimate. Implement `corrected_mode_prevalence` in `monitoring/correct.py`. Use only the random sample.

The monitor uses 1 for failure and 0 for pass. Under this convention:

1. Failure sensitivity is the fraction of human labeled failures that the judge flags. The value equals the Homework 5 test TNR because Homework 5 treated Pass as the positive label.
2. Pass specificity is the fraction of human labeled passes that the judge leaves unflagged. The value equals the Homework 5 test TPR.

Use `judge_test_data` from `monitoring/run_judges.py` to load the frozen judge's held out test labels and predictions. Apply the Rogan Gladen correction and a seeded percentile bootstrap interval.

Implement `build_score_records` in `monitoring/write_scores.py`. Write these scores:

1. `<mode>_verdict` for traces in the random sample.
2. `<mode>_risk_verdict` for traces selected by a risk group.
3. `<mode>_corrected_prevalence` once for the period.

The score IDs must be stable. If a trace is in both selections, it receives both verdict scores. Only the random verdicts contribute to prevalence.

Run the focused tests:

```bash
uv run pytest --runxfail tests/test_hw_holes.py -k "hw7_corrected or hw7_score"
```

Run the monitor for both periods:

```bash
uv run python -m monitoring.run --period before
uv run python -m monitoring.run --period after
```

Save one line per period in `monitoring/history.jsonl`. Each record must include:

1. The period label, judge ID, and Cartwheel model.
2. The Langfuse trace, conversation, random sample, and risk sample counts.
3. The raw rate, corrected rate, interval, failure sensitivity, and pass specificity.

Use `prevalence_chart` from `monitoring/chart.py` to create `monitoring/prevalence.svg`. The chart must show both periods, their intervals, and the configured threshold.

Both periods contain 50 conversation records, but their Langfuse trace counts can differ because conversations can have different numbers of turns.

Run the `after` period a second time. Confirm that Langfuse updates the existing score IDs instead of creating duplicate scores.

## Part D, schedule the monitor

Create `.github/workflows/monitor.yml` with a daily schedule and a manual trigger. The job must:

1. Install the repository dependencies.
2. Read traces from the previous 24 hours and group them by `meta.session_id` into conversations.
3. Run the same sampling, judging, correction, and score writing code.
4. Upload the local monitoring output as a workflow artifact, even when the job fails.

If the time window contains no eligible conversations, the command must record a zero count and exit successfully without calling the judge.

The scheduled command must support this form:

```bash
uv run python -m monitoring.run --last-hours 24
```

Store `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and the frozen judge's provider key as GitHub Actions secrets. Store `LANGFUSE_HOST` as a repository variable. A GitHub hosted runner needs a Langfuse host it can reach. Use a self hosted runner if you keep Langfuse on your computer. The workflow does not need the Cartwheel model provider key because it reads existing traces.

Create a Langfuse dashboard that shows:

1. The random sample verdict score over time.
2. The risk verdict score over time.
3. The traces flagged by either score.

Run the workflow manually once and confirm that it completes.

## Part E, interpret the result

Add `monitoring/README.md` with four short answers:

1. Did the corrected failure estimate move between the two periods?
2. Do the intervals support a conclusion, or is the result uncertain?
3. What did the risk groups reveal that the random estimate did not?
4. What action should happen if the estimate crosses the threshold?

A threshold crossing should start error analysis on the flagged traces. Confirmed failures should become new evaluation cases in the Homework 6 suite.

## Files to commit

Commit these files:

```text
monitoring/config.json
monitoring/run.py
monitoring/sample.py
monitoring/correct.py
monitoring/write_scores.py
monitoring/history.jsonl
monitoring/prevalence.svg
monitoring/README.md
scenarios/hw7-after-results.jsonl
.github/workflows/monitor.yml
```

Do not commit `.env`, API keys, raw Langfuse exports, or generated database files.

## Video

Record a video of no more than 5 minutes. Show:

1. The two periods and their shared scenario set and model.
2. The random sample and risk groups.
3. The raw and corrected estimates with their interval.
4. The Langfuse dashboard.
5. One successful scheduled workflow run.
6. What you would do after a threshold crossing.
