"""Validate Cartwheel support-scenario JSONL before an expensive run.

The synthetic-scenario skill is an instruction file, so generated records
need a separate executable contract.  The default mode validates records that
may be used for a pilot.  ``--final`` additionally enforces Homework 3's
250-record composition and documented data-quality coverage.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from agent.config import db_path

GROUPS = {"coverage", "challenge"}
ROLES = {"shopper", "merchant", "support"}
REQUIRED_TUPLE_FIELDS = {
    "role",
    "intent",
    "record_state",
    "applicable_policy",
    "tools_needed",
    "turn_count",
    "difficulty",
}
OBJECTIVE_SOURCE_TYPES = {
    "sql",
    "eligibility_function",
    "policy_document",
    "data_quality_table",
}


class ScenarioValidationError(ValueError):
    """Raised when one or more scenario-contract checks fail."""


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_expected(expected: Any, label: str, errors: list[str]) -> None:
    if not isinstance(expected, dict):
        errors.append(f"{label}: expected must be an object")
        return
    evaluation = expected.get("evaluation")
    source = expected.get("source")
    if not isinstance(source, dict):
        errors.append(f"{label}: expected.source must be an object")
        return
    source_type = source.get("type")
    reference = source.get("reference")
    if not _nonempty_string(reference):
        errors.append(f"{label}: expected.source.reference must be a nonempty string")

    if evaluation == "objective":
        if not _nonempty_string(expected.get("outcome")):
            errors.append(f"{label}: an objective expected outcome must be a nonempty string")
        if source_type not in OBJECTIVE_SOURCE_TYPES:
            errors.append(
                f"{label}: objective source type must be one of "
                f"{sorted(OBJECTIVE_SOURCE_TYPES)}"
            )
    elif evaluation == "human_judgment":
        if not _nonempty_string(expected.get("criterion")):
            errors.append(f"{label}: a human_judgment expected value needs criterion")
        if source_type != "specification":
            errors.append(f"{label}: human_judgment source type must be 'specification'")
    else:
        errors.append(
            f"{label}: expected.evaluation must be 'objective' or 'human_judgment'"
        )


def validate_scenarios(
    scenarios: list[dict[str, Any]],
    *,
    final: bool = False,
    db: Path | None = None,
) -> dict[str, Any]:
    """Validate records and return a compact summary.

    In final mode, the database manifest is also used to prove that every
    documented defect has five challenge scenarios and that each scenario's
    tuple points at the affected entity.
    """
    errors: list[str] = []
    ids: list[str] = []
    conversations: list[tuple[str, ...]] = []
    groups: Counter[str] = Counter()
    dq_counts: Counter[str] = Counter()
    dq_rows: dict[str, tuple[str, int]] = {}

    if final:
        database = db or db_path()
        if not database.exists():
            raise FileNotFoundError(
                f"database not found: {database}; run python -m seed.generate first"
            )
        conn = sqlite3.connect(database)
        try:
            rows = conn.execute(
                "SELECT case_id, entity_type, entity_id FROM data_quality_cases"
            ).fetchall()
        finally:
            conn.close()
        dq_rows = {case_id: (entity_type, entity_id) for case_id, entity_type, entity_id in rows}
        if not dq_rows:
            errors.append("database contains no documented data_quality_cases")

    for index, scenario in enumerate(scenarios, start=1):
        label = f"record {index}"
        if not isinstance(scenario, dict):
            errors.append(f"{label}: scenario must be an object")
            continue
        scenario_id = scenario.get("id")
        if not _nonempty_string(scenario_id):
            errors.append(f"{label}: id must be a nonempty string")
        else:
            ids.append(scenario_id)
            label = scenario_id

        group = scenario.get("scenario_group")
        if group not in GROUPS:
            errors.append(f"{label}: scenario_group must be 'coverage' or 'challenge'")
        else:
            groups[group] += 1

        tuple_ = scenario.get("tuple")
        if not isinstance(tuple_, dict):
            errors.append(f"{label}: tuple must be an object")
            tuple_ = {}
        if tuple_.get("role") not in ROLES:
            errors.append(f"{label}: tuple.role must be shopper, merchant, or support")
        if not _nonempty_string(tuple_.get("intent")):
            errors.append(f"{label}: tuple.intent must be a nonempty string")
        missing_tuple_fields = sorted(REQUIRED_TUPLE_FIELDS - tuple_.keys())
        if missing_tuple_fields:
            errors.append(
                f"{label}: tuple is missing required fields "
                f"{', '.join(missing_tuple_fields)}"
            )
        for field in ("record_state", "applicable_policy", "difficulty"):
            value = tuple_.get(field)
            if value is not None and not _nonempty_string(value):
                errors.append(f"{label}: tuple.{field} must be null or a nonempty string")
        tools = tuple_.get("tools_needed")
        if "tools_needed" in tuple_ and not (
            _nonempty_string(tools) or (isinstance(tools, int) and not isinstance(tools, bool) and tools >= 0)
        ):
            errors.append(f"{label}: tuple.tools_needed must be a nonempty string or a nonnegative integer")
        if not _nonempty_string(scenario.get("opening_message")):
            errors.append(f"{label}: opening_message must be a nonempty string")
        followups = scenario.get("followups")
        if not isinstance(followups, list) or not all(_nonempty_string(x) for x in followups):
            errors.append(f"{label}: followups must be a list of nonempty strings")
        elif len(followups) > 2:
            errors.append(f"{label}: at most two followups are allowed (three turns total)")
        elif tuple_.get("turn_count") != 1 + len(followups):
            errors.append(
                f"{label}: tuple.turn_count must equal 1 + len(followups)"
            )
        if _nonempty_string(scenario.get("opening_message")) and isinstance(followups, list):
            messages = [scenario["opening_message"], *followups]
            if all(_nonempty_string(message) for message in messages):
                conversations.append(tuple(message.strip().casefold() for message in messages))
        _validate_expected(scenario.get("expected"), label, errors)

        dq_id = scenario.get("data_quality_case_id")
        if dq_id is not None:
            if not _nonempty_string(dq_id):
                errors.append(f"{label}: data_quality_case_id must be null or a nonempty string")
            else:
                dq_counts[dq_id] += 1
                if group != "challenge":
                    errors.append(f"{label}: a data-quality scenario must be in the challenge group")
                expected = scenario.get("expected", {})
                source = expected.get("source", {}) if isinstance(expected, dict) else {}
                if expected.get("evaluation") != "objective":
                    errors.append(f"{label}: a documented data-quality case must be objective")
                if source.get("type") != "data_quality_table" or source.get("reference") != dq_id:
                    errors.append(
                        f"{label}: data-quality expected source must reference {dq_id!r}"
                    )
                if final:
                    manifest = dq_rows.get(dq_id)
                    if manifest is None:
                        errors.append(f"{label}: unknown data_quality_case_id {dq_id!r}")
                    else:
                        entity_type, entity_id = manifest
                        entity_key = f"{entity_type}_id"
                        if tuple_.get(entity_key) != entity_id:
                            errors.append(
                                f"{label}: tuple.{entity_key} must be {entity_id} for {dq_id}"
                            )

    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate scenario ids: {', '.join(duplicates[:10])}")
    duplicate_conversations = [
        conversation
        for conversation, count in Counter(conversations).items()
        if count > 1
    ]
    if duplicate_conversations:
        preview = " / ".join(duplicate_conversations[0])
        errors.append(f"duplicate scripted conversations found (for example: {preview})")

    if final:
        if len(scenarios) != 250:
            errors.append(f"final dataset must contain 250 records, found {len(scenarios)}")
        for group, required in (("coverage", 175), ("challenge", 75)):
            if groups[group] != required:
                errors.append(
                    f"final dataset must contain {required} {group} records, found {groups[group]}"
                )
        for case_id in sorted(dq_rows):
            if dq_counts[case_id] != 5:
                errors.append(
                    f"final dataset must contain 5 scenarios for {case_id}, found {dq_counts[case_id]}"
                )

    if errors:
        raise ScenarioValidationError("scenario validation failed:\n- " + "\n- ".join(errors))
    return {
        "records": len(scenarios),
        "unique_ids": len(ids),
        "coverage": groups["coverage"],
        "challenge": groups["challenge"],
        "data_quality": sum(dq_counts.values()),
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            scenarios.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ScenarioValidationError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Cartwheel scenario JSONL.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--final", action="store_true", help="enforce the 250-record final contract")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    summary = validate_scenarios(load_jsonl(args.path), final=args.final, db=args.db)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
