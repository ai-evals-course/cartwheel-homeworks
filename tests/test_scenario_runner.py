"""Offline tests for the scenario runner's rerun planning (no server needed)."""

import json
from pathlib import Path

import pytest

from scenarios.runner import load_results, plan_run


def _scenario(sid: str) -> dict:
    return {"id": sid, "scenario_group": "coverage", "opening_message": "hi", "expected": {}}


def _record(sid: str, status: str = "completed") -> dict:
    return {"scenario_id": sid, "status": status, "turns": []}


SCENARIOS = [_scenario(f"support-000{i}") for i in range(1, 5)]


def test_plain_run_runs_everything_and_keeps_nothing() -> None:
    to_run, kept = plan_run(SCENARIOS, {})
    assert [s["id"] for s in to_run] == [s["id"] for s in SCENARIOS]
    assert kept == []


def test_resume_reruns_missing_and_failed_records_only() -> None:
    existing = {
        "support-0001": _record("support-0001"),
        "support-0002": _record("support-0002", status="error"),
        "support-0003": _record("support-0003"),
    }
    to_run, kept = plan_run(SCENARIOS, existing, resume=True)
    assert [s["id"] for s in to_run] == ["support-0002", "support-0004"]
    assert [r["scenario_id"] for r in kept] == ["support-0001", "support-0003"]


def test_ids_replaces_named_records_and_keeps_the_rest() -> None:
    existing = {s["id"]: _record(s["id"]) for s in SCENARIOS}
    to_run, kept = plan_run(SCENARIOS, existing, ids={"support-0003"})
    assert [s["id"] for s in to_run] == ["support-0003"]
    assert sorted(r["scenario_id"] for r in kept) == ["support-0001", "support-0002", "support-0004"]


def test_unknown_id_is_rejected() -> None:
    with pytest.raises(SystemExit, match="support-9999"):
        plan_run(SCENARIOS, {}, ids={"support-9999"})


def test_load_results_reads_records_by_id(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(_record("support-0001")) + "\n")
    assert list(load_results(path)) == ["support-0001"]
    assert load_results(tmp_path / "absent.jsonl") == {}
