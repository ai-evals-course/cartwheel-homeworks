---
name: synthetic-trace-generation
description: >
  Generate grounded, diverse user interactions and run them against an
  instrumented application to create a verified trace dataset.
---

# Synthetic trace generation

Use the workflow when production traces are unavailable or do not cover enough
behavior for error analysis. The workflow assumes that the application, its
behavior specification, and authoritative data already exist.

## Inputs

- Behavior specification or rubric.
- Authoritative data, policies, deterministic functions, or simulator.
- Executable application interface.
- Trace destination and export path.
- Executable scenario validator.
- Dataset size, model configuration, time budget, and cost budget.

## Invariants

1. Ground expected outcomes in authoritative sources. Neither the request
   generator nor the application under evaluation is its own oracle.
2. Keep hidden expected answers out of request generation prompts.
3. Generate and review requests before running the application.
4. Preserve ordinary coverage while adding difficult cases.
5. Preserve human decisions at the dimension and request review gates.

## Steps

### 1. Verify the application and tracing

Read the specification, tool contracts, permission rules, and ground truth
sources. Run one inexpensive request and verify that its trace contains:

- user and application messages;
- model identity and settings;
- tool calls and results;
- a stable scenario identifier;
- token usage and errors where available.

Do not start bulk generation until authentication, tracing, and state reset work.

### 2. Define dimensions

Derive dimensions from the specification, data, and intended analysis. Common
dimensions include role, intent, entity and state, applicable rule, expected
tool path, difficulty, user language style, and conversation length.

Every dimension needs a reason. Include varied language styles when response
quality matters, for example terse fragments, typos, confusion, frustration,
operational shorthand, and requests for a short answer.

Show the dimension plan and values to a person. Stop for approval.

### 3. Build grounded plans

Sample valid combinations of approved dimension values. Do not enumerate the
full Cartesian product. Count selected values and deliberately include rare or
risky combinations.

Maintain two pools:

- `coverage`: ordinary cases that repeatedly exercise important values;
- `challenge`: valid boundary conditions, missing information, corrections,
  permission boundaries, inconsistent records, and other supported difficulty.

Select concrete records from ground truth. Verify access permissions. Ensure
state changing scenarios target distinct records unless interaction is
intentional.

### 4. Record expectations

Compute the expected result before generating user language.

Use an objective expectation when authoritative data or deterministic code fixes
the answer or action. Record the outcome, reason, source type, and stable source
reference.

Use a human judgment expectation when several responses could satisfy the
requirement. Record a precise criterion and the supporting requirement or
rubric.

Store expectations in scenario records, but do not expose hidden facts or
expected answers to request generators.

### 5. Generate user interactions

Generate requests separately from application execution. Use independent model
calls per scenario, or small batches assigned to separate subagents when the
coding environment provides them. Record the generation method and model. Do
not claim to use subagents when none are available.

Give the generator only the role, user goal, selected style, user visible facts,
and required length. Do not fill the dataset with a shared opening or followup
template.

For multi-turn interactions:

- write one opening and an ordered list of exact user followups;
- keep every followup plausible for an unknown preceding response;
- develop one coherent issue through clarification, correction, pressure, or a
  decision;
- preserve the assigned style rather than polishing every user;
- omit stage directions, persona notes, evaluator language, and hidden facts.

Use the project's turn limit. Repeated requests to check, compare, cite,
confirm, or summarize do not create useful length.

### 6. Check and review requests

Use an independent critic model or subagent when available. The critic may
rewrite language, but must preserve the grounded plan, expectation, and assigned
style.

Run mechanical checks for:

- schema and turn count errors;
- duplicate conversations or repeated utterances;
- invented identifiers, amounts, dates, entities, or personal facts;
- impossible role and record combinations;
- accidental or repeated write requests;
- followups that assume a specific unseen response;
- references to tools, traces, prompts, tests, or expected outcomes;
- missing coverage values.

Regenerate weak interactions from their plans. Run the executable validator.

Show a person complete conversations, including the longest examples, both
pools, all roles and styles, a state changing case, and difficult cases. Stop
until the person accepts or revises the language.

### 7. Run a pilot

Reset mutable state. Run a small representative set with one fixed application
model configuration. Persist status, errors, duration, observed messages, and
model identity for every scenario.

Verify trace completeness and scenario identifiers. Compare results with
recorded expectations. Treat provider refusals, timeouts, transport errors, and
missing traces as execution failures, not application quality failures.

Revise invalid scenarios and enrich challenge cases from difficult dimensions,
not by copying requests that happened to fail.

### 8. Run the final set

Repeat generation, criticism, human review, and validation for the final set.
Reset mutable state immediately before execution and keep the application model
configuration fixed.

Sequential execution is safest for shared mutable state. Use parallel execution
only when state changes are independent and provider limits, timeouts, tracing,
and the cost budget support the selected concurrency.

Rerun missing or failed scenarios without deleting completed run records.

### 9. Verify and export

Before error analysis:

1. Count completed scenario identifiers.
2. Confirm that every completed scenario has the expected traces.
3. Inspect traces across roles, lengths, styles, and scenario groups.
4. Confirm that messages, tool activity, model metadata, usage, and scenario
   identifiers are present.
5. Export the trace set with generation and application model provenance.
6. Report coverage and challenge results separately.

The workflow ends with a verified trace dataset. Failure taxonomy discovery and
quality measurement belong to the subsequent error analysis workflow.

## Conceptual scenario record

Use the project's executable schema. Preserve at least the following concepts,
even when field names differ:

```json
{
  "id": "scenario-0042",
  "scenario_group": "challenge",
  "dimensions": {
    "role": "user_role",
    "intent": "requested_action",
    "record_state": "relevant_state",
    "difficulty": "boundary",
    "user_style": "terse_fragmentary",
    "turn_count": 3
  },
  "opening_message": "First user message",
  "followups": ["Second user message", "Third user message"],
  "expected": {
    "evaluation": "objective",
    "outcome": "expected result",
    "reason": "reason derived from ground truth",
    "source": {
      "type": "deterministic_oracle",
      "reference": "stable source reference"
    }
  }
}
```

For human judgment, replace `outcome` and `reason` with a precise `criterion`
and reference the supporting requirement or rubric.

## Limitations

Synthetic users are usually more relevant and consistent than production users,
even when generation prompts request varied styles. Synthetic traces complement
rather than replace production traffic.

Challenge enrichment changes failure frequency. A combined coverage and
challenge failure rate is not an estimate of production prevalence.

Scripted followups cannot react to an exact preceding response. Adaptive user
simulation requires a runtime user model with separate evaluation and cost.
