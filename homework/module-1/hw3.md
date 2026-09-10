# Homework 3, creating the support trace dataset

Homework 3 asks you to create a collection of Cartwheel support traces for Homework 4. A *scenario* is a planned support request with a recorded *expected result*, which states what the agent should do. When you run a scenario, Cartwheel records the conversation, model calls, and tool calls in a *trace*.

You will begin by deciding which kinds of support requests to include. You will run 30 scenarios first, so you can fix unclear requests and confirm that the agent produces some failures. You will then create the full set of 250 scenarios and export their traces. In Homework 4, you will use the traces to find repeated failure patterns.

## Working through the assignment with a coding agent

If you would like a coding agent to walk you through the assignment, paste the prompt below at the start of a session in your repository. The prompt assumes no programming background, so it suits an analyst or a product manager as well as an engineer. The agent generates the scenario files with the synthetic data skill; the handout's review points are where you decide.

> Walk me through Homework 3 in `homework/module-1/hw3.md` as an interactive tutorial. Read `AGENTS.md`, `homework/module-1/AGENTS.md`, the handout, `SPEC.md`, and `scenarios/skill/SKILL.md` first. I may not have a programming background, so assume nothing about what I know, and adapt once you see what I do know.
>
> I am driving. Work one step at a time, in the handout's order. Before each step, explain in plain language what you propose to do and why the assignment needs it, and show me the command you would run or the change you would make. Then wait for me to say go. Do not run a command, change a file, or generate anything until I have said so, and do not take several steps on one go ahead. Reading files to prepare a proposal is fine. Once I say go, do that step, show me the result, and explain what it means. Move on only when you are confident I understand the current step. One short question about what I expect to see, or what a result means, is enough to check; keep questions few, and do not turn the session into a quiz. Explain every unfamiliar term the first time it appears, using the actual files and outputs as examples. When a picture would help, draw one; a text diagram is fine.
>
> If something fails, read the error, explain it plainly, and propose a focused fix. Keep a short progress note of what is done and what is next, so we can resume later, and keep a checklist of every deliverable so nothing is skipped. Leave the assessments and the video to me. Do not call the assignment done until every file in the "Files to commit" list exists and the checks in the handout pass.
>
> Concepts I need to understand before we use them: what a scenario is and why it records an expected result, why expected results come from the database and the policy documents rather than from the model, what a dimension and a tuple are, why the coverage set and the challenge set are kept apart, and what the pilot is for. Stop at each review point in the handout, the dimension plan, the pilot review, and the final review, and let me make the decisions there. Diagrams that would help me: the path from dimensions to tuples to requests to expected results to traces, and the flow from the scenario file through the runner and the agent into Langfuse.

## Expected work

- Estimated time: 4 to 6 hours of your own work, excluding model response time.
- Run 30 pilot scenarios and review at least 10 results.
- Confirm at least five agent failures.
- Create and run 250 final scenarios on one model.
- Review 15 final scenarios, export the traces, and record a video of no more than 5 minutes.

The scenario runner sends requests one at a time, and each scenario needs several model calls. At the rate measured on the instructor run (about 8 seconds per scenario on `gpt-5.5`), the final 250 scenarios take about 35 minutes of unattended time and a few dollars of model usage. Budget for roughly 280 scenario runs in all, including the pilot.

## Preparation

Continue in the same repository from Homework 2. Homework 3 needs the Homework 2 endpoints, because the scenario runner sends every request through them, and the Homework 2 tool span attributes, because the run report counts roles and permission denials from them. Run the commands below from the repository root.

Homework 2 was optional. If you did not complete it, apply the reference implementation of its four functions before starting the server:

```bash
git apply homework/module-1/hw2-reference.patch
```

If you completed Homework 2, keep your own implementation and do not apply the patch.

Choose one model provider and confirm that its key is in `.env`. Set `CARTWHEEL_MODEL` in `.env` to the model you will use for every run in the assignment, before starting the server. The runner commands below also take the model name, so that each result records the model that produced it. Use the same value in both places.

Generate the local data and start Langfuse:

```bash
uv run python -m seed.generate
docker compose -f observability/docker-compose.yml up -d
```

Start the Cartwheel endpoint in a second terminal and leave it running:

```bash
uv run uvicorn server.app:app --port 8010
```

Read the following files before generating scenarios:

- `SPEC.md`, which defines the agent's required behavior.
- `scenarios/skill/SKILL.md`, which explains how to generate grounded scenarios.

Ask your coding agent to follow the scenario skill. You will review the plan and a sample of its scenarios yourself.

## Part A, plan the scenario dataset

You will decide which kinds of support requests the dataset must include. A *dimension* is one way the requests can differ, such as the user's role or intent. Planning the dimensions before generation helps the coding agent create a varied dataset.

Start a coding agent session from the repository root, then use the following prompt:

> Read `scenarios/skill/SKILL.md` and `SPEC.md`. Query the `data_quality_cases` table. Propose the scenario dimensions and their possible values, then stop so I can review them before generation.

The plan must include the following dimensions:

- Authenticated role.
- User intent.
- The record involved (an order and its state, a product, a store policy page, or none).
- Applicable platform or store policy.
- Number of tool calls needed.
- Request difficulty.

Add another dimension only when `SPEC.md` or the seeded data provides a reason for it. Each scenario also records its turn count, which equals one plus the number of followups; the validator checks it.

The *coverage set* includes ordinary and difficult requests across every important dimension. The *challenge set* includes requests that are intentionally difficult, e.g., missing information, a correction across turns, a store policy override, an authorization boundary, or a damaged record.

Record the group in `scenario_group` as either `coverage` or `challenge`. Do not include prompt injection or malicious documents, because Homework 8 covers deliberate attacks.

The seeded database contains six deliberately damaged records. Read them before planning the challenge set:

```bash
sqlite3 -header -column data/cartwheel.db \
  'SELECT case_id, entity_type, entity_id, description, expected_handling FROM data_quality_cases ORDER BY case_id;'
```

A scenario about a damaged record must use an authenticated user who may access the record. It must also record the matching `case_id` in `data_quality_case_id`. Scenarios that do not target a damaged record should set `data_quality_case_id` to `null`.

## Part B, run a pilot and confirm failures

You will run a small pilot before creating all 250 scenarios. The pilot gives you a cheaper way to find invalid or repetitive scenarios, and it confirms that the agent produces failures you can study in Homework 4.

Have the coding agent generate `scenarios/pilot_scenarios.jsonl` with the skill: 30 scenarios with broad role and intent coverage, including ordinary requests and difficult requests from the dimensions in Part A.

Each scenario must record what the agent should do and the source that supports the answer. For example, if an order has no delivery date, the scenario records that the agent must not calculate a return deadline and cites the damaged record. The scenario skill shows the required JSON fields.

Validate the file, then run the scenarios on your selected model. Replace `YOUR_MODEL` with the value of `CARTWHEEL_MODEL` in `.env`:

```bash
uv run python -m scenarios.validate scenarios/pilot_scenarios.jsonl

uv run python -m scenarios.runner scenarios/pilot_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/pilot-results.jsonl
```

Review at least 10 pilot results in Langfuse. Start with difficult scenarios and cases where the model used an unexpected tool, changed data, or gave an answer that conflicts with the recorded expected result.

Create `scenarios/pilot_review.jsonl` with one record for each scenario you review. Record:

- `scenario_id`.
- `scenario_valid`, as `true` or `false`.
- `confirmed_failure`, as `true` or `false`.
- `evidence`, naming the database value, policy, tool result, or requirement that supports your decision.
- `scenario_change`, or `null` when the scenario needs no revision.

Count a failure only when `scenario_valid` is `true` and the observed behavior conflicts with the recorded expected result or a clear requirement in `SPEC.md`.

The pilot review must contain at least five confirmed failures. If the first 30 scenarios contain fewer than five, add 20 challenge scenarios, reset the data with `uv run python -m seed.generate`, and run the pilot again. You may instead choose a lower capability model from the same provider. Use the selected model for the final run as well.

Do not name or group failure modes in Homework 3. Homework 4 begins the open coding and taxonomy work.

## Part C, create and review the final scenarios

You will use the pilot review to create the final scenario file. Revise invalid or repetitive scenarios, then generate more scenarios from the plan in Part A.

Save the final dataset in `scenarios/support_scenarios.jsonl`. It must contain:

- 175 scenarios with `scenario_group` set to `coverage`.
- 75 scenarios with `scenario_group` set to `challenge`, including five for each of the six damaged records.

Give every final scenario a new identifier, distinct from the pilot identifiers. The export in Part E selects traces by scenario identifier, so a reused identifier would pull in the pilot run's traces as well.

In Homework 4, you will review 100 traces and search the remaining traces for similar failures. The 250 scenario requirement provides enough examples for both steps. Other evaluation projects may need fewer or more traces.

Do not select a scenario only because a model failed on the exact request. Use the underlying dimension, such as a store policy override or missing order data, to generate new cases.

Review 15 scenarios before the full run. Include both scenario groups, all three roles, and every intent.

Save each decision in `scenarios/support_review.jsonl` with `scenario_id`, `decision`, `reason`, and `change`. Use `accept`, `revise`, or `reject` for the decision. Apply every revision and replace every rejected scenario.

Select 50 of the final scenarios for a later comparison. Include both groups and all three roles, then save the records in `scenarios/monitoring_scenarios.jsonl`. Homework 7 will run the same requests after the agent changes.

Validate the final file:

```bash
uv run python -m scenarios.validate scenarios/support_scenarios.jsonl --final
```

The command checks the schema, unique identifiers, group counts, turn counts, duplicate conversations, and damaged record coverage. Repair every reported error before starting the final run, because the run makes model calls for every scenario.

## Part D, run the final dataset

You will run all 250 scenarios on the model selected during the pilot. Using one model makes the final traces comparable.

Reset the development data first. The pilot changed order states through refunds and cancellations, and the expected outcomes assume the seeded state:

```bash
uv run python -m seed.generate
```

Then run the final set:

```bash
uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/final-results.jsonl
```

Check the runner output for errors. A scenario whose request times out or fails is recorded with a status other than `completed`. Fix the cause, then rerun only the affected scenarios into the same output file:

```bash
uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/final-results.jsonl --resume
```

The `--resume` flag keeps every completed record and reruns the scenarios whose record is missing or has another status. To rerun named scenarios instead, e.g., because Part E reports a scenario without a trace, pass `--ids support-0153,support-0201`; their records replace the earlier ones. A rerun does not reset the data, so before rerunning a scenario that refunds or cancels an order, check that the first attempt did not already change the order. If many scenarios failed, reset the data and run the full set again.

Confirm that all 250 runs completed:

```bash
jq -s 'group_by(.status) | map({status: .[0].status, count: length})' \
  scenarios/final-results.jsonl
```

Keep the coverage and challenge counts separate when you summarize the run. The challenge set contains more difficult requests by design.

## Part E, check and export the traces

You will check that the run completed, then export the traces for Homework 4.

```bash
docker compose -f observability/docker-compose.yml exec -T clickhouse \
  clickhouse-client --user clickhouse --password clickhouse --database default \
  --multiquery --format PrettyCompact < reports/smoke.sql \
  | tee reports/smoke-output.txt
```

The report counts traces per scenario and per role, errors, escalations, tokens and cost, the longest traces, tool calls, and permission denials. It describes what ran, not how well the agent did.

```bash
uv run python -m scenarios.export_langfuse \
  scenarios/support_scenarios.jsonl traces/support_traces.json
```

The command fails when a final scenario has no matching trace, which happens when the server stopped before its spans were sent. Rerun the scenarios it names with `--ids` (Part D) until the export succeeds. A successful export contains traces for all 250 final scenario identifiers, which gives Homework 4 more than the required 200 traces.

Open three exported traces and confirm that each trace contains the conversation, model name, tool activity, and its scenario identifier in `cartwheel_scenario_id`. Include one challenge scenario and one scenario with more than one turn. You do not need to write failure notes or create a taxonomy.

## Files to commit

- `scenarios/pilot_scenarios.jsonl`
- `scenarios/pilot-results.jsonl`
- `scenarios/pilot_review.jsonl`
- `scenarios/support_scenarios.jsonl`
- `scenarios/support_review.jsonl`
- `scenarios/monitoring_scenarios.jsonl`
- `scenarios/final-results.jsonl`
- `reports/smoke-output.txt`
- `traces/support_traces.json`

## Video

Record one continuous screen video of no more than 5 minutes. Show the following work:

1. Show one pilot scenario that failed, then show the expected result and evidence.
2. Show one final scenario that you revised after review.
3. Open one complete final trace and show its scenario identifier and tool activity.
4. Regenerate the number of final scenario identifiers:

```bash
jq '[.traces[].cartwheel_scenario_id] | unique | length' \
  traces/support_traces.json
```

Every statement in the video must agree with the committed files and the Langfuse traces shown on screen.
