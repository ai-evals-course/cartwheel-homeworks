---
name: synthetic-trace-generation
description: >
  Generate grounded, diverse support conversations and run them against the
  instrumented Cartwheel agent to create a verified trace dataset for error
  analysis.
---

# Synthetic trace generation

This skill generates a dataset of agent traces when production traces are unavailable or do not cover enough behavior for error analysis. The approach generates *scenarios* rather than raw user messages, because a scenario carries both a user request and an expected outcome grounded in the database and the policy documents. The expected outcome is what makes the trace useful for finding failures: without a recorded answer key, a reviewer has nothing to compare the agent's behavior against.

## Why not generate user messages directly?

Asking a model to "generate 250 support questions for an e-commerce platform" produces narrow data. The model tends to repeat the most common request type, such as order status, and ignores categories that appear less often in its training data, such as refund eligibility boundaries, store policy overrides, and permission denials. Adding more rows does not fix the problem, because more rows of the same kind do not introduce missing kinds. The synthetic data approach fixes the problem by defining the kinds of variation first, then generating requests that cover each kind.

## What a scenario contains

A scenario is a planned support conversation with four parts:

1. **A tuple of dimension values** that describe what kind of request the conversation represents, such as the user's role, intent, and the state of the relevant order.
2. **User messages** (an opening message and optional followups) written in natural language from the tuple, as if a real user were typing into the chat window.
3. **An expected outcome** computed from the database and the policy documents, stating what the agent should do and citing the authoritative source.
4. **Metadata** linking the scenario to its group (coverage or challenge), its scenario identifier, and any relevant data quality case.

The scenario is an input to the runner, not a trace. Running a scenario through the agent produces two separate outputs: a result record for the attempted conversation, and Langfuse traces from the instrumented application. Cartwheel creates one trace per user turn and tags every trace with the scenario identifier, so the plan, the result, and the traces are always linked.

## Invariants

These rules hold throughout the workflow. Each one prevents a specific mistake.

1. **Ground expected outcomes in authoritative sources.** The expected outcome for a refund scenario comes from the order's delivery date and the return window in `facts.yaml`, not from the model's answer. If the model's own answer were the answer key, a wrong answer would look correct. Sources include the database (SQL), the policy documents, and the data quality table.

2. **Keep hidden expected answers out of generation prompts.** The model that writes the user's message receives only facts the simulated user would know (the product name, an approximate date, a vague description) and never the hidden expected outcome. A user asking about a return does not know the exact return window or whether the refund will be approved.

3. **Write and review conversation plans before running the application.** Each application run costs model calls for every scenario in the file. Catching an invalid scenario before the run saves the cost of running it. Catching a bad user message before the run saves the cost of a trace that tests the wrong thing.

4. **Preserve ordinary coverage while adding difficult cases.** Reporting the coverage and challenge sets separately prevents routine successes from hiding failures at the edges. A dataset of 175 coverage scenarios and 75 challenge scenarios lets a reviewer see both the baseline behavior and the boundary behavior.

5. **Preserve human decisions at the dimension and request review gates.** The human approves the dimensions before generation starts, and reviews a sample of complete conversations before the runner starts. The coding agent proposes, generates, and validates, but the human decides what the dataset should contain.

## Step 1: Verify the application and tracing

Before generating any scenarios, confirm that the Cartwheel agent runs and that its traces are complete. Start the server and Langfuse, then send one inexpensive request (for example, "What's the status of order 4127?" as a shopper) and verify that its Langfuse trace contains:

- The user message and the agent's response.
- The model identity (for example, `gpt-5.5`).
- Tool calls and their results (for example, `get_order` with the order record).
- A `cartwheel.scenario_id` attribute on the trace.
- Token usage, if available.

Do not start bulk generation until authentication, tracing, and the database state reset (`uv run python -m seed.generate`) all work.

## Step 2: Define dimensions of variation

A *dimension* is one named source of variation in the support requests. Each dimension should change the expected behavior, the execution path, or a quality requirement. Do not add a dimension merely because it is easy to vary.

The Cartwheel specification, the seeded data, and the policy documents motivate the following dimensions:

| Dimension | Values | Why it matters |
| --- | --- | --- |
| **Role** | shopper, merchant, support | Different roles have different permissions. A shopper can view their own orders, a merchant can view their store's orders, and support can view any order. The same request from different roles triggers different tool results and permission denials. |
| **Intent** | order status, refund, cancellation, policy question, product search, dispute, out of scope | Each intent exercises different tools and different parts of the specification. A refund request calls `get_order` and `issue_refund`, while a policy question calls `search_help_center` and `get_policy`. |
| **Record involved** | an order (in window, past window, above threshold, placed, shipped), a product, a store policy page, none | The state of the record determines the expected outcome. An order delivered 15 days ago is eligible for a return under the 30-day window, while an order delivered 45 days ago is not. |
| **Applicable policy** | platform rule, store override, none | Some stores override the platform return window. Juniper Home Goods has a 14-day window instead of the platform's 30 days. A request about a Juniper order triggers a different expected outcome than the same request about a Blue Heron Ceramics order. |
| **Tools needed** | none, one lookup, several calls | A policy question needs one lookup (`search_help_center`), while a refund needs several calls (`get_order` to check eligibility, then `issue_refund`). Varying the number of tool calls exercises different parts of the agent loop. |
| **Difficulty** | well specified, ambiguous, missing information, boundary | A well-specified request names the order and the action. An ambiguous request describes a product without an order number, so the agent must call `find_order` first. A boundary request sits exactly at the return window or the refund threshold. |
| **User language style** | neutral\_conversational, terse\_fragmentary, typo\_heavy, confused\_rambling, frustrated\_impatient, repetitive\_pressuring, operational\_shorthand, requests\_short\_plain\_answer | The specification requires direct and respectful responses (RESP-5) regardless of user style. Varying the style tests whether the agent handles terse fragments and frustrated messages as well as polite requests. The validator enforces one of these exact values. |

Each scenario also records its **turn count** (1 through 25), which equals one plus the number of followups. The turn count is set per scenario through the followups list rather than as a separate dimension. The validator checks that the recorded turn count matches the actual number of messages.

### Proposing dimensions to the human

After reading `SPEC.md`, the seeded data, and the data quality cases, propose the dimensions and their values to the human for approval. Use AskUserQuestion to present the proposed dimensions and wait for the human's decision before generating any scenarios. The human may add, remove, or revise dimensions. Do not generate scenarios until the dimensions are approved.

Any additional dimension beyond the seven above needs a reason from the specification or the seeded data. For example, "conversation language" would not be a useful dimension because the specification does not mention multilingual support.

## Step 3: Build grounded conversation plans

Sample valid combinations of the approved dimension values. Do not enumerate the full Cartesian product, because many combinations are invalid (a support staff member asking about their own orders is not a valid scenario), and the product of seven dimensions with multiple values each grows quickly. Instead, count how often each value appears and deliberately include rare and risky combinations, such as store overrides, boundary cases, and damaged records.

### Two pools

Maintain two separate pools:

- **Coverage** (175 scenarios): ordinary requests that exercise every important dimension value. These include straightforward order status checks, simple refund requests within the return window, and routine policy questions.
- **Challenge** (75 scenarios): intentionally difficult requests that test policy boundaries, damaged records, permission edges, corrections across turns, and missing information. Five challenge scenarios should target each of the six data quality cases in the database.

Report results for the two pools separately, because mixing them lets the routine majority hide failures at the edges.

### Selecting records from the database

Each scenario that involves an order, product, or policy must reference a real record from the seeded database. For example, a refund scenario targeting a past-window order should reference an order whose delivery date is more than 30 days ago. Query the database to find a matching record, and verify that the selected user has permission to access the record under the specified role.

Scenarios that change state (refunds, cancellations) should target distinct records, so that one scenario's side effects do not invalidate another scenario's expected outcome.

### Data quality cases

The seeded database contains six deliberately damaged records. Query the `data_quality_cases` table to see them:

```bash
sqlite3 -header -column data/cartwheel.db \
  'SELECT case_id, entity_type, entity_id, description, expected_handling FROM data_quality_cases ORDER BY case_id;'
```

For example, order 8002 has a delivered status but no delivery date. A scenario about this order should record that the agent must not compute a return deadline from a missing date, and should cite `dq-order-missing-delivery-date` as the data quality case identifier.

## Step 4: Compute expected outcomes

Compute the expected outcome for each scenario before generating the user's message. The expected outcome states what the agent should do, and cites the authoritative source that determines the answer.

### Objective expectations

Use an objective expectation when the database or a deterministic rule fixes the answer. For example:

- **Order 3980**, delivered 2026-05-17, Blue Heron Ceramics, no store override. The platform return window is 30 days from delivery (`facts.yaml`). Today is 45 days after delivery. **Expected outcome:** refund denied. **Source:** the return policy in `facts.yaml` and the order row.
- **Order 6974**, delivered 17 days ago, Juniper Home Goods, 14-day store override. **Expected outcome:** refund denied (the store override is stricter). **Source:** the store policy document for Juniper Home Goods.
- **Order 8002**, delivered status but no delivery date (data quality case `dq-order-missing-delivery-date`). **Expected outcome:** do not compute a return deadline. **Source:** the data quality table.

Record the outcome, a short reason, the source type (`sql`, `eligibility_function`, `policy_document`, or `data_quality_table`), and a stable reference to the source (for example, `cw-returns` for the platform return policy, or `dq-order-missing-delivery-date` for a data quality case).

### Human judgment expectations

Use a human judgment expectation when several responses could satisfy the requirement. For example, when a shopper asks a vague question and the agent refuses or asks for clarification, the expected behavior is "a clear and respectful explanation of what information is needed" rather than one exact sentence. Record a precise criterion (for example, "the response must explain what information is missing without revealing other users' data") and cite the relevant SPEC.md requirement (for example, RESP-3 and RESP-4) with source type `specification`.

## Step 5: Generate conversations

Generate the user conversations separately from running the application. The generation model writes the user's messages from the tuple and the user-visible facts, but never sees the hidden expected outcome.

### One call per conversation

Use one independent model call per conversation, and launch the calls concurrently with a bounded pool of at least two workers. Parallel coding subagents may provide the pool when the environment supports them. Do not ask one model call to draft the whole dataset, because a single call produces conversations that share structure and phrasing.

### The generation prompt

Give the generation model the role, the user's goal, the selected language style, the user-visible facts (for example, the product name and an approximate time frame), and the required number of turns. Do not include the order number, the exact delivery date, the return window, or the expected outcome.

For example, to generate the request for the order-3980 refund scenario:

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

- Invented identifiers, amounts, dates, or product names that do not match the selected database row.
- Followups that assume a specific agent response.
- Conversations that share a template opening or followup.
- Language that a real user would not produce, such as quoting the return policy by name.
- References to tools, traces, prompts, or expected outcomes that break the simulation.

The critic may rewrite language but must preserve the grounded plan, the expectation, and the assigned style.

## Step 6: Review conversations with the human

Run the executable validator on the generated file:

```bash
uv run python -m scenarios.validate scenarios/pilot_scenarios.jsonl
```

The validator checks the JSON schema, required tuple fields, unique identifiers, turn counts, duplicate conversations, and the expected-outcome format. Fix every reported error before proceeding.

Then show the human a sample of complete conversations for review. Include the longest conversation, both scenario groups, all three roles, a state-changing scenario (refund or cancellation), a difficult scenario, and several user language styles. The human reads the opening and every followup and decides whether the language is realistic, the followups make sense without seeing the agent's response, and the expected outcome matches the selected record.

Do not start the runner until the human accepts the conversation sample.

## Step 7: Run a pilot

Reset the development data first, because earlier runs may have changed order states:

```bash
uv run python -m seed.generate
```

Run a small representative set (about 30 scenarios) on one model:

```bash
uv run python -m scenarios.runner scenarios/pilot_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/pilot-results.jsonl
```

Review at least 10 results. For each result, compare the agent's behavior with the recorded expected outcome. A confirmed failure requires a valid scenario and observed behavior that conflicts with the expected outcome or a SPEC.md requirement. Record the evidence: which database value, policy, tool result, or requirement supports the judgment.

The pilot must contain at least five confirmed failures. If it does not, add challenge scenarios from the difficult dimensions (store overrides, boundary cases, data quality defects), or use a lower-capability model from the same provider. Do not add scenarios by copying requests that happened to fail; use the underlying dimension (such as "store policy override") to generate new cases.

## Step 8: Create and run the final set

Generate the full set of 250 scenarios (175 coverage, 75 challenge) following the same steps: generate conversations concurrently, run critic calls, validate, and show the human a sample. Give every final scenario a new identifier distinct from the pilot identifiers, because the trace export selects traces by scenario identifier.

Reset the development data immediately before the final run, then run the full set on one model:

```bash
uv run python -m seed.generate

uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/final-results.jsonl
```

If any scenarios fail (timeout, provider error, missing trace), rerun only the affected scenarios:

```bash
uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --model YOUR_MODEL --output scenarios/final-results.jsonl --resume
```

The `--resume` flag keeps every completed record and reruns only the scenarios whose record is missing or incomplete.

## Step 9: Verify and export

Export the traces and confirm completeness:

```bash
uv run python -m scenarios.export_langfuse \
  scenarios/support_scenarios.jsonl traces/support_traces.json
```

Before finishing, verify:

1. Every final scenario identifier has a matching trace in the export.
2. Each trace contains the conversation messages, tool calls and results, model metadata, and the `cartwheel_scenario_id` attribute.
3. The export includes traces from both scenario groups, all three roles, and a range of turn counts.

Report the coverage and challenge results separately. The workflow ends with a verified trace dataset ready for error analysis.

## Conversation plan format

Each line of the scenario JSONL file is one complete planned conversation. Here is a Cartwheel example:

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

The fields:

- **id**: a unique identifier that links the plan, the run result, and the Langfuse traces through `cartwheel.scenario_id`.
- **scenario_group**: `coverage` or `challenge`.
- **data_quality_case_id**: the `case_id` from the `data_quality_cases` table, or `null` when the scenario does not target a damaged record.
- **tuple**: one value per dimension, plus the `user_id` and any record identifier (such as `order_id`) that grounds the scenario in the database.
- **opening_message**: the first user message, written naturally without hidden facts.
- **followups**: an ordered list of exact user messages for subsequent turns. An empty list means a single-turn conversation.
- **expected**: the answer key. For an objective expectation, record `outcome`, `reason`, and `source` with one of the types `sql`, `eligibility_function`, `policy_document`, or `data_quality_table`. For a human judgment expectation, replace `outcome` and `reason` with a `criterion` describing what a correct response looks like, and use source type `specification` with the relevant SPEC.md requirement identifier.

Here is a human judgment example:

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

## Limitations

**Synthetic users are more cooperative than real users.** Even when the generation prompt requests varied styles, generated users tend to be more polite, more grammatical, and more relevant than real users. A generated frustrated user says "this is really annoying, can you just process the refund" rather than sending three messages of unrelated complaints before arriving at the actual request. Synthetic traces complement production traffic rather than replacing it.

**Challenge enrichment changes the observed failure rate.** A dataset with 75 intentionally difficult scenarios will show more failures than a random sample of production requests. Reporting the coverage and challenge sets separately prevents the enriched failure rate from being mistaken for the production failure rate.

**Scripted followups cannot react to the agent's response.** A followup like "yes, go ahead" assumes the agent offered an action. Because the followups are written before the agent runs, each followup must be plausible regardless of what the agent said in the previous turn. Adaptive user simulation, where a second model reads the agent's response and generates a contextual followup, requires a runtime user model with its own evaluation and cost.
