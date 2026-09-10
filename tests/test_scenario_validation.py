from __future__ import annotations

import copy

import pytest

from scenarios.validate import ScenarioValidationError, validate_scenarios


def valid_scenario() -> dict:
    return {
        "id": "support-0001",
        "scenario_group": "coverage",
        "data_quality_case_id": None,
        "tuple": {
            "role": "shopper",
            "intent": "order_status",
            "record_state": "delivered",
            "tools_needed": "one_lookup",
            "applicable_policy": None,
            "turn_count": 1,
            "difficulty": "ordinary",
            "order_id": 4127,
        },
        "opening_message": "Where is order 4127?",
        "followups": [],
        "expected": {
            "evaluation": "objective",
            "outcome": "return_accessible_order_status",
            "source": {"type": "sql", "reference": "orders.id = 4127"},
        },
    }


def test_pilot_validation_accepts_contract() -> None:
    assert validate_scenarios([valid_scenario()]) == {
        "records": 1,
        "unique_ids": 1,
        "coverage": 1,
        "challenge": 0,
        "data_quality": 0,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda s: s.update(scenario_group="hard"), "scenario_group"),
        (lambda s: s["expected"].update(evaluation="model_guess"), "expected.evaluation"),
        (lambda s: s["tuple"].pop("intent"), "tuple.intent"),
        (lambda s: s["tuple"].pop("difficulty"), "missing required fields"),
        (lambda s: s["tuple"].update(turn_count=2), "tuple.turn_count"),
        (lambda s: s.update(followups=["one", "two", "three"]), "three turns total"),
    ],
)
def test_pilot_validation_rejects_bad_records(mutation, message: str) -> None:
    scenario = valid_scenario()
    mutation(scenario)
    with pytest.raises(ScenarioValidationError, match=message):
        validate_scenarios([scenario])


def test_pilot_validation_rejects_duplicate_conversations() -> None:
    first = valid_scenario()
    second = valid_scenario()
    second["id"] = "support-0002"
    with pytest.raises(ScenarioValidationError, match="duplicate scripted conversations"):
        validate_scenarios([first, second])


def test_final_validation_enforces_counts_and_dirty_case_entity(world: dict) -> None:
    scenario = valid_scenario()
    scenario.update(
        scenario_group="challenge",
        data_quality_case_id="dq-order-missing-delivery-date",
    )
    scenario["tuple"]["order_id"] = 999
    scenario["expected"] = {
        "evaluation": "objective",
        "outcome": "do_not_compute_return_deadline",
        "source": {
            "type": "data_quality_table",
            "reference": "dq-order-missing-delivery-date",
        },
    }
    with pytest.raises(ScenarioValidationError) as exc:
        validate_scenarios([copy.deepcopy(scenario)], final=True, db=world["db"])
    text = str(exc.value)
    assert "tuple.order_id must be 8002" in text
    assert "must contain 250 records" in text
    assert "must contain 5 scenarios for dq-order-missing-delivery-date" in text


def test_final_validation_accepts_complete_composition(world: dict) -> None:
    records = []
    for i in range(250):
        scenario = valid_scenario()
        scenario["id"] = f"support-{i:04d}"
        scenario["opening_message"] = f"Where is order 4127? wording {i}"
        scenario["scenario_group"] = "coverage" if i < 175 else "challenge"
        records.append(scenario)

    cases = [
        ("dq-product-duplicate-title", "product_id", 2),
        ("dq-product-missing-title", "product_id", 3),
        ("dq-product-invalid-price", "product_id", 4),
        ("dq-order-reversed-dates", "order_id", 8001),
        ("dq-order-missing-delivery-date", "order_id", 8002),
        ("dq-order-store-mismatch", "order_id", 8003),
    ]
    for offset, (case_id, entity_key, entity_id) in enumerate(cases):
        for repetition in range(5):
            scenario = records[175 + offset * 5 + repetition]
            scenario["data_quality_case_id"] = case_id
            scenario["tuple"][entity_key] = entity_id
            scenario["expected"] = {
                "evaluation": "objective",
                "outcome": "follow_manifest_expected_handling",
                "source": {"type": "data_quality_table", "reference": case_id},
            }

    summary = validate_scenarios(records, final=True, db=world["db"])
    assert summary == {
        "records": 250,
        "unique_ids": 250,
        "coverage": 175,
        "challenge": 75,
        "data_quality": 30,
    }
