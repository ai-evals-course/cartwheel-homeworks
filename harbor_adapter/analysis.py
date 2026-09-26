"""Create the Homework 6 trial-count artifact from one Harbor job."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.eval.passk import pass_at_k

from harbor_adapter.summary import _reward


def analyze_capability_job(
    job_dir: Path,
    case_id: str,
    *,
    expected_attempts: int = 15,
) -> dict[str, Any]:
    """Return ordered rewards and pass@k estimates for one capability case."""
    result_path = job_dir / "result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Harbor result not found: {result_path}")
    result = json.loads(result_path.read_text())
    trials = [
        trial
        for trial in result.get("trial_results", [])
        if str(trial.get("task_name", "")).endswith(case_id)
    ]
    if len(trials) != expected_attempts:
        raise ValueError(
            f"{case_id}: expected {expected_attempts} trials, found {len(trials)}"
        )

    rewards: list[int] = []
    trial_records: list[dict[str, Any]] = []
    models: set[str] = set()
    for trial in trials:
        if trial.get("exception_info") is not None:
            raise ValueError(f"{case_id}: trial {trial.get('trial_name')} has an error")
        reward = _reward(trial)
        if reward is None:
            raise ValueError(
                f"{case_id}: trial {trial.get('trial_name')} has no reward"
            )
        passed = int(reward >= 1.0)
        rewards.append(passed)
        trial_records.append(
            {"trial_name": str(trial.get("trial_name", "")), "passed": passed}
        )
        agent_info = trial.get("agent_info") or {}
        model_info = agent_info.get("model_info") or {}
        model_name = model_info.get("name")
        if model_name:
            provider = model_info.get("provider")
            recorded_model = str(model_name)
            if provider and not recorded_model.startswith(f"{provider}/"):
                recorded_model = f"{provider}/{recorded_model}"
            models.add(recorded_model)
    if len(models) != 1:
        raise ValueError(
            f"{case_id}: expected one recorded agent model, found {sorted(models)}"
        )

    comparisons: list[dict[str, Any]] = []
    for n in (5, 10, 15):
        observed = rewards[:n]
        successes = sum(observed)
        ks = [1, 3, 5]
        if n == 15:
            ks.extend([10, 15])
        comparisons.append(
            {
                "n": n,
                "successes": successes,
                "pass_at_k": {
                    str(k): pass_at_k(n, successes, k) for k in ks
                },
            }
        )

    return {
        "case_id": case_id,
        "model": next(iter(models)),
        "trial_order": "result.json trial_results order",
        "trials": trial_records,
        "rewards": rewards,
        "n": len(rewards),
        "successes": sum(rewards),
        "comparisons": comparisons,
    }


def write_analysis(path: Path, analysis: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis, indent=2) + "\n")
