"""Summarize a Harbor job and apply the Cartwheel CI gate."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from harbor_adapter.export import load_export_cases
from replay.rollout import load_cases


def _case_id(task_name: str, known_ids: set[str]) -> str | None:
    matches = [case_id for case_id in known_ids if task_name.endswith(case_id)]
    return max(matches, key=len) if matches else None


def _reward(trial: dict[str, Any]) -> float | None:
    verifier = trial.get("verifier_result")
    if not isinstance(verifier, dict):
        return None
    rewards = verifier.get("rewards")
    if not isinstance(rewards, dict):
        return None
    value = rewards.get("reward")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def summarize_job(
    job_dir: Path,
    *,
    cases_path: Path | None = None,
    expected_attempts: int | None = None,
    classify: bool = False,
) -> tuple[str, bool]:
    """Return a Markdown summary and whether the CI gate passes."""
    if classify:
        cases = load_export_cases(cases_path)
    else:
        cases = load_cases(cases_path)
    by_id = {case["id"]: case for case in cases}
    result_path = job_dir / "result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Harbor result not found: {result_path}")
    result = json.loads(result_path.read_text())
    trials: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unknown: list[str] = []
    for trial in result.get("trial_results", []):
        case_id = _case_id(str(trial.get("task_name", "")), set(by_id))
        if case_id is None:
            unknown.append(str(trial.get("task_name", "")))
            continue
        trials[case_id].append(trial)

    if classify:
        lines = [
            "## Cartwheel baseline results",
            "",
            "| Case | Passed | Trials | Record in the case |",
            "| --- | ---: | ---: | --- |",
        ]
    else:
        lines = [
            "## Cartwheel evaluation results",
            "",
            "| Case | Kind | Passed | Trials | pass@1 | pass@3 | pass@5 | pass^5 | CI decision |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    gate_passes = not unknown
    infrastructure: list[str] = []
    reported_cases = 0
    for case in cases:
        case_trials = trials.get(case["id"], [])
        if classify and not case_trials:
            continue
        reported_cases += 1
        rewards = [_reward(trial) for trial in case_trials]
        errors = sum(
            reward is None or trial.get("exception_info") is not None
            for reward, trial in zip(rewards, case_trials)
        )
        if expected_attempts is not None and len(case_trials) != expected_attempts:
            infrastructure.append(
                f"{case['id']}: expected {expected_attempts} trials, found {len(case_trials)}"
            )
        if errors:
            infrastructure.append(f"{case['id']}: {errors} trial(s) did not produce a reward")

        passes = sum(reward is not None and reward >= 1.0 for reward in rewards)
        n = len(case_trials)
        if classify and n:
            if n != 5 or errors:
                record = "do not classify; complete five valid trials"
            elif passes == 5:
                record = '`kind: "regression"`'
            else:
                rate = passes / n
                record = (
                    '`kind: "capability"`, '
                    f'`baseline_pass_rate: {rate:.1f}`'
                )
            lines.append(f"| `{case['id']}` | {passes} | {n} | {record} |")
        elif n:
            from tests.eval.passk import case_passes, pass_at_k, pass_hat_k

            decision = case_passes(
                case["kind"], passes, n, case.get("baseline_pass_rate")
            )
            label = decision["decision"]
            if label == "block":
                gate_passes = False
            pass_1 = pass_at_k(n, passes, 1)
            pass_3 = pass_at_k(n, passes, 3) if n >= 3 else None
            pass_5 = pass_at_k(n, passes, 5) if n >= 5 else None
            reliability_5 = pass_hat_k(n, passes, 5) if n >= 5 else None

            def show(value: float | None) -> str:
                return f"{value:.3f}" if value is not None else "n/a"

            lines.append(
                f"| `{case['id']}` | {case['kind']} | {passes} | {n} | "
                f"{show(pass_1)} | {show(pass_3)} | {show(pass_5)} | "
                f"{show(reliability_5)} | {label} |"
            )
        else:
            label = "incomplete"
            gate_passes = False
            if not classify:
                lines.append(
                    f"| `{case['id']}` | {case['kind']} | 0 | 0 | n/a | n/a | n/a | n/a | {label} |"
                )

    if unknown:
        infrastructure.append("unknown Harbor tasks: " + ", ".join(sorted(unknown)))
    if classify and reported_cases == 0:
        infrastructure.append("no baseline trials matched a case in the case file")
    if infrastructure:
        gate_passes = False
        lines.extend(["", "Infrastructure problems:"])
        lines.extend(f"- {problem}" for problem in infrastructure)
    if classify:
        lines.extend(
            [
                "",
                "Add the reported classification to each case before exporting the CI suite.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Regression cases block on any failed trial. Capability cases do not block.",
            ]
        )
    return "\n".join(lines) + "\n", gate_passes


def write_github_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a") as handle:
            handle.write(markdown)
