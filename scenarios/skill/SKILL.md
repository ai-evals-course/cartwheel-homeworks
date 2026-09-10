---
name: synthetic-scenarios
description: >
  Generate grounded eval scenarios from a spec plus ground-truth access.
  Use when you have a written spec for an agent and a database or corpus
  that can compute expected outcomes, and you need realistic usage data
  (scenarios) to run against the agent.
---

# Synthetic scenario generation

The file provides a versioned procedure for a coding agent. The procedure is
included in the Cartwheel scaffold, introduced in Lecture 3.2, and used in
Homework 3 to generate support scenarios from the Cartwheel specification.

## When to use

Use the procedure when a specification and an authoritative data source
already exist, but representative requests and traces do not. The procedure
generates requests against an existing application; it does not invent the
application's database, policies, or expected outcomes.

## Inputs

- The path to the support agent specification, `SPEC.md`.
- A DB or corpus handle for computing expected outcomes (for Cartwheel:
  `data/cartwheel.db` and `data/policies/`).

## Procedure

1. Read the spec, propose the six required dimensions with their values,
   and show them to the human before generating anything. Add another
   dimension only with a stated reason. The six required dimensions are:
   the authenticated role; the intent; the record involved (an order and
   its state, a product, a store policy page, or none); the applicable
   policy (platform rule, store override, or none); the number of tool
   calls needed (none, one lookup, or several); and the difficulty. Each
   scenario also records its turn count (1 to 3), which equals one plus
   the number of followups.
2. Generate tuples from the approved dimensions, using a few tuples the
   human wrote as examples. Do not enumerate the full Cartesian product;
   some combinations are invalid and the product grows quickly. Count how
   often each value appears, and sample the rare and risky combinations on
   purpose. Keep a coverage pool in which every dimension value appears
   repeatedly and a separate challenge pool of difficult but valid
   combinations. Do not select a challenge merely because a model failed
   on the exact case.
3. Draft one natural opening message per tuple. For a multi-turn scenario,
   put one or two exact user utterances in `followups`; the runner sends every
   string verbatim, so do not place persona notes or generation instructions
   in the field.
4. Check for duplicate requests, unrealistic phrasing, and missing dimension
   values. Assign `scenario_group` as `coverage` or `challenge`. The coverage
   group exercises the planned dimensions. The challenge group concentrates
   on valid requests that are difficult for a stated reason.
5. Compute the expected outcome per scenario from ground truth (SQL against
   the database, or the eligibility function in `seed/eligibility.py`).
   A model assertion is not ground truth. When code or a policy document
   cannot determine the expected outcome, mark the scenario for later human
   judgment.
6. Run a pilot on the selected model. Confirm failures against the recorded
   expected results, then identify dimensions associated with the difficult
   cases. If the first pilot produces too few failures, use a lower capability
   model from the same provider. Do not create a failure taxonomy during
   scenario generation.
7. Generate new challenge scenarios from the difficult dimensions. Preserve
   the coverage pool, because a dataset containing only failures cannot show
   ordinary behavior.
8. Emit JSONL, one scenario per line.
9. Run the executable contract before any model calls:
   `uv run python -m scenarios.validate scenarios/support_scenarios.jsonl --final`.
   Repair every reported error before starting the final run.

## Output schema

```json
{
  "id": "support-0042",
  "scenario_group": "challenge",
  "data_quality_case_id": "dq-order-missing-delivery-date",
  "tuple": {"role": "shopper", "intent": "return_deadline", "record_state": "order_missing_delivery_date", "applicable_policy": "cw-returns", "tools_needed": "one_lookup", "turn_count": 1, "difficulty": "boundary", "order_id": 8002},
  "opening_message": "When does the return period end for order 8002?",
  "followups": [],
  "expected": {
    "evaluation": "objective",
    "outcome": "do_not_compute_return_deadline",
    "reason": "The order is marked delivered, but its delivery date is missing.",
    "source": {
      "type": "data_quality_table",
      "reference": "dq-order-missing-delivery-date"
    }
  }
}
```

For an objective case, `expected.source.type` is `sql`,
`eligibility_function`, `policy_document`, or `data_quality_table`.
`expected.source.reference` identifies the query, function input, document,
or data quality case used to determine the answer.

Use the following form when a person must judge the resulting trace:

```json
{
  "expected": {
    "evaluation": "human_judgment",
    "criterion": "The response should explain the missing information without inventing a date.",
    "source": {
      "type": "specification",
      "reference": "SPEC.md, RESP-3"
    }
  }
}
```

Choose one expected form for each scenario. Use `objective` when the scenario
tests an answer or action that data, code, or a policy document fixes exactly.
Use `human_judgment` when the scenario tests a response quality that has
several acceptable answers. A model response cannot be the source of an
expected result, because the response may contain the error the evaluation
needs to find.

`id` links the scenario to its traces through the
`cartwheel.scenario_id` span attribute. Use `data_quality_case_id: null` for
an ordinary scenario. A scenario involving a documented defect uses the
matching identifier from `data_quality_cases`, belongs to the challenge
group, uses an objective `data_quality_table` source, and records the affected
`product_id` or `order_id` in `tuple`.

## Known limits

Queries drafted by a model tend to be more polite, grammatical, and relevant
than requests from actual users. Synthetic scenarios therefore do not replace
production traffic. Challenge enrichment also changes the observed failure
frequency. Report results separately for the coverage and challenge groups,
and do not interpret the combined frequency as an estimate of production
prevalence.
