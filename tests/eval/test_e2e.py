"""Optional direct agent tests on classified evaluation cases.

Each evaluation case runs EVAL_K times, each run in a freshly re-seeded world
(the sandbox reset), scored by the case's code checks plus its pinned
Module 2 judges. The per-case pass count feeds the CI rule you
implemented in tests/eval/passk.py:

  - a regression case blocks on ANY failed run (its baseline is k of k);
  - a capability case never blocks CI, but its pass rate is reported in the
    log and exported as a Module 5 improvement target.

The CI decision never uses pass@k. Passing a case because one run in k
succeeded would allow a broken behavior to merge.

The tests use model calls and skip unless CARTWHEEL_RUN_E2E=1 and an agent model
is selected. Homework 6 uses Harbor with Docker in GitHub Actions. Reruns are
for infrastructure failures only. A completed verdict is data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harbor_adapter.export import _provider_key, load_export_cases
from replay.rollout import (
    apply_checks,
    fresh_world,
    judge_reply,
    load_frozen_judge,
    retrieved_docs_text,
    run_case,
)
from tests.eval.conftest import EVAL_K, PINNED_AGENT_MODEL

pytestmark = pytest.mark.skipif(
    os.environ.get("CARTWHEEL_RUN_E2E") != "1"
    or not PINNED_AGENT_MODEL,
    reason="direct agent tests need CARTWHEEL_RUN_E2E=1 and CARTWHEEL_MODEL",
)

CASES = [
    case
    for case in load_export_cases()
    if case.get("kind") in {"regression", "capability"}
]


def _run_once(case: dict, root: Path) -> tuple[bool, list[str], dict]:
    """One rollout in a fresh world: (passed, failure_modes, usage)."""
    with fresh_world(root) as db_path:
        transcript = run_case(case, model=PINNED_AGENT_MODEL)
        outcome = apply_checks(case, transcript, db_path)
        failures = list(outcome["failed"])
        judges = case["expected"].get("judges", {})
        docs = retrieved_docs_text(transcript)
        for mode, expected in judges.items():
            judge = load_frozen_judge(mode)
            required_key = _provider_key(judge["model"])
            if required_key and not os.environ.get(required_key):
                failures.append(f"judge-skipped: no {required_key} (score incomplete)")
                continue
            verdict = judge_reply(judge, transcript["final_reply"], docs)
            if verdict != expected:
                failures.append(f"judge:{mode} said {verdict}, expected {expected}")
    return (not failures, failures, transcript["usage"])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_e2e_case(case: dict, tmp_path: Path) -> None:
    from tests.eval.passk import case_passes

    passes = 0
    failure_lines: list[str] = []
    tokens_in = tokens_out = 0
    for i in range(EVAL_K):
        passed, failures, usage = _run_once(case, tmp_path / f"run-{i}")
        passes += passed
        tokens_in += usage["input_tokens"]
        tokens_out += usage["output_tokens"]
        if not passed:
            failure_lines.append(f"run {i}: {'; '.join(failures)}")

    rate = passes / EVAL_K
    print(
        f"{case['id']} [{case['kind']}] "
        f"pass rate {passes}/{EVAL_K} = {rate:.2f} | "
        f"tokens in {tokens_in} out {tokens_out}"
        + (f" | {failure_lines[0]}" if failure_lines else "")
    )

    decision = case_passes(
        case["kind"], passes, EVAL_K, case.get("baseline_pass_rate")
    )
    assert decision["decision"] == "pass", (
        f"{case['id']} failed CI: {decision['reason']}\n" + "\n".join(failure_lines)
    )
