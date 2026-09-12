---
name: synthetic-trace-generation
description: >
  Generate grounded, diverse user interactions and run them against an
  instrumented application to create a verified trace dataset for error
  analysis.
---

# Synthetic trace generation

This skill generates a dataset of agent traces when production traces are unavailable or do not cover enough behavior for error analysis. The workflow applies to any application that accepts user requests and produces observable behavior, including support agents, coding agents, research agents, and browser agents. The examples below use the Cartwheel support agent as a concrete illustration, but the method is the same for any application with a behavior specification and authoritative data.

## Why not generate user messages directly?

Asking a model to "generate 250 questions for my application" produces narrow data. The model tends to repeat the most common request type and ignores categories that appear less often in its training data. For a support agent, the model produces dozens of order status questions and very few refund boundary cases, store policy overrides, or permission denials. For a coding agent, the model produces many "write a function" requests and very few "fix a failing test in a large repository" or "refactor across three files." Adding more rows does not fix the problem, because more rows of the same kind do not introduce missing kinds.

The synthetic data approach fixes the problem by defining the kinds of variation first, then generating requests that cover each kind. A *scenario* carries both a user request and an expected outcome grounded in the application's authoritative data. The expected outcome is what makes the trace useful for finding failures: without a recorded answer key, a reviewer has nothing to compare the agent's behavior against.

## What a scenario contains

A scenario is a planned interaction with four parts:

1. **A tuple of dimension values** that describe what kind of request the interaction represents. Each dimension is one source of variation that changes the expected behavior or the execution path.
2. **User messages** (an opening message and optional followups) written in natural language from the tuple, as a real user would type them. The messages do not state hidden facts from the tuple.
3. **An expected outcome** computed from the application's authoritative data, stating what the agent should do and citing the source that determines the answer.
4. **Metadata** linking the scenario to its group (coverage or challenge) and its identifier.

The scenario is an input to the runner, not a trace. Running a scenario through the instrumented application produces two separate outputs: a result record for the attempted interaction, and traces from the application's instrumentation. The scenario identifier appears on every trace so the plan, the result, and the traces are always linked.

## Invariants

These rules hold throughout the workflow. Each one prevents a specific mistake.

1. **Ground expected outcomes in authoritative sources.** The expected outcome comes from the application's data, rules, or specification, not from the model's answer. If the model's own answer were the answer key, a wrong answer would look correct. For the Cartwheel agent, sources include the database (SQL), the return policy in `facts.yaml`, the policy documents, and the data quality table. For a coding agent, sources might include the test suite, the type checker, or a known correct output.

2. **Keep hidden expected answers out of generation prompts.** The model that writes the user's message receives only facts the simulated user would know and never the hidden expected outcome. A shopper asking about a return does not know the exact return window or whether the refund will be approved. A developer asking a coding agent to fix a bug does not state the root cause in the request.

3. **Write and review conversation plans before running the application.** Each application run costs model calls for every scenario in the file. Catching an invalid scenario before the run saves the cost of running it. Catching a bad user message before the run saves the cost of a trace that tests the wrong thing.

4. **Preserve ordinary coverage while adding difficult cases.** Reporting the coverage and challenge sets separately prevents routine successes from hiding failures at the edges.

5. **Preserve human decisions at the dimension and request review gates.** The human approves the dimensions before generation starts, and reviews a sample of complete interactions before the runner starts. The coding agent proposes, generates, and validates, but the human decides what the dataset should contain.

## Step 1: Verify the application and tracing

Before generating any scenarios, confirm that the application runs and that its traces are complete. Send one inexpensive request and verify that the resulting trace contains:

- The user message and the agent's response.
- The model identity.
- Tool calls and their results.
- A scenario identifier attribute on the trace.
- Token usage, if available.

Do not start bulk generation until authentication, tracing, and any state reset all work.

**Cartwheel example.** Start the server and Langfuse, send "What's the status of my last order?" as a shopper, and confirm that the Langfuse trace contains the conversation, `gpt-5.5` as the model, the `get_order` tool call and its result, and a `cartwheel.scenario_id` attribute. Reset the database with `uv run python -m seed.generate`.

## Step 2: Define dimensions of variation

A *dimension* is one named source of variation in the requests. A useful dimension changes the expected behavior, the execution path, or a quality requirement. Do not add a dimension merely because it is easy to vary.

Read the application's behavior specification, its data, and any ground truth sources to identify the dimensions. The dimensions depend on the application:

| Application | Useful dimensions | Why they matter |
| --- | --- | --- |
| Support agent | user role, intent, record state, applicable policy, tools needed, difficulty, user style | Permissions, tools, rules, and response requirements vary by role, intent, and record state. |
| Coding agent | task type, language, repository size, test state, ambiguity | Context needs, tool paths, and completion checks vary by task and codebase. |
| Research agent | question type, source availability, recency, conflicting evidence | Retrieval, synthesis, and citation requirements vary by what the agent can find. |
| Browser agent | workflow, authentication state, page state, interruption point | Available actions and recovery behavior vary by what the page shows. |

**Cartwheel example.** The Cartwheel specification, the seeded data, and the policy documents motivate seven dimensions:

| Dimension | Values | Why it matters |
| --- | --- | --- |
| **Role** | shopper, merchant, support | Different roles have different permissions. A shopper can view their own orders, a merchant can view their store's orders, and support can view any order. |
| **Intent** | order status, refund, cancellation, policy question, product search, dispute, out of scope | Each intent exercises different tools. A refund calls `get_order` and `issue_refund`, while a policy question calls `search_help_center`. |
| **Record involved** | an order (in window, past window, above threshold, placed, shipped), a product, a store policy page, none | The record state determines the expected outcome. An order delivered 15 days ago is eligible for a return, while one delivered 45 days ago is not. |
| **Applicable policy** | platform rule, store override, none | Some stores override the platform return window. Juniper Home Goods has a 14-day window instead of the platform's 30 days. |
| **Tools needed** | none, one lookup, several calls | A policy question needs one lookup, while a refund needs several calls. |
| **Difficulty** | well specified, ambiguous, missing information, boundary | An ambiguous request describes a product without an order number. A boundary request sits exactly at the return window or the refund threshold. |
| **User language style** | neutral\_conversational, terse\_fragmentary, typo\_heavy, confused\_rambling, frustrated\_impatient, repetitive\_pressuring, operational\_shorthand, requests\_short\_plain\_answer | The specification requires direct and respectful responses regardless of user style. The validator enforces one of these exact values. |

Each scenario also records its **turn count** (1 through 25), which equals one plus the number of followups. The turn count is set per scenario through the followups list rather than as a separate dimension.

### Proposing dimensions to the human

Do not present a finished dimension list. Start by asking the human to brainstorm in their own words: give one example dimension with a reason (e.g., "One dimension is the user's role, because different roles have different permissions. What other sources of variation do you think would change the agent's behavior?"). Let the human type their own ideas freely. Do not offer multiple choice options for this step. Wait for the human to name at least two dimensions before you propose additional ones.

After the human has contributed dimensions, read the specification, the data, and any ground truth sources to fill in gaps the human may have missed. Present the combined list (the human's dimensions and your additions, each with a reason) and ask the human to approve, revise, or add more. Do not generate scenarios until the dimensions are approved.

Any dimension needs a reason from the specification or the data. A dimension without a reason from either source is unlikely to change the expected behavior.

## Step 3: Build grounded conversation plans

Sample valid combinations of the approved dimension values. Do not enumerate the full Cartesian product, because many combinations are invalid and the product grows quickly. Instead, count how often each value appears and deliberately include rare and risky combinations.

### Two pools

Maintain two separate pools:

- **Coverage**: ordinary requests that exercise every important dimension value.
- **Challenge**: intentionally difficult requests that test boundaries, damaged records, permission edges, corrections across turns, and missing information.

The specific counts depend on the project. Report results for the two pools separately, because mixing them lets the routine majority hide failures at the edges.

**Cartwheel example.** The Cartwheel homework uses 175 coverage scenarios and 75 challenge scenarios. Five challenge scenarios target each of the six data quality cases in the database. The coverage set includes straightforward order status checks and routine policy questions. The challenge set includes store policy overrides, refund threshold boundaries, and orders with missing or contradictory data.

### Selecting records from the data

Each scenario that involves a record from the application's data must reference a real record. Query the data to find a matching record, and verify that the simulated user has permission to access the record under the specified role.

Scenarios that change state (for example, refunds or cancellations) should target distinct records, so that one scenario's side effects do not invalidate another scenario's expected outcome.

### Data quality cases

If the application's data contains deliberately damaged or edge-case records, query them and include challenge scenarios that exercise the expected handling.

**Cartwheel example.** The seeded database contains six damaged records in the `data_quality_cases` table. For example, order 8002 has a delivered status but no delivery date. A scenario about that order records that the agent must not compute a return deadline from a missing date, and cites `dq-order-missing-delivery-date` as the source.

## Step 4: Compute expected outcomes

Compute the expected outcome for each scenario before generating the user's message. The expected outcome states what the agent should do, and cites the authoritative source that determines the answer.

### Objective expectations

Use an objective expectation when the data or a deterministic rule fixes the answer.

**Cartwheel example:**

- **Order 3980**, delivered 2026-05-17, Blue Heron Ceramics, no store override. The platform return window is 30 days from delivery (`facts.yaml`). Today is 45 days after delivery. **Expected outcome:** refund denied. **Source:** the return policy in `facts.yaml` and the order row.
- **Order 6974**, delivered 17 days ago, Juniper Home Goods, 14-day store override. **Expected outcome:** refund denied (the store override is stricter). **Source:** the store policy document for Juniper Home Goods.
- **Order 8002**, delivered status but no delivery date (data quality case `dq-order-missing-delivery-date`). **Expected outcome:** do not compute a return deadline. **Source:** the data quality table.

Record the outcome, a short reason, the source type, and a stable reference to the source. For Cartwheel, the source types are `sql`, `eligibility_function`, `policy_document`, and `data_quality_table`. Other applications define their own source types based on their authoritative data.

### Human judgment expectations

Use a human judgment expectation when several responses could satisfy the requirement. Record a precise criterion describing what a correct response looks like, and cite the relevant specification requirement.

**Cartwheel example.** When a shopper asks a vague question and the agent asks for clarification, the expected behavior is "a clear and respectful explanation of what information is needed" rather than one exact sentence. The criterion cites RESP-3 and RESP-4 from SPEC.md, with source type `specification`.

## Step 5: Generate conversations

Generate the user messages separately from running the application. The generation model writes the user's messages from the tuple and the user-visible facts, but never sees the hidden expected outcome.

### One call per conversation

Use one independent model call per conversation, and launch the calls concurrently with a bounded pool of at least two workers. Parallel coding subagents may provide the pool when the environment supports them. Do not ask one model call to draft the whole dataset, because a single call produces conversations that share structure and phrasing.

### The generation prompt

Give the generation model the role, the user's goal, the selected style, the user-visible facts, and the required number of turns. Do not include identifiers, exact dates, internal rules, or the expected outcome.

**Cartwheel example.** To generate the request for a past-window refund scenario:

```
You are simulating a customer messaging the Cartwheel support agent.
Write a realistic one sentence message from the user described below.
Write naturally, as if the user is typing into a chat window. Do not
state every fact from the tuple. Do not mention the order number.

Role: shopper
Intent: refund
Record: a vase from Blue Heron Ceramics, purchased about six weeks ago
User style: confused, rambling
```

The model might produce: "Can I return the vase I got a while ago? I never used it."

The message leaves out the order number, the exact delivery date, and the return window, because a real user would not know or state those facts.

### Multi-turn conversations

For scenarios with more than one turn, write one opening message and an ordered list of exact followup messages. Each followup must be plausible without knowing the agent's preceding response, because the followups are scripted before the agent runs. A followup like "Yes, go ahead with the refund" assumes the agent offered a refund, which it might not have. Instead, write followups that develop one coherent issue through clarification, correction, or added detail, such as "Actually, I think it was the desk organizer, not the vase."

Preserve the assigned language style in the followups. A terse user stays terse. A frustrated user stays frustrated. Do not polish every user into polite grammatical prose.

### Critic pass

After generating all conversations, run an independent critic call for each conversation concurrently. The critic checks for:

- Invented identifiers, amounts, dates, or entity names that do not match the selected data record.
- Followups that assume a specific agent response.
- Conversations that share a template opening or followup.
- Language that a real user would not produce, such as quoting internal policy names or rule numbers.
- References to tools, traces, prompts, or expected outcomes that break the simulation.

The critic may rewrite language but must preserve the grounded plan, the expectation, and the assigned style.

## Step 6: Review conversations with the human

Run the project's executable validator on the generated file. Fix every reported error before proceeding.

**Cartwheel example:**

```bash
uv run python -m scenarios.validate scenarios/pilot_scenarios.jsonl
```

The Cartwheel validator checks the JSON schema, required tuple fields, unique identifiers, turn counts, duplicate conversations, and the expected-outcome format.

Then show the human a sample of complete conversations for review. Include the longest conversation, both scenario groups, every role, a state-changing scenario, a difficult scenario, and several user styles. The human reads the opening and every followup and decides whether the language is realistic, the followups make sense without seeing the agent's response, and the expected outcome matches the selected record.

Do not start the runner until the human accepts the conversation sample.

## Step 7: Run a pilot

Reset any mutable application state first, because earlier runs may have changed it.

Run a small representative set (about 30 scenarios) on one model. Review at least 10 results. For each result, compare the agent's behavior with the recorded expected outcome. A confirmed failure requires a valid scenario and observed behavior that conflicts with the expected outcome or a specification requirement. Record the evidence: which data value, policy, tool result, or requirement supports the judgment.

The pilot must contain at least five confirmed failures. If it does not, add challenge scenarios from the difficult dimensions, or use a lower-capability model from the same provider. Do not add scenarios by copying requests that happened to fail; use the underlying dimension to generate new cases.

**Cartwheel example:**

```bash
uv run python -m seed.generate
uv run python -m scenarios.runner scenarios/pilot_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/pilot-results.jsonl
```

## Step 8: Create and run the final set

Generate the full set following the same steps: generate conversations concurrently, run critic calls, validate, and show the human a sample. Give every final scenario a new identifier distinct from the pilot identifiers, because the trace export selects traces by scenario identifier.

Reset mutable application state immediately before the final run, then run the full set on one model. If any scenarios fail (timeout, provider error, missing trace), rerun only the affected scenarios.

**Cartwheel example:**

```bash
uv run python -m seed.generate
uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/final-results.jsonl
```

The `--resume` flag keeps every completed record and reruns only the scenarios whose record is missing or incomplete.

## Step 9: Verify and export

Export the traces and confirm completeness. Verify:

1. Every final scenario identifier has a matching trace in the export.
2. Each trace contains the conversation messages, tool calls and results, model metadata, and the scenario identifier attribute.
3. The export includes traces from both scenario groups, all roles, and a range of turn counts.

Report the coverage and challenge results separately. The workflow ends with a verified trace dataset ready for error analysis.

**Cartwheel example:**

```bash
uv run python -m scenarios.export_langfuse \
  scenarios/support_scenarios.jsonl traces/support_traces.json
```

## Conversation plan format

Each line of the scenario file is one complete planned interaction. The format depends on the project, but every plan should contain at least a unique identifier, dimension values, user messages, and an expected outcome. Use the project's executable schema when one exists.

**Cartwheel example (objective expectation):**

```json
{
  "id": "support-0042",
  "scenario_group": "challenge",
  "data_quality_case_id": "dq-order-missing-delivery-date",
  "tuple": {
    "role": "shopper",
    "user_id": 392,
    "intent": "return_deadline",
    "record_state": "order_missing_delivery_date",
    "applicable_policy": "cw-returns",
    "tools_needed": "one_lookup",
    "difficulty": "missing_information",
    "user_style": "confused_rambling",
    "turn_count": 1,
    "order_id": 8002
  },
  "opening_message": "Can I still send back the pencil set I got from Atlas Stationery?",
  "followups": [],
  "expected": {
    "evaluation": "objective",
    "outcome": "do_not_compute_return_deadline",
    "reason": "The order has a delivered status but no delivery date.",
    "source": {
      "type": "data_quality_table",
      "reference": "dq-order-missing-delivery-date"
    }
  }
}
```

**Cartwheel example (human judgment expectation):**

```json
{
  "id": "support-0108",
  "scenario_group": "coverage",
  "data_quality_case_id": null,
  "tuple": {
    "role": "shopper",
    "user_id": 210,
    "intent": "out_of_scope",
    "record_state": "none",
    "applicable_policy": "none",
    "tools_needed": "none",
    "difficulty": "well_specified",
    "user_style": "neutral_conversational",
    "turn_count": 1
  },
  "opening_message": "Can you help me file my taxes?",
  "followups": [],
  "expected": {
    "evaluation": "human_judgment",
    "criterion": "The agent declines the request in one or two sentences and points to what it can help with, without revealing inaccessible information.",
    "source": {
      "type": "specification",
      "reference": "SCOPE-2, RESP-4"
    }
  }
}
```

The key fields:

- **id**: a unique identifier that links the plan, the run result, and the traces.
- **scenario_group**: `coverage` or `challenge`.
- **tuple**: one value per approved dimension, plus any record identifier that grounds the scenario in the data.
- **opening_message**: the first user message, written naturally without hidden facts.
- **followups**: an ordered list of exact user messages for subsequent turns. An empty list means a single-turn interaction.
- **expected**: the answer key. For an objective expectation, record the outcome, reason, and source. For a human judgment expectation, record a criterion and a specification reference.

## Limitations

**Synthetic users are more cooperative than real users.** Even when the generation prompt requests varied styles, generated users tend to be more polite, more grammatical, and more relevant than real users. A generated frustrated shopper says "this is really annoying, can you just process the refund" rather than sending three messages of unrelated complaints before arriving at the actual request. A generated developer describes the bug precisely rather than pasting a stack trace with no context. Synthetic traces complement production traffic rather than replacing it.

**Challenge enrichment changes the observed failure rate.** A dataset with intentionally difficult scenarios will show more failures than a random sample of production requests. Reporting the coverage and challenge sets separately prevents the enriched failure rate from being mistaken for the production failure rate.

**Scripted followups cannot react to the agent's response.** A followup like "yes, go ahead" assumes the agent offered an action. Because the followups are written before the agent runs, each followup must be plausible regardless of what the agent said in the previous turn. Adaptive user simulation, where a second model reads the agent's response and generates a contextual followup, requires a runtime user model with its own evaluation and cost.
