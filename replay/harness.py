"""The supplied sandbox replay harness used by later course modules.

When a case fails in CI, one red run tells you almost nothing: was it
a real regression, or the rare tail of a case that was always slightly
flaky? Rerunning until green *hides* the regression. The right move is to
characterize the failure: replay that one input many times in a fresh, reset
sandbox and measure the distribution.

The two functions below provide the harness core:

  - :func:`replay_case` is the fan-out loop: n rollouts, a world reset
    before every one, infrastructure retries that never touch a verdict.
  - :func:`summarize_rollouts` turns the rollout records into the
    measurement the decision needs: a failure rate with a bootstrap
    interval, the failure-mode breakdown, and the behavioral spread.

The harness supplies the measurement; YOU supply the judgment. A high,
consistent failure rate is a regression to fix and block in CI. A rare
failure should become an evaluation case rather than a reason to block every merge. Record the decision and the measured rate in the homework artifact.

Both functions take injectable callables (`runner`, `reset`) so tests can run
offline with scripted rollouts. The real wiring is
`replay.rollout.world_reset` for the reset and a closure over
`replay.rollout.run_case` + `apply_checks` for the runner; `python -m
replay` (below in __main__.py) assembles exactly that.
"""

from __future__ import annotations

import random
from collections import Counter
from statistics import median
from typing import Any, Callable


class ReplayInfraError(RuntimeError):
    """An infrastructure failure inside one rollout: a timeout, a rate
    limit, a sandbox that failed to start. These are the ONLY failures a
    rollout may be retried for. A verdict (pass or fail) is data and is
    never retried; a verdict flip belongs in the measured failure rate."""


def replay_case(
    runner: Callable[[], dict[str, Any]],
    reset: Callable[[], None],
    n: int = 100,
    max_infra_retries: int = 2,
) -> list[dict[str, Any]]:
    """Fan out n rollouts of one case, resetting the world before each.

    The contract, precisely:

      1. Call ``reset()`` before EVERY rollout, including the first, so each
         rollout starts from the identical world and a write in one rollout
         cannot leak into the next.
      2. Call ``runner()`` once per rollout. It returns a record dict with
         at least {"passed": bool}; pass it through untouched except for
         adding "rollout": i (0-based).
      3. If ``runner()`` raises :class:`ReplayInfraError`, that attempt did
         not produce data: reset and retry the SAME rollout index, up to
         ``max_infra_retries`` retries per rollout. If it still raises after
         the retries are exhausted, re-raise. Count retries per rollout, not
         globally.
      4. NEVER retry a rollout whose runner returned normally, whatever its
         verdict. A failing verdict is a data point, not an error.
      5. Return exactly n records, in rollout order.

    Args:
        runner: runs one rollout against the freshly reset world and returns
            a record dict ({"passed": bool, ...}; the real runner adds
            "steps", "tool_calls", "failure_modes").
        reset: resets the world to its initial state (re-seed or rollback).
        n: number of rollouts (the course default for characterization
           is 100).
        max_infra_retries: retries allowed per rollout for
            ReplayInfraError only.

    Returns:
        A list of exactly n record dicts, each with a "rollout" index added.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    if max_infra_retries < 0:
        raise ValueError("max_infra_retries cannot be negative")

    records: list[dict[str, Any]] = []
    for rollout in range(n):
        retries = 0
        while True:
            reset()
            try:
                record = dict(runner())
            except ReplayInfraError:
                if retries >= max_infra_retries:
                    raise
                retries += 1
                continue
            record["rollout"] = rollout
            records.append(record)
            break
    return records


def summarize_rollouts(
    records: list[dict[str, Any]],
    confidence: float = 0.95,
    bootstrap_iterations: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Turn rollout records into the failure-distribution measurement.

    Each record has at least {"passed": bool}; failing records may carry
    "failure_modes": [str] (which checks or judges failed), and any record
    may carry "steps": int.

    Compute:

      - ``n``: number of records.
      - ``failures``: count of records with passed == False.
      - ``failure_rate``: failures / n.
      - ``ci_low``, ``ci_high``: a percentile bootstrap interval on the
        failure rate. Use ``random.Random(seed)`` and, for each of
        ``bootstrap_iterations`` iterations, resample n records with
        replacement (``rng.choices``) and record that resample's failure
        rate; the interval is the ``alpha/2`` and ``1 - alpha/2`` empirical
        quantiles of those rates, where ``alpha = 1 - confidence``. Sort the
        bootstrap rates and index with ``int(q * (len(rates) - 1))`` for
        quantile q. The same seed must produce the same interval.
      - ``mode_counts``: a dict counting each failure mode across failing
        records (a record listing two modes contributes to both).
      - ``steps``: {"min", "median", "max"} over records that carry "steps"
        (median of an even count is the mean of the two middle values), or
        None when no record carries "steps".

    Returns a dict with exactly those keys. Raises ValueError on an empty
    records list.

    The summary is the measurement; the regression-versus-tail decision is
    yours, made in the write-up, from these numbers.
    """
    if not records:
        raise ValueError("records cannot be empty")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be at least 1")

    n = len(records)
    failures = sum(not bool(record.get("passed")) for record in records)
    failure_rate = failures / n
    rng = random.Random(seed)
    bootstrap_rates = []
    for _ in range(bootstrap_iterations):
        sample = rng.choices(records, k=n)
        bootstrap_rates.append(
            sum(not bool(record.get("passed")) for record in sample) / n
        )
    bootstrap_rates.sort()
    alpha = 1 - confidence
    low_index = int((alpha / 2) * (len(bootstrap_rates) - 1))
    high_index = int((1 - alpha / 2) * (len(bootstrap_rates) - 1))

    mode_counts: Counter[str] = Counter()
    for record in records:
        if not record.get("passed"):
            mode_counts.update(record.get("failure_modes", []))

    step_values = sorted(
        int(record["steps"]) for record in records if "steps" in record
    )
    step_summary = None
    if step_values:
        step_summary = {
            "min": step_values[0],
            "median": median(step_values),
            "max": step_values[-1],
        }

    return {
        "n": n,
        "failures": failures,
        "failure_rate": failure_rate,
        "ci_low": bootstrap_rates[low_index],
        "ci_high": bootstrap_rates[high_index],
        "mode_counts": dict(mode_counts),
        "steps": step_summary,
    }
