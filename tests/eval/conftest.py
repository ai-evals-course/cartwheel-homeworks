"""Fixtures and constants for the Module 3 evaluation tests.

The deterministic tests run without model keys. The direct model test remains
available as an optional local check. Homework 6 uses Harbor for pull request
evaluation runs.
"""

from __future__ import annotations

import os

import pytest

from replay.rollout import load_cases

# The course uses five runs per case.
# A clean 5-of-5 bounds the per-run pass rate above 0.55 at 95 percent
# confidence, which catches collapses per case; small drifts show up in the
# suite-level aggregate instead.
EVAL_K = 5

# Use the same student-selected agent model as the Harbor evaluation. A separate
# CARTWHEEL_EVAL_MODEL may be set for this optional direct check.
PINNED_AGENT_MODEL = os.environ.get("CARTWHEEL_EVAL_MODEL") or os.environ.get(
    "CARTWHEEL_MODEL"
)


@pytest.fixture(scope="session")
def evaluation_cases() -> list[dict]:
    """Every evaluation case in the Module 3 CI set."""
    return load_cases()
