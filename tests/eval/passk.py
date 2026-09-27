"""pass@k, pass^k, and the CI result for one case (Module 3, Lecture 1.3).

Your agent samples, so a single end-to-end run is a noisy measurement. These
three functions turn n observed runs of one evaluation case into a signal and a
decision:

  - :func:`pass_at_k` answers the capability question: can the agent EVER get
    this right? It rises with k.
  - :func:`pass_hat_k` (read "pass hat k") answers the reliability question:
    can the agent be trusted EVERY time? It falls with k.
  - :func:`case_passes` applies the course's CI rule: a regression case
    blocks on any failed run; a capability case never blocks CI, but its
    pass rate is reported for tracking.

CI must use the reliability view. The same 6-of-8 agent reads as 1.000 under
pass@4 and 0.214 under pass^4. Passing the case because one run in eight
succeeded would allow a broken behavior to merge.

All three are pure functions. No model call, no I/O. The homework tests pin
the worked numbers from the lecture (Artifact G), so a correct implementation
reproduces them exactly.
"""

from __future__ import annotations

from math import comb
from typing import Any


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator of pass@k from n runs with c successes.

    pass@k is the probability that AT LEAST ONE of k i.i.d. runs succeeds.
    The naive estimate (run k times, check if any passed) wastes runs; the
    unbiased estimator from n >= k runs is:

        pass@k = 1 - C(n - c, k) / C(n, k)

    where C is the binomial coefficient (math.comb). The subtracted term is
    the probability that a random size-k subset of the n runs contains only
    failures. When there are fewer than k failures (n - c < k), every size-k
    subset contains a success, so pass@k = 1.0 exactly.

    Args:
        n: total number of runs (n >= 1).
        c: number of successful runs (0 <= c <= n).
        k: subset size (1 <= k <= n).

    Returns:
        The estimate as a float in [0, 1].

    Raises:
        ValueError: if n < 1, c is outside [0, n], or k is outside [1, n].

    Worked numbers (Artifact G, n=8, c=6):
        pass_at_k(8, 6, 1) == 0.75
        pass_at_k(8, 6, 2) == 1 - C(2,2)/C(8,2) == 1 - 1/28 == 0.9642857...
        pass_at_k(8, 6, 4) == 1.0  (only 2 failures, so every 4-subset hits
                                    a success)
    """
    ### YOUR CODE HERE (hw6)
    raise NotImplementedError("hw6: implement pass_at_k")


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Estimator of pass^k from n runs with c successes.

    pass^k is the probability that ALL k i.i.d. runs succeed (tau-bench,
    Yao et al. 2024). The estimator from n >= k runs is:

        pass^k = C(c, k) / C(n, k)

    which is the probability that a random size-k subset of the n runs
    contains only successes. When there are fewer than k successes (c < k),
    no size-k subset is all-success, so pass^k = 0.0 exactly.

    Args:
        n: total number of runs (n >= 1).
        c: number of successful runs (0 <= c <= n).
        k: subset size (1 <= k <= n).

    Returns:
        The estimate as a float in [0, 1].

    Raises:
        ValueError: if n < 1, c is outside [0, n], or k is outside [1, n].

    Worked numbers (Artifact G, n=8, c=6):
        pass_hat_k(8, 6, 2) == C(6,2)/C(8,2) == 15/28 == 0.5357142...
        pass_hat_k(8, 6, 4) == C(6,4)/C(8,4) == 15/70 == 0.2142857...
        pass_hat_k(8, 6, 8) == 0.0  (not all 8 succeeded)
    """
    ### YOUR CODE HERE (hw6)
    raise NotImplementedError("hw6: implement pass_hat_k")


def case_passes(
    kind: str,
    passes: int,
    n: int,
    baseline_pass_rate: float | None = None,
) -> dict[str, Any]:
    """Return the CI decision for one evaluation case run n times.

    The evaluation case set holds two kinds of case:

      - A **regression** case guards a previously fixed bug. Its pinned
        baseline is n of n, and it blocks the merge on ANY failed run
        (`passes < n`). A rerun is allowed only for infrastructure errors
        (those never reach this function; see replay/harness.py), never for
        a verdict flip.
      - A **capability** case covers a core behavior the agent has never
        held reliably. It never blocks CI, because forcing it to pass would
        make CI red forever. Instead, its pass rate is reported in the CI
        log and exported as a Module 5 improvement target.

    Args:
        kind: "regression" or "capability".
        passes: number of observed runs that passed (0 <= passes <= n).
        n: number of observed runs (n >= 1).
        baseline_pass_rate: the pinned per-case baseline in [0, 1], optional.
            Recorded for tracking but does not affect the CI decision.

    Returns:
        A dict with:
          - "decision": "block" or "pass".
          - "reason": one sentence a CI log can print, naming the numbers
            that drove the decision (e.g. "regression case failed 1 of 5
            runs" or "capability case passed 2 of 5, baseline 0.6, not
            blocking").

    Raises:
        ValueError: if kind is not "regression" or "capability", or if
            passes is outside [0, n].

    Worked numbers (Artifact G, n = 5):
        case_passes("regression", 5, 5)          -> pass
        case_passes("regression", 4, 5)          -> block (any failed run)
        case_passes("capability", 3, 5, 0.6)     -> pass  (never blocks)
        case_passes("capability", 2, 5, 0.6)     -> pass  (never blocks)
        case_passes("capability", 1, 5, 0.6)     -> pass  (never blocks)
    """
    ### YOUR CODE HERE (hw6)
    raise NotImplementedError("hw6: implement case_passes")
