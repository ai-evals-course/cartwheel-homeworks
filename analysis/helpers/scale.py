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


class JudgeBatch(dict[str, int]):
    """Binary predictions with the skill's critiques for disagreement review."""

    def __init__(self) -> None:
        super().__init__()
        self.critiques: dict[str, str] = {}


def _decode_judge_rows(rows: list[dict[str, Any]], trace_ids: list[str]) -> JudgeBatch:
    batch = JudgeBatch()
    expected = set(trace_ids)
    for row in rows:
        tid = str(row.get("trace_id", ""))
        if tid not in expected or tid in batch:
            raise ValueError("DocETL returned an unexpected or duplicate trace id")
        verdict = row.get("result")
        critique = row.get("critique")
        if verdict not in ("Pass", "Fail"):
            raise ValueError(f"DocETL result for trace {tid} must be Pass or Fail")
        if not isinstance(critique, str) or not critique.strip():
            raise ValueError(f"DocETL result for trace {tid} needs a critique")
        batch[tid] = 1 if verdict == "Pass" else 0
        batch.critiques[tid] = critique
    missing = expected - set(batch)
    if missing:
        raise ValueError(f"DocETL returned no result for trace ids: {sorted(missing)[:5]}")
    return batch


def load_store_traces() -> list[dict[str, Any]]:
    """Load the full store slice the frozen judge scales over.

    Use ``CARTWHEEL_JUDGE_TRACE_SOURCE`` for an explicit JSON/JSONL
    export. Otherwise source from Langfuse when configured (``LANGFUSE_*``),
    pulling the error analysis trace slice via
    :func:`analysis.helpers.langfuse_io.fetch_traces`; otherwise reads and
    normalizes the committed export at ``state/store_traces.json``. A
    configured Langfuse failure is surfaced rather than replaced with demo
    data, because silently evaluating a different trace collection would
    invalidate the result.
    """
    source = os.environ.get("CARTWHEEL_JUDGE_TRACE_SOURCE")
    if source:
        from .normalization import normalize_trace

        path = Path(source)
        text = path.read_text(encoding="utf-8")
        records = ([json.loads(line) for line in text.splitlines() if line.strip()]
                   if path.suffix == ".jsonl" else json.loads(text))
        if isinstance(records, dict):
            records = records.get("traces")
        if not isinstance(records, list) or not records:
            raise ValueError("judge trace source must contain a nonempty list of traces")
        traces = [normalize_trace(record) for record in records]
        ids = [trace["trace_id"] for trace in traces]
        if len(set(ids)) != len(ids):
            raise ValueError("judge trace source contains duplicate trace ids")
        return traces

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


def _docetl_map_pass(
    prompt_text: str, trace_ids: list[str], model: str, store: dict[str, Any], *, bypass_cache: bool = False
) -> list[dict[str, Any]]:
    """One DocETL map-operation pass, returning the raw produced rows."""
    import tempfile

    from docetl.api import Dataset, MapOp, Pipeline, PipelineOutput, PipelineStep

    rows = [{"trace_id": tid, "content": _trace_text(tid, store)} for tid in trace_ids]
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
            "First write a critique of the trace against the criterion. "
            "Use specific evidence from the provided trace. Then return result "
            "as exactly Pass when the named failure is absent, or Fail when present."
        ),
        output={
            "schema": {
                "critique": "string",
                "result": "string",
            }
        },
        bypass_cache=bypass_cache,
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
    return json.loads(out_path.read_text(encoding="utf-8"))


def _run_docetl_map(  # pragma: no cover - requires the docetl extra + a live key
    prompt_text: str, trace_ids: list[str], model: str
) -> dict[str, int]:
    """One DocETL ``map`` operation classifying each trace as 0/1.

    Writes the trace slice to a temp JSON dataset, builds a Pipeline with a
    single map op whose prompt wraps the frozen judge prompt, runs it, and
    reads the per-trace answers back. Uses DocETL's declarative Python API
    (``Dataset``, ``MapOp``, ``PipelineStep``, ``PipelineOutput``,
    ``Pipeline``).

    Occasionally the model returns a result outside {"Pass", "Fail"} (e.g.
    "Not found") for one trace in a batch, usually on an unusually long
    trace. DocETL's own completion cache then serves that same invalid
    response on every naive retry (same prompt + content -> same cache key),
    so a plain retry never recovers. One bypass-cache retry, scoped to only
    the offending trace ids, is enough to get a fresh classification without
    re-paying for the traces that already came back valid.
    """
    store = {trace["trace_id"]: trace for trace in load_store_traces()}
    produced = _docetl_map_pass(prompt_text, trace_ids, model, store)

    invalid_ids = {
        str(row.get("trace_id", ""))
        for row in produced
        if row.get("result") not in ("Pass", "Fail")
    }
    if invalid_ids:
        retried = _docetl_map_pass(
            prompt_text, sorted(invalid_ids), model, store, bypass_cache=True
        )
        retried_by_id = {str(row["trace_id"]): row for row in retried}
        produced = [
            retried_by_id.get(str(row.get("trace_id", "")), row) for row in produced
        ]

    # HW5 labels and public predictions use Pass=1, Fail=0.
    return _decode_judge_rows(produced, trace_ids)
