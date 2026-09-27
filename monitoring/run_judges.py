"""Run a frozen Homework 5 judge over sampled traces.

Instructor-provided. This is the expensive track of the two-track plan: the
code checks run on 100 percent of the stream because they are free, and the
judges run only on the plan `monitoring/sample.py` produced, asynchronously
off the serving path (here: a batch job, which at course scale is the same
thing).

Each trace dict needs "id" and "text". The text is the normalized
conversation used in Homework 5, including the turns and tool evidence that
the judge needs. The prompt, model, wrapper, and verdict parser stay pinned.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from analysis.helpers.tools import _load_judge, _test_labels_and_preds
from agent.agent import LITELLM_COURSE_MODELS


def _decode_judge_rows(
    rows: list[dict[str, Any]], trace_ids: list[str]
) -> dict[str, int]:
    """Decode the Pass or Fail records used by Homework 5."""
    predictions: dict[str, int] = {}
    expected = set(trace_ids)
    for row in rows:
        trace_id = str(row.get("trace_id", ""))
        if trace_id not in expected or trace_id in predictions:
            raise ValueError("judge returned an unexpected or duplicate trace id")
        critique = row.get("critique")
        if not isinstance(critique, str) or not critique.strip():
            raise ValueError(f"judge result for {trace_id} needs a critique")
        verdict = str(row.get("result", "")).strip().lower().rstrip(".")
        if verdict not in {"pass", "passed", "fail", "failed"}:
            verdict = "fail"
        predictions[trace_id] = 1 if verdict in {"pass", "passed"} else 0
    missing = expected - set(predictions)
    if missing:
        raise ValueError(f"judge returned no result for {sorted(missing)[:5]}")
    return predictions


def load_monitoring_judge(judge_id: str) -> dict[str, Any]:
    """Load the exact frozen judge selected for monitoring."""
    judge = _load_judge(judge_id)
    if judge.get("status") != "frozen":
        raise ValueError(f"judge {judge_id!r} is not frozen")
    return judge


def judge_test_data(judge_id: str) -> tuple[list[int], list[int]]:
    """Return failure-positive human labels and predictions for correction."""
    return _test_labels_and_preds(load_monitoring_judge(judge_id))


def judge_sample(
    judge_id: str, traces: list[dict[str, Any]]
) -> dict[str, int]:
    """Run the exact frozen judge over the sampled traces.

    Returns trace_id -> 0/1 verdict in the failure-positive convention the
    whole course uses (1 = the failure is present, i.e. the judge said
    "fail"). Requires the judge model's API key.
    """
    if not traces:
        raise ValueError("no traces to judge")
    trace_ids = [str(trace.get("id", "")) for trace in traces]
    if any(not trace_id for trace_id in trace_ids) or len(set(trace_ids)) != len(
        trace_ids
    ):
        raise ValueError("traces need nonempty, unique ids")
    if any(not str(trace.get("text", "")).strip() for trace in traces):
        raise ValueError("every trace needs normalized conversation text")

    from docetl.api import Dataset, MapOp, Pipeline, PipelineOutput, PipelineStep

    judge = load_monitoring_judge(judge_id)
    with tempfile.TemporaryDirectory(prefix="cartwheel-monitor-") as directory:
        root = Path(directory)
        input_path = root / "traces.json"
        output_path = root / "out.json"
        input_path.write_text(
            json.dumps(
                [
                    {"trace_id": trace_id, "content": trace["text"]}
                    for trace_id, trace in zip(trace_ids, traces, strict=True)
                ]
            ),
            encoding="utf-8",
        )
        operation = MapOp(
            name="classify_failure_mode",
            type="map",
            model=LITELLM_COURSE_MODELS.get(judge["model"], judge["model"]),
            prompt=(
                f"{judge['prompt_text']}\n\n"
                "--- Trace to evaluate ---\n"
                "{{ input.content }}\n\n"
                "First write a critique of the trace against the criterion. "
                "Use specific evidence from the provided trace. Then return result "
                "as exactly Pass when the named failure is absent, or Fail when present."
            ),
            output={"schema": {"critique": "string", "result": "string"}},
        )
        pipeline = Pipeline(
            name="cartwheel_monitor",
            datasets={"traces": Dataset(type="file", path=str(input_path))},
            operations=[operation],
            steps=[
                PipelineStep(
                    name="classify",
                    input="traces",
                    operations=["classify_failure_mode"],
                )
            ],
            output=PipelineOutput(
                type="file",
                path=str(output_path),
                intermediate_dir=str(root),
            ),
        )
        pipeline.run()
        rows = json.loads(output_path.read_text(encoding="utf-8"))

    pass_positive = _decode_judge_rows(rows, trace_ids)
    return {trace_id: 1 - prediction for trace_id, prediction in pass_positive.items()}
