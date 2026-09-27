from __future__ import annotations

import pytest

from replay.harness import ReplayInfraError, replay_case, summarize_rollouts
from replay.rollout import judge_trace_text


def test_replay_resets_before_each_run_and_retries_only_infrastructure() -> None:
    resets = 0
    calls = 0

    def reset() -> None:
        nonlocal resets
        resets += 1

    def runner() -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ReplayInfraError("temporary service error")
        return {"passed": calls % 2 == 0}

    records = replay_case(runner, reset, n=2, max_infra_retries=1)

    assert resets == 3
    assert calls == 3
    assert [record["rollout"] for record in records] == [0, 1]
    assert [record["passed"] for record in records] == [True, False]


def test_replay_does_not_retry_a_completed_failure() -> None:
    calls = 0

    def runner() -> dict:
        nonlocal calls
        calls += 1
        return {"passed": False}

    records = replay_case(runner, lambda: None, n=2)

    assert calls == 2
    assert len(records) == 2


def test_rollout_summary_is_deterministic() -> None:
    records = [
        {"passed": True, "steps": 2},
        {"passed": False, "failure_modes": ["judge:a"], "steps": 4},
        {
            "passed": False,
            "failure_modes": ["judge:a", "check:b"],
            "steps": 6,
        },
    ]

    first = summarize_rollouts(records, bootstrap_iterations=100, seed=7)
    second = summarize_rollouts(records, bootstrap_iterations=100, seed=7)

    assert first == second
    assert first["failures"] == 2
    assert first["failure_rate"] == pytest.approx(2 / 3)
    assert first["mode_counts"] == {"judge:a": 2, "check:b": 1}
    assert first["steps"] == {"min": 2, "median": 4, "max": 6}


def test_judge_trace_text_uses_the_hw5_normalized_roles() -> None:
    transcript = {
        "turns": [
            {
                "user": "Where is my order?",
                "reply": "It shipped today.",
                "tool_calls": [
                    {
                        "name": "get_order",
                        "args": {"order_id": 42},
                        "result": {"ok": True, "status": "shipped"},
                    }
                ],
            }
        ]
    }

    assert judge_trace_text(transcript).splitlines() == [
        "user: Where is my order?",
        'tool_call: {"order_id": 42}',
        'tool_result: {"ok": true, "status": "shipped"}',
        "assistant: It shipped today.",
    ]
