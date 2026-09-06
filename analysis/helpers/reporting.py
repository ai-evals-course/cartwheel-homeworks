"""Bias-corrected prevalence and the failure report.

This module holds the two loop-stage-10 helpers:

  - :func:`corrected_prevalence` turns a frozen judge's raw flag count into
    a bias-corrected prevalence estimate with a bootstrap confidence
    interval with the Rogan-Gladen point estimate and a percentile bootstrap.
    Stored labels mark failure presence, while Module 2 statistics define Pass
    as the positive class. The helper converts the stored values, corrects the
    Pass rate, and reports one minus the corrected Pass rate as failure
    prevalence.
  - :func:`failure_report` emits the validation report Module 3 opens
    (schema: Artifact L).

The calculation is implemented directly with NumPy, so the statistical
method remains inspectable and requires no separate evaluation package.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from . import guards, tools

def _estimate_prevalence(
    test_labels: Sequence[int],
    test_preds: Sequence[int],
    unlabeled_preds: Sequence[int],
    bootstrap_iterations: int = 20000,
    confidence_level: float = 0.95,
    seed: int | None = 7,
) -> tuple[float, float, float]:
    """Return the Rogan-Gladen estimate and a percentile bootstrap interval."""
    # Persisted mode values use 1 for failure present. Convert to the course
    # statistics convention before applying Rogan Gladen.
    labels = 1 - np.asarray(test_labels, dtype=float)
    preds = 1 - np.asarray(test_preds, dtype=float)
    unlabeled = 1 - np.asarray(unlabeled_preds, dtype=float)

    def point(
        sampled_labels: np.ndarray,
        sampled_preds: np.ndarray,
        sampled_unlabeled: np.ndarray,
    ) -> float:
        positive = sampled_labels == 1
        negative = sampled_labels == 0
        if not positive.any() or not negative.any() or not sampled_unlabeled.size:
            return float("nan")
        tpr = sampled_preds[positive].mean()
        tnr = (1 - sampled_preds[negative]).mean()
        denominator = tpr + tnr - 1
        if denominator == 0:
            return float("nan")
        observed = sampled_unlabeled.mean()
        pass_rate = (observed + tnr - 1) / denominator
        pass_rate = float(min(max(pass_rate, 0.0), 1.0))
        return 1 - pass_rate

    estimate = point(labels, preds, unlabeled)
    rng = np.random.default_rng(seed)
    samples = np.empty(bootstrap_iterations, dtype=float)
    for index in range(bootstrap_iterations):
        test_indices = rng.integers(0, len(labels), len(labels))
        unlabeled_indices = rng.integers(0, len(unlabeled), len(unlabeled))
        samples[index] = point(
            labels[test_indices],
            preds[test_indices],
            unlabeled[unlabeled_indices],
        )
    samples = samples[~np.isnan(samples)]
    alpha = (1 - confidence_level) / 2
    low = float(np.quantile(samples, alpha))
    high = float(np.quantile(samples, 1 - alpha))
    return estimate, low, high


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _tpr_tnr(labels: Sequence[int], preds: Sequence[int]) -> tuple[float, float]:
    """Compute TPR for Pass and TNR for Fail from stored failure flags."""
    pass_labels = [1 - int(label) for label in labels]
    pass_preds = [1 - int(pred) for pred in preds]
    tp = sum(1 for l, p in zip(pass_labels, pass_preds) if l == 1 and p == 1)
    fn = sum(1 for l, p in zip(pass_labels, pass_preds) if l == 1 and p == 0)
    tn = sum(1 for l, p in zip(pass_labels, pass_preds) if l == 0 and p == 0)
    fp = sum(1 for l, p in zip(pass_labels, pass_preds) if l == 0 and p == 1)
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    return tpr, tnr


def corrected_prevalence(
    judge_id: str,
    trace_filter: str = "all",
    confidence: float = 0.95,
    *,
    bootstrap_iterations: int = 20000,
    seed: int | None = 7,
) -> dict[str, Any]:
    """Bias-corrected prevalence for a frozen judge over the full store.

    Runs the frozen judge's test predictions against the human test labels
    to recover TPR and TNR, takes the judge's predictions over the selected
    unlabeled slice, and computes the Rogan-Gladen point estimate with a
    bootstrap confidence interval. Stored labels use 1 for failure presence,
    but TPR and TNR use Pass as the positive class. The returned estimate is
    the failure prevalence, computed as one minus corrected Pass prevalence.

    Args:
        judge_id: a frozen judge id (raises via the guard otherwise).
        trace_filter: ``"all"`` for the full store, or a segment key such as
            ``"role:shopper"`` / ``"store:BrewMate Kitchen"`` matched against
            the stored unlabeled predictions' ``segments`` map.
        confidence: confidence level for the interval (default 0.95).
        bootstrap_iterations: number of percentile-bootstrap replicates.
        seed: seed for a reproducible NumPy random-number generator.

    Returns:
        A dict with ``raw`` failure flag rate, ``corrected`` failure prevalence,
        ``ci_low`` / ``ci_high`` / ``confidence``, the ``test_tpr`` /
        ``test_tnr`` used, the ``n_test`` and ``n_unlabeled`` sizes, and a
        ``validity_warning`` (non-empty when TPR + TNR is not comfortably
        above 1, where the Rogan-Gladen correction becomes unstable).
    """
    judge = tools._load_judge(judge_id)
    guards.require_frozen_for_prevalence(judge)

    test_labels, test_preds = tools._test_labels_and_preds(judge)
    if not test_labels:
        raise guards.GuardViolation(
            f"judge '{judge_id}' is frozen but has no scored test split; run "
            "judge_alignment on test before correcting."
        )
    tpr, tnr = _tpr_tnr(test_labels, test_preds)

    unlabeled_preds = tools._unlabeled_preds(judge, trace_filter)
    if not unlabeled_preds:
        raise ValueError(
            f"no unlabeled predictions for filter '{trace_filter}'. Run the "
            "frozen judge over the store slice first (run_judge)."
        )
    raw = sum(unlabeled_preds) / len(unlabeled_preds)

    theta, lo, hi = _estimate_prevalence(
        test_labels,
        test_preds,
        unlabeled_preds,
        bootstrap_iterations=bootstrap_iterations,
        confidence_level=confidence,
        seed=seed,
    )

    validity = ""
    if tpr + tnr <= 1.05:
        validity = (
            f"TPR + TNR = {tpr + tnr:.3f} is not comfortably above 1; the "
            "correction is unstable and the interval will be very wide. "
            "Improve the judge before trusting this estimate."
        )

    return {
        "judge_id": judge_id,
        "mode": judge.get("mode"),
        "trace_filter": trace_filter,
        "raw": round(raw, 4),
        "raw_failure_rate": round(raw, 4),
        "raw_pass_rate": round(1 - raw, 4),
        "corrected": round(float(theta), 4),
        "corrected_failure_prevalence": round(float(theta), 4),
        "corrected_pass_rate": round(1 - float(theta), 4),
        "ci_low": round(float(lo), 4),
        "ci_high": round(float(hi), 4),
        "confidence": confidence,
        "test_tpr": round(tpr, 4),
        "test_tnr": round(tnr, 4),
        "n_test": len(test_labels),
        "n_unlabeled": len(unlabeled_preds),
        "validity_warning": validity,
        "backend": "python-bootstrap",
    }


# ---------------------------------------------------------------------------
# failure_report
# ---------------------------------------------------------------------------

def _mode_prevalence(
    mode_name: str, judge_id: str | None
) -> tuple[dict[str, Any], int, int]:
    """Best-effort prevalence for one mode: ``(block, fail_count, pass_count)``.

    For a judge-backed mode with a frozen judge, ``block`` is the corrected
    estimate; for a code mode or an unfrozen judge it falls back to the raw
    labeled rate so the report is still emittable mid-flight."""
    labels = tools._load_labels(mode_name)
    fail = sum(1 for r in labels if r["label"] == 1)
    total = len(labels)
    raw = round(fail / total, 4) if total else 0.0
    block = {"raw": raw, "corrected": raw, "ci_low": raw, "ci_high": raw, "confidence": 0.95}
    if judge_id is not None:
        judge = tools._load_judge(judge_id)
        if guards.is_frozen(judge) and tools._unlabeled_preds(judge, "all"):
            est = corrected_prevalence(judge_id, "all")
            block = {
                "raw": est["raw"],
                "corrected": est["corrected"],
                "ci_low": est["ci_low"],
                "ci_high": est["ci_high"],
                "confidence": est["confidence"],
            }
    return block, fail, (total - fail)


def failure_report(output_path: str | Path) -> dict[str, Any]:
    """Emit the Module 2 failure report (Artifact L schema).

    Reads the confirmed taxonomy (``patterns.json``), the per-mode labels,
    and the registered judges, and assembles one report entry per confirmed
    or frozen mode. Judge-backed modes carry their frozen judge's test
    TPR/TNR and corrected prevalence with a CI; code-checked modes carry the
    raw human rate and no TPR/TNR. The report preserves requirement sources,
    judge decisions, and examples needed by Module 3 without introducing a
    production prioritization exercise.

    Writes both a JSON file at ``output_path`` and a rendered markdown file
    alongside it (``.md``), and returns the report dict.
    """
    output_path = Path(output_path)
    patterns = tools._load_patterns()
    judges_by_mode = tools._judges_by_mode()

    modes_out: list[dict[str, Any]] = []
    for mode in patterns.get("modes", []):
        name = mode["name"]
        if mode.get("status") not in ("confirmed", "frozen"):
            continue
        judge_id = judges_by_mode.get(name)
        is_code = mode.get("evaluator_type") == "code" or judge_id is None
        prevalence, fail_ct, pass_ct = _mode_prevalence(name, None if is_code else judge_id)

        if is_code:
            evaluator: dict[str, Any] = {"type": "code"}
        else:
            judge = tools._load_judge(judge_id)
            test_labels, test_preds = tools._test_labels_and_preds(judge)
            tpr, tnr = _tpr_tnr(test_labels, test_preds) if test_labels else (None, None)
            evaluator = {
                "type": "judge",
                "judge_id": judge_id,
                "prompt_hash": judge.get("prompt_hash"),
                "test_tpr": round(tpr, 4) if tpr is not None else None,
                "test_tnr": round(tnr, 4) if tnr is not None else None,
                # Stored 0 means Pass: match each interval to its Pass-positive rate.
                "test_tpr_interval": tools._wilson_interval(
                    sum(1 for label, pred in zip(test_labels, test_preds) if label == pred == 0),
                    sum(1 for label in test_labels if label == 0),
                ),
                "test_tnr_interval": tools._wilson_interval(
                    sum(1 for label, pred in zip(test_labels, test_preds) if label == pred == 1),
                    sum(1 for label in test_labels if label == 1),
                ),
                "test_class_counts": {
                    "failure": sum(1 for label in test_labels if label == 1),
                    "nonfailure": sum(1 for label in test_labels if label == 0),
                },
                "decision": mode.get("judge_decision", "use" if test_labels else None),
            }

        entry = {
            "name": name,
            "definition": mode.get("definition", ""),
            "requirement_source": mode.get("requirement_source"),
            "evaluator": evaluator,
            "labeled_counts": {"fail": fail_ct, "pass": pass_ct},
            "human_judgment_counts": {"failure": fail_ct, "nonfailure": pass_ct},
            "prevalence": prevalence,
            "examples": list(mode.get("example_trace_ids", [])),
            "evaluation_case_candidates": list(mode.get("evaluation_case_candidates", [])),
        }
        modes_out.append(entry)

    modes_out.sort(key=lambda mode: mode["name"])

    report = {
        "generated_at": _utcnow(),
        "modes": modes_out,
    }
    tools._state.write_json(output_path, report)
    _render_markdown(report, output_path.with_suffix(".md"))
    return report


def _render_markdown(report: dict[str, Any], md_path: Path) -> None:
    lines: list[str] = ["# Cartwheel failure report", ""]
    for mode in report["modes"]:
        prev = mode["prevalence"]
        lines.append(f"## {mode['name']}")
        lines.append("")
        lines.append(mode["definition"])
        lines.append("")
        if mode["requirement_source"]:
            lines.append(f"- Requirement source: {mode['requirement_source']}")
        ev = mode["evaluator"]
        if ev["type"] == "judge":
            lines.append(
                f"- Evaluator: judge `{ev['judge_id']}` "
                f"(test TPR {ev['test_tpr']}, TNR {ev['test_tnr']}, "
                f"decision {ev['decision']})"
            )
        else:
            lines.append("- Evaluator: code check")
        lines.append(
            f"- Prevalence: raw {prev['raw']}, corrected {prev['corrected']} "
            f"(95% CI {prev['ci_low']}-{prev['ci_high']})"
        )
        lines.append(
            f"- Labeled: {mode['labeled_counts']['fail']} fail / "
            f"{mode['labeled_counts']['pass']} pass"
        )
        if mode["examples"]:
            lines.append(f"- Examples: {', '.join(mode['examples'])}")
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
