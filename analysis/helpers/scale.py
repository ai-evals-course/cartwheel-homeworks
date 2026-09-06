"""DocETL backend for applying a judge to a trace collection.

``run_judge`` dispatches development, test, and unlabeled batches through a
DocETL map operation using the model recorded with the judge. DocETL supplies
structured output, parallel execution, and caching. Tests and the offline
demonstration inject a stubbed classifier and never make a live model call.

Tests and the demo pass an explicit ``classify`` callable into
``run_judge``, so control never reaches layers 1 or 2 offline. This module
guards that boundary: :func:`classify_store` raises a clear error rather than
silently calling a model when no backend is configured.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from . import _state

# Course model name -> LiteLLM model id for evaluator execution.
# The aliases allow a registered judge to use a short course-facing name.
# Anything not in this table is passed to LiteLLM verbatim, so a student can
# name any LiteLLM-routable model.
_SCALE_MODEL_LITELLM = {
    "gemini-flash": "gemini/gemini-flash-latest",
    "gemini-flash-lite": "gemini/gemini-flash-lite-latest",
    "gpt-nano": "gpt-5.5-nano",
}


def load_store_traces() -> list[dict[str, Any]]:
    """Load the full store slice the frozen judge scales over.

    Sources from Langfuse when it is configured (``LANGFUSE_*`` present),
    pulling the error analysis trace slice via
    :func:`analysis.helpers.langfuse_io.fetch_traces`; otherwise reads and
    normalizes the committed export at ``state/store_traces.json``. A
    configured Langfuse failure is surfaced rather than replaced with demo
    data, because silently evaluating a different trace collection would
    invalidate the result.
    """
    from . import langfuse_io

    if langfuse_io.is_configured():
        traces = langfuse_io.fetch_traces()
        if not traces:
            raise ValueError("Langfuse returned no traces for the Module 2 slice")
        return traces
    from .normalization import normalize_traces

    records = _state.read_json(_state.state_path("store_traces.json"), default=[])
    return normalize_traces(records) if records else []


def _backend() -> str:
    """Resolve the active scaling backend from the environment.

    Return ``docetl`` when a model key is present and ``none`` in an offline
    environment.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "docetl"
    return "none"


def classify_store(
    prompt_text: str,
    judge_model: str,
    trace_ids: list[str],
    classify: Callable[[str, list[str]], dict[str, int]] | None = None,
) -> dict[str, int]:
    """Classify ``trace_ids`` with the judge prompt over the full store.

    Args:
        prompt_text: the frozen judge prompt.
        judge_model: the model recorded with the judge.
        trace_ids: the store traces to classify.
        classify: an explicit classifier ``fn(prompt, ids) -> {id: 0|1}``.
            When provided (tests, offline demo), it is used directly and no
            live model is touched.

    Returns:
        ``{trace_id: 0|1}``.

    Raises:
        RuntimeError when no ``classify`` is given and no backend is
        configured, so a test can never fall through to a live call by
        accident.
    """
    if classify is not None:
        return {str(tid): int(v) for tid, v in classify(prompt_text, trace_ids).items()}

    backend = _backend()
    if backend == "docetl":
        return _classify_docetl(prompt_text, trace_ids, judge_model)
    raise RuntimeError(
        "no scaling backend configured and no classify callable passed. "
        "Configure a model key for DocETL, or pass classify= (tests and the "
        "offline demo do this so no "
        "live model is ever called)."
    )


# ---------------------------------------------------------------------------
# shared cheap-model plumbing (LiteLLM)
# ---------------------------------------------------------------------------


def _litellm_model_id(model: str) -> str:
    """Map the course scale-model name to a LiteLLM-routable model id."""
    return _SCALE_MODEL_LITELLM.get(model, model)


def _trace_text(trace_id: str, traces_by_id: dict[str, dict[str, Any]] | None = None) -> str:
    """The text the cheap judge classifies for one trace.

    Uses the normalized content loaded from Langfuse or the committed export.
    An identifier without content is rejected because an LLM judge cannot
    evaluate a trace it has not received.
    """
    index = traces_by_id or {trace["trace_id"]: trace for trace in load_store_traces()}
    trace = index.get(str(trace_id))
    if trace and trace.get("text"):
        return str(trace["text"])
    raise ValueError(f"trace {trace_id} has no normalized content for judge evaluation")


def _classify_docetl(
    prompt_text: str, trace_ids: list[str], model: str
) -> dict[str, int]:  # pragma: no cover - live path
    """Apply the judge to a trace batch with one DocETL map operation.

    The operation uses the model recorded with the judge and returns one
    structured binary classification per trace.

    Pipeline or schema errors are surfaced to the caller. A failed batch must
    not silently change execution engines or convert missing predictions into
    passing labels.
    """
    try:
        import docetl  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "DocETL is not installed. Run uv sync in the Cartwheel project."
        ) from exc

    return _run_docetl_map(prompt_text, trace_ids, model)


def _run_docetl_map(  # pragma: no cover - requires the docetl extra + a live key
    prompt_text: str, trace_ids: list[str], model: str
) -> dict[str, int]:
    """One DocETL ``map`` operation classifying each trace as 0/1.

    Writes the trace slice to a temp JSON dataset, builds a Pipeline with a
    single map op whose prompt wraps the frozen judge prompt, runs it, and
    reads the per-trace answers back. Uses DocETL's declarative Python API
    (``Dataset``, ``MapOp``, ``PipelineStep``, ``PipelineOutput``,
    ``Pipeline``).
    """
    import tempfile

    from docetl.api import (
        Dataset,
        MapOp,
        Pipeline,
        PipelineOutput,
        PipelineStep,
    )

    store = {trace["trace_id"]: trace for trace in load_store_traces()}
    rows = [
        {"trace_id": tid, "content": _trace_text(tid, store)} for tid in trace_ids
    ]
    tmpdir = Path(tempfile.mkdtemp(prefix="cartwheel-docetl-"))
    in_path = tmpdir / "traces.json"
    out_path = tmpdir / "out.json"
    in_path.write_text(json.dumps(rows), encoding="utf-8")

    map_op = MapOp(
        name="classify_failure_mode",
        type="map",
        model=_litellm_model_id(model),
        prompt=(
            f"{prompt_text}\n\n"
            "--- Trace to evaluate ---\n"
            "{{ input.content }}\n\n"
            "Return passes_mode as true when the trace passes the criterion, "
            "and false when the named failure is present. Include a short evidence string grounded "
            "only in the provided trace."
        ),
        output={
            "schema": {
                "passes_mode": "boolean",
                "evidence": "string",
            }
        },
    )
    pipeline = Pipeline(
        name="cartwheel_judge_batch",
        datasets={"traces": Dataset(type="file", path=str(in_path))},
        operations=[map_op],
        steps=[
            PipelineStep(name="classify", input="traces", operations=["classify_failure_mode"])
        ],
        output=PipelineOutput(type="file", path=str(out_path), intermediate_dir=str(tmpdir)),
    )
    pipeline.run()

    produced = json.loads(out_path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for row in produced:
        tid = row.get("trace_id")
        if tid is None:
            continue
        if "passes_mode" not in row:
            raise ValueError(f"DocETL result for trace {tid} has no passes_mode field")
        # Prediction files store failure flags for each named mode, while the
        # evaluator's public convention defines Pass as positive.
        result[str(tid)] = 0 if bool(row["passes_mode"]) else 1
    missing = sorted(set(map(str, trace_ids)) - set(result))
    if missing:
        raise ValueError(f"DocETL returned no result for trace ids: {missing[:5]}")
    return result
