"""Write monitoring verdicts and corrected prevalence back to Langfuse.

The corrected number should live next to the traces it came from, so the
dashboard and the annotation queues see it. Langfuse's Scores API updates a
score when a later request uses the same ``score_id``. A repeated monitoring
run therefore updates an existing score instead of creating a duplicate.
Building the score records is your hole. The code that writes them to
Langfuse is provided below it.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _stable_id(*parts: str) -> str:
    """A deterministic 32-hex id from the given parts (helper, provided)."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def build_score_records(
    mode: str,
    random_verdicts: dict[str, int],
    risk_verdicts: dict[str, int],
    estimate: dict[str, Any],
    batch_label: str,
) -> list[dict[str, Any]]:
    """Build repeatable Langfuse score records for one monitoring run.

    The function creates three kinds of scores. They use stable identifiers so
    a repeated run updates existing scores instead of creating duplicates:

      1. **Random-sample verdicts.** One record per trace in
         ``random_verdicts``:
         ``name`` is ``f"{mode}_verdict"``, ``value`` is the 0/1 verdict as
         a float, ``data_type`` is "NUMERIC", ``trace_id`` is the trace's
         id, and ``score_id`` is ``_stable_id(mode, "verdict", trace_id)``.
      2. **Risk-group verdicts.** One record per trace in ``risk_verdicts``:
         ``name`` is ``f"{mode}_risk_verdict"`` and ``score_id`` is
         ``_stable_id(mode, "risk_verdict", trace_id)``. The other fields
         match the random-sample verdict records. A trace in both samples
         receives both scores.
      3. **The corrected prevalence,** one record attached to the batch
         rather than a trace: ``name`` is ``f"{mode}_corrected_prevalence"``,
         ``value`` is ``estimate["corrected"]``, ``data_type`` is "NUMERIC",
         ``trace_id`` is None, ``comment`` carries the interval as
         ``f"95% CI {ci_low}-{ci_high}, raw {raw}, n={n_sample}"`` (use the
         estimate's fields verbatim), and ``score_id`` is
         ``_stable_id(mode, "prevalence", batch_label)``.

    Ordering: the random records, the risk records, then the prevalence
    record. Preserve each verdict dictionary's insertion order.

    Calling the function twice with the same arguments must return records
    with identical ``score_id`` values. The Scores API treats a repeated
    ``score_id`` as an update.

    Args:
        mode: the failure mode, e.g. "unsupported_policy_claim".
        random_verdicts: trace_id -> 0/1 verdict for the random sample.
        risk_verdicts: trace_id -> 0/1 verdict for the risk groups.
        estimate: the dict returned by
            :func:`monitoring.correct.corrected_mode_prevalence`.
        batch_label: names the batch, e.g. "2026-W28". The label is part of
            the period prevalence score identifier, but not a trace verdict
            identifier.

    Returns:
        A list of score record dicts with keys: score_id, name, value,
        data_type, trace_id, comment (comment is None for verdicts).
    """
    ### YOUR CODE HERE (hw7)
    raise NotImplementedError("hw7: implement build_score_records")


# ---------------------------------------------------------------------------
# The POST wiring (instructor-provided). Gated on the LANGFUSE_* env vars the
# same way analysis/helpers/langfuse_io.py is, so nothing here runs offline.
# ---------------------------------------------------------------------------


def post_scores(records: list[dict[str, Any]]) -> int:
    """Write score records to Langfuse. Returns the number written.

    Uses the SDK's ``create_score`` with the ``score_id`` idempotency
    parameter, so writing a record again updates the existing score.
    """
    from analysis.helpers import langfuse_io

    if not langfuse_io.is_configured():
        raise langfuse_io.LangfuseNotConfigured(
            "set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST "
            "to write scores; the offline path only builds score records"
        )
    from langfuse import get_client

    client = get_client()
    for record in records:
        kwargs: dict[str, Any] = {
            "name": record["name"],
            "value": record["value"],
            "data_type": record["data_type"],
            "score_id": record["score_id"],
        }
        if record.get("trace_id") is not None:
            kwargs["trace_id"] = record["trace_id"]
        if record.get("comment"):
            kwargs["comment"] = record["comment"]
        client.create_score(**kwargs)
    client.flush()
    return len(records)
