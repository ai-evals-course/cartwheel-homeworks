"""The agent-facing helper functions of the error-analysis skill.

These are the functions the coding agent calls across the error-analysis
loop. They are *instructor-provided and fully implemented*: students call
them, they are not homework holes. Each wraps file-backed state under
``analysis/state/`` (Artifact J layout). DocETL executes judge batches, while
the statistical helpers operate directly on persisted labels and predictions.

Loop-stage map (Outline helper table):

  - :func:`select_traces`     stages 1, 4  (open-coding / coverage batches)
  - :func:`next_to_label`     stages 6, 9  (collect additional human judgments)
  - :func:`split_labels`      stage 8       (train/dev/test)
  - :func:`register_judge`    stages 7, 9   (each prompt edit is a version)
  - :func:`run_judge`         stages 8-10   (cached predictions)
  - :func:`judge_alignment`   stages 8, 9   (TPR/TNR/agreement on a split)
  - :func:`iteration_log`     stage 9       (the hill-climbing table)
  - :func:`freeze_judge`      stage 9       (locks the version, unlocks test)

The prevalence and reporting helpers (:func:`corrected_prevalence`,
:func:`failure_report`) live in ``reporting.py`` and re-export from the
package root.

State access here is deliberately explicit and dependency-light so every
run is inspectable. The prevalence calculation lives in ``reporting.py``;
the selection signals (clustering, semantic neighbors,
uncertainty) live in ``selection.py``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import os
from pathlib import Path
from typing import Any

from . import _state, guards, scale, selection

# ---------------------------------------------------------------------------
# small shared utilities
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _prompt_hash(prompt_text: str, model: str) -> str:
    """Stable short hash of (prompt, model), used as the version fingerprint
    and the prediction-cache key. The model is folded in because the same
    prompt on a different judge model is a different classifier."""
    digest = hashlib.sha256(f"{model}\n{prompt_text}".encode("utf-8")).hexdigest()
    return digest[:12]


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float | None]:
    """Return a two sided Wilson interval for one binomial rate."""
    if total <= 0:
        return [None, None]
    rate = successes / total
    denominator = 1 + (z * z / total)
    center = (rate + (z * z / (2 * total))) / denominator
    margin = (
        z
        * math.sqrt((rate * (1 - rate) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


# ---------------------------------------------------------------------------
# state loaders (also used by reporting.py)
# ---------------------------------------------------------------------------


def _load_patterns() -> dict[str, Any]:
    return _state.read_json(_state.state_path("patterns.json"), default={"modes": []})


def _labels_path(mode: str) -> Path:
    return _state.state_path("labels", f"{mode}.jsonl")


def _load_labels(mode: str) -> list[dict[str, Any]]:
    """Return the *current* label per trace for ``mode``.

    Label files are append-only: a flip appends a new record and marks the
    prior one ``superseded_by``. This collapses the log to the live label
    per trace by dropping any record that has been superseded, and among the
    remaining records for a trace keeps the last one written.
    """
    rows = _state.read_jsonl(_labels_path(mode))
    # A record is dead once it carries a ``superseded_by`` pointer (Artifact L:
    # the field is set on the old record when a flip appends its replacement).
    # Nothing is overwritten, so the file keeps the full flip history; this
    # collapses it to the live label per trace. Among the surviving records for
    # a trace, the last one written wins (append order is chronological).
    live: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("superseded_by"):
            continue
        live[row["trace_id"]] = row
    return list(live.values())


def _judge_path(judge_id: str) -> Path:
    return _state.state_path("judges", f"{judge_id}.json")


def _load_judge(judge_id: str) -> dict[str, Any]:
    judge = _state.read_json(_judge_path(judge_id), default=None)
    if judge is None:
        raise FileNotFoundError(
            f"no judge '{judge_id}' under state/judges/. Register it first "
            "with register_judge."
        )
    return judge


def _judges_by_mode() -> dict[str, str]:
    """Map each mode to its frozen judge id when one exists, else its most
    recently registered judge id."""
    out: dict[str, str] = {}
    latest: dict[str, tuple[str, str]] = {}  # mode -> (ts, judge_id)
    judges_dir = _state.state_path("judges")
    if not judges_dir.exists():
        return out
    for path in sorted(judges_dir.glob("*.json")):
        judge = _state.read_json(path)
        mode = judge.get("mode")
        if not mode:
            continue
        if guards.is_frozen(judge):
            out[mode] = judge["judge_id"]
            continue
        ts = judge.get("created_at", "")
        if mode not in latest or ts >= latest[mode][0]:
            latest[mode] = (ts, judge["judge_id"])
    for mode, (_, jid) in latest.items():
        out.setdefault(mode, jid)
    return out


def _test_labels_and_preds(judge: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Return aligned (human test labels, judge test predictions) for the
    frozen judge, in a fixed trace order. Reads the persisted test-split
    assignment and the cached predictions for this judge's frozen prompt."""
    mode = judge["mode"]
    splits = _state.read_json(_state.state_path("splits.json"), default={})
    test_ids = splits.get(mode, {}).get("test", [])
    labels_by_trace = {r["trace_id"]: r["label"] for r in _load_labels(mode)}
    preds_by_trace = _cached_preds(judge)
    test_labels: list[int] = []
    test_preds: list[int] = []
    for tid in test_ids:
        if tid in labels_by_trace and tid in preds_by_trace:
            test_labels.append(int(labels_by_trace[tid]))
            test_preds.append(int(preds_by_trace[tid]))
    return test_labels, test_preds


def _unlabeled_preds(judge: dict[str, Any], trace_filter: str) -> list[int]:
    """Return the frozen judge's predictions over the unlabeled store slice
    selected by ``trace_filter`` (``all`` or ``key:value`` against each
    prediction's ``segments`` map)."""
    store = judge.get("store_predictions", {})
    rows = store.get("predictions", [])
    if trace_filter == "all":
        return [int(r["pred"]) for r in rows]
    if ":" not in trace_filter:
        raise ValueError(
            f"trace_filter '{trace_filter}' is neither 'all' nor 'key:value'"
        )
    key, value = trace_filter.split(":", 1)
    return [int(r["pred"]) for r in rows if r.get("segments", {}).get(key) == value]


def _cached_preds(judge: dict[str, Any]) -> dict[str, int]:
    """Predictions cached by (prompt hash, trace id) for this judge's current
    prompt version. Stored on the judge record under ``predictions`` keyed by
    prompt hash."""
    cache = judge.get("predictions", {})
    return {tid: int(p) for tid, p in cache.get(judge["prompt_hash"], {}).items()}


# ---------------------------------------------------------------------------
# trace source resolution (Langfuse or a file export)
# ---------------------------------------------------------------------------


def _load_trace_source(trace_source: str | Path | None) -> list[dict[str, Any]]:
    """Load normalized traces from an export path or explicit live source.

    The "langfuse" source requires configured Langfuse and nonempty results.
    For offline analysis, pass a Module 1 export such as
    ``traces/support_traces.json`` from ``scenarios.export_langfuse``.
    Each reader normalizes its records before returning them.
    """
    if isinstance(trace_source, str) and trace_source.lower() == "langfuse":
        from . import langfuse_io

        if not langfuse_io.is_configured():
            raise langfuse_io.LangfuseNotConfigured(
                "Langfuse is not configured. Configure LANGFUSE_PUBLIC_KEY, "
                "LANGFUSE_SECRET_KEY, and LANGFUSE_HOST, or pass a trace "
                "export path for offline analysis."
            )
        traces = langfuse_io.fetch_traces()
        if not traces:
            raise ValueError("Langfuse returned no traces for the Module 2 slice")
        return traces
    return selection.load_traces(trace_source)


# ---------------------------------------------------------------------------
# select_traces
# ---------------------------------------------------------------------------


def select_traces(
    trace_source: str | Path,
    k: int,
    strategy: str = "diversity",
    exclude_ids: list[str] | None = None,
) -> list[dict[str, str]]:
    """Pick a diverse batch of traces to read, and persist the manifest.

    Reading traces in logged order surfaces only the most common patterns,
    so the ``diversity`` strategy clusters the store on trace features and
    returns cluster representatives (two thirds) plus random picks (one
    third), because clustering never captures every dimension.

    Args:
        trace_source: a Langfuse export path (JSON/JSONL of trace records), or
            the literal ``"langfuse"`` to pull the
            error-analysis slice live from configured Langfuse. Empty live
            results raise. For offline use, pass a Module 1 export such as
            ``traces/support_traces.json``.
        k: batch size (the demo default is 24).
        strategy: ``"diversity"`` (default), ``"random"``, or ``"outlier"``
            (interquartile-range flags on a numeric feature).
        exclude_ids: trace ids already read, skipped this batch.

    Returns:
        A list of ``{"trace_id": ..., "reason": ...}`` dicts, one per pick,
        with a one-line reason. Review records are persisted to
        ``state/samples.json`` and selection details to
        ``state/sample_manifest.json``.
    """
    exclude = set(exclude_ids or [])
    traces = _load_trace_source(trace_source)
    picks = selection.select(traces, k=k, strategy=strategy, exclude_ids=exclude)
    traces_by_id = {trace["id"]: trace for trace in traces}
    samples = []
    for pick in picks:
        trace = traces_by_id[pick["trace_id"]]
        samples.append(
            {
                "trace_id": trace["trace_id"],
                "reason": pick["reason"],
                "trace": trace["trace"],
                "text": trace["text"],
                "features": trace["features"],
                "meta": trace["meta"],
                "permalink": trace.get("permalink"),
                "flags": [],
            }
        )
    manifest = {
        "source": str(trace_source),
        "k": k,
        "strategy": strategy,
        "selected_at": _utcnow(),
        "picks": picks,
    }
    # File sources are relative to state so the export and state can move
    # together. The marker distinguishes them from older manifest paths.
    if not (isinstance(trace_source, str) and trace_source.lower() == "langfuse"):
        source_path = Path(trace_source).resolve()
        try:
            relative_source = os.path.relpath(source_path, _state.state_root().resolve())
        except ValueError:  # Windows cannot make relative paths across drives.
            manifest["source"] = str(source_path)
        else:
            manifest["source"] = relative_source.replace(os.sep, "/")
            manifest["source_relative_to"] = "state"
    _state.write_json(_state.state_path("samples.json"), samples)
    _state.write_json(_state.state_path("sample_manifest.json"), manifest)
    return samples


# ---------------------------------------------------------------------------
# next_to_label
# ---------------------------------------------------------------------------


def next_to_label(
    mode: str,
    k: int,
    strategy: str = "enrich",
    trace_source: str | Path | None = None,
) -> list[dict[str, str]]:
    """Propose the next traces to label for ``mode``, enriched for signal.

    Failures are rare in the wild, so labeling in store order wastes effort.
    Strategies:

      - ``enrich`` (default): semantic neighbors of the confirmed failures,
        which finds more of the same failure.
      - ``uncertainty``: traces where the judge flips across repeated runs at
        temperature above zero (its least certain calls).
      - ``disagreement``: traces where a code check and the judge conflict.
      - ``random``: a uniform sample, for calibration.

    Args:
        mode: the failure mode to grow the pool for.
        k: how many candidates to propose.
        strategy: one of the four above.
        trace_source: override the trace source; defaults to the last
            ``select_traces`` source recorded in ``sample_manifest.json``.
            With no recorded source, returns no candidates.

    Returns:
        ``{"trace_id": ..., "signal": ...}`` dicts naming why each was
        picked, excluding already-labeled traces.
    """
    labeled = {r["trace_id"] for r in _load_labels(mode)}
    confirmed_failures = [r["trace_id"] for r in _load_labels(mode) if r["label"] == 1]
    source = trace_source
    if source is None:
        manifest = _state.read_json(
            _state.state_path("sample_manifest.json"), default={}
        )
        source = manifest.get("source")
        if source is not None and manifest.get("source_relative_to") == "state":
            source = _state.state_path(source)
    traces = _load_trace_source(source) if source is not None else []
    return selection.next_candidates(
        traces,
        mode=mode,
        k=k,
        strategy=strategy,
        confirmed_failures=confirmed_failures,
        already_labeled=labeled,
    )


# ---------------------------------------------------------------------------
# split_labels
# ---------------------------------------------------------------------------


def split_labels(
    mode: str,
    fractions: tuple[float, float, float] = (0.15, 0.425, 0.425),
    seed: int = 7,
    min_per_class: int = 10,
) -> dict[str, list[str]]:
    """Split the human judgments for ``mode`` into disjoint train/dev/test.

    Train supplies few-shot examples (any trace in the prompt is banned from
    dev and test), dev is where refinement is scored, and test is touched
    once after freezing. The split is stratified by label so each split
    holds both classes, and it refuses to proceed when a class is too thin
    to land ``min_per_class`` examples in the smaller eval split (the guard),
    because a test split with only two examples from either class cannot
    support a useful estimate for the corresponding rate.

    Args:
        mode: the failure mode whose human judgments are split.
        fractions: (train, dev, test); defaults to 0.15 / 0.425 / 0.425.
        seed: RNG seed for a reproducible shuffle (demo seed is 7).
        min_per_class: minimum examples of each class the smaller eval split
            must be able to hold; below this the split raises.

    Returns:
        ``{"train": [...], "dev": [...], "test": [...]}`` of trace ids,
        persisted to ``state/splits.json`` under ``mode``. The three lists
        are disjoint.
    """
    import random

    labels = _load_labels(mode)
    if not labels:
        raise ValueError(f"no labels for mode '{mode}'; label some traces first.")
    fails = sorted(r["trace_id"] for r in labels if r["label"] == 1)
    passes = sorted(r["trace_id"] for r in labels if r["label"] == 0)

    guards.check_split_class_counts(len(fails), len(passes), min_per_class, fractions)

    rng = random.Random(seed)
    rng.shuffle(fails)
    rng.shuffle(passes)

    def _partition(items: list[str]) -> tuple[list[str], list[str], list[str]]:
        n = len(items)
        n_train = round(n * fractions[0])
        n_dev = round(n * fractions[1])
        train = items[:n_train]
        dev = items[n_train : n_train + n_dev]
        test = items[n_train + n_dev :]
        return train, dev, test

    f_train, f_dev, f_test = _partition(fails)
    p_train, p_dev, p_test = _partition(passes)

    assignment = {
        "train": sorted(f_train + p_train),
        "dev": sorted(f_dev + p_dev),
        "test": sorted(f_test + p_test),
    }
    # Disjointness is a property of a partition, but assert it so a future
    # edit that breaks it fails loudly rather than leaking silently.
    all_splits = assignment["train"] + assignment["dev"] + assignment["test"]
    assert len(all_splits) == len(set(all_splits)), "splits overlap"

    splits_file = _state.read_json(_state.state_path("splits.json"), default={})
    splits_file[mode] = {
        **assignment,
        "seed": seed,
        "fractions": list(fractions),
        "created_at": _utcnow(),
    }
    _state.write_json(_state.state_path("splits.json"), splits_file)
    return assignment


# ---------------------------------------------------------------------------
# register_judge
# ---------------------------------------------------------------------------


def register_judge(mode: str, prompt_text: str, judge_model: str) -> dict[str, str]:
    """Register a new judge prompt version for ``mode`` and return its id.

    Each edit is a new version: registering re-hashes (prompt, model) and
    appends to the mode's version history. A judge id is
    ``<mode>-v<N>``; the prompt hash fingerprints the exact text and model.

    Args:
        mode: the failure mode this judge scores.
        prompt_text: the full judge prompt (the four-component prompt from
            the lecture).
        judge_model: the judge model id (demo default ``claude-opus-4-6``,
            deliberately a different family from the agent under evaluation).

    Returns:
        ``{"judge_id": ..., "prompt_hash": ..., "version": ...}``.
    """
    history_path = _state.state_path("judges", f"_history_{mode}.json")
    history = _state.read_json(history_path, default={"versions": []})
    version = len(history["versions"])
    judge_id = f"{mode}-v{version}"
    prompt_hash = _prompt_hash(prompt_text, judge_model)

    judge = {
        "judge_id": judge_id,
        "mode": mode,
        "version": version,
        "prompt_text": prompt_text,
        "prompt_hash": prompt_hash,
        "model": judge_model,
        "status": "draft",
        "created_at": _utcnow(),
        "iterations": [],
        "predictions": {},
    }
    _state.write_json(_judge_path(judge_id), judge)
    history["versions"].append({"judge_id": judge_id, "prompt_hash": prompt_hash})
    _state.write_json(history_path, history)
    return {"judge_id": judge_id, "prompt_hash": prompt_hash, "version": version}


# ---------------------------------------------------------------------------
# run_judge
# ---------------------------------------------------------------------------


def run_judge(
    judge_id: str,
    split: str | None = None,
    trace_ids: list[str] | None = None,
    *,
    classify=None,
) -> dict[str, int]:
    """Run a judge and return per-trace binary predictions, cached.

    Predictions are cached by (prompt hash, trace id), so reruns are free and
    a rerun after an edit only classifies the changed version. Over the full
    store this dispatches through the scaling backend
    (:func:`analysis.helpers.scale.classify_store`), which uses the opt-in
    DocETL map operation for every live batch. For tests, pass a ``classify``
    callable so no live model is ever called.

    Args:
        judge_id: the judge to run.
        split: ``"train"``/``"dev"``/``"test"`` to score that split, or
            ``"store"`` to score the full unlabeled store slice.
        trace_ids: an explicit id list, as an alternative to ``split``.
        classify: optional ``fn(prompt, [traces]) -> {trace_id: 0|1}`` used
            in place of the live/DocETL backend (tests supply a stub).

    Returns:
        ``{trace_id: 0|1}`` for the scored traces. Also updates the judge's
        prediction cache on disk.
    """
    judge = _load_judge(judge_id)
    mode = judge["mode"]

    store_traces: list[dict[str, Any]] = []
    if split == "store":
        store_traces = scale.load_store_traces()
        ids = [r["trace_id"] for r in store_traces]
    elif split in ("train", "dev", "test"):
        splits = _state.read_json(_state.state_path("splits.json"), default={})
        ids = splits.get(mode, {}).get(split, [])
    elif trace_ids is not None:
        ids = list(trace_ids)
    else:
        raise ValueError("pass split ('train'/'dev'/'test'/'store') or trace_ids")

    cache = judge.setdefault("predictions", {}).setdefault(judge["prompt_hash"], {})
    to_classify = [tid for tid in ids if tid not in cache]

    if to_classify:
        if classify is not None:
            fresh = classify(judge["prompt_text"], to_classify)
        else:  # live/DocETL path; never reached in tests
            fresh = scale.classify_store(
                judge["prompt_text"], judge["model"], to_classify
            )
        for tid, pred in fresh.items():
            cache[str(tid)] = int(pred)
        _state.write_json(_judge_path(judge_id), judge)

    if split == "store":
        traces_by_id = {str(row["trace_id"]): row for row in store_traces}
        judge["store_predictions"] = {
            "predictions": [
                {
                    "trace_id": str(tid),
                    "pred": int(cache[str(tid)]),
                    "segments": dict(traces_by_id[str(tid)].get("segments", {})),
                }
                for tid in ids
                if str(tid) in cache
            ],
            "created_at": _utcnow(),
        }
        _state.write_json(_judge_path(judge_id), judge)

    return {tid: int(cache[tid]) for tid in ids if tid in cache}


# ---------------------------------------------------------------------------
# judge_alignment
# ---------------------------------------------------------------------------


def judge_alignment(judge_id: str, split: str) -> dict[str, Any]:
    """Score a judge against the human labels on a split.

    Computes TPR, TNR, overall agreement, the confusion counts, and the
    disagreement trace ids with Pass as the positive class and Fail as the
    negative class. Stored mode labels remain failure indicators, so the
    helper converts them before computing the statistics. Running on ``dev`` auto-appends a row to the
    iteration log (version, dev TPR/TNR). Running on ``test`` raises unless
    the judge is frozen: the test split is unavailable until you freeze
    (the guard). ``run_judge`` must have produced predictions for the split
    first.

    Args:
        judge_id: the judge to score.
        split: ``"dev"`` while iterating, or ``"test"`` only once frozen.

    Returns:
        ``{"tpr", "tnr", "tpr_interval", "tnr_interval", "agreement",
        "tp", "fn", "tn", "fp", "disagreements": [...], "n"}``.
    """
    judge = _load_judge(judge_id)
    guards.require_frozen_for_test(judge, split)

    mode = judge["mode"]
    splits = _state.read_json(_state.state_path("splits.json"), default={})
    ids = splits.get(mode, {}).get(split, [])
    if not ids:
        raise ValueError(f"no '{split}' split for mode '{mode}'; run split_labels.")

    labels_by_trace = {r["trace_id"]: r["label"] for r in _load_labels(mode)}
    preds = _cached_preds(judge)
    missing = [tid for tid in ids if tid not in preds]
    if missing:
        raise ValueError(
            f"judge '{judge_id}' has no predictions for {len(missing)} "
            f"'{split}' traces; run run_judge(judge_id, split='{split}') first."
        )

    tp = fn = tn = fp = 0
    disagreements: list[str] = []
    for tid in ids:
        if tid not in labels_by_trace:
            continue
        # Mode files store 1 when the named failure is present. Evaluation
        # statistics use 1 for Pass and 0 for Fail throughout Module 2.
        label = 1 - int(labels_by_trace[tid])
        pred = 1 - int(preds[tid])
        if label == 1 and pred == 1:
            tp += 1
        elif label == 1 and pred == 0:
            fn += 1
            disagreements.append(tid)
        elif label == 0 and pred == 0:
            tn += 1
        else:
            fp += 1
            disagreements.append(tid)

    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    total = tp + fn + tn + fp
    agreement = (tp + tn) / total if total else 0.0

    result = {
        "judge_id": judge_id,
        "split": split,
        "tpr": round(tpr, 4),
        "tnr": round(tnr, 4),
        "tpr_interval": _wilson_interval(tp, tp + fn),
        "tnr_interval": _wilson_interval(tn, tn + fp),
        "agreement": round(agreement, 4),
        "tp": tp,
        "fn": fn,
        "tn": tn,
        "fp": fp,
        "n": total,
        "disagreements": disagreements,
    }

    # Running on dev during refinement logs a hill-climbing row. A frozen
    # version is done iterating, so it is not re-logged (that would duplicate
    # the row already recorded when the version was tuned).
    if split == "dev" and not guards.is_frozen(judge):
        _append_iteration_row(judge, tpr, tnr)

    return result


def _append_iteration_row(
    judge: dict[str, Any], tpr: float, tnr: float, change_note: str = "", label_flips: int = 0
) -> None:
    row = {
        "version": judge["version"],
        "change_note": change_note,
        "dev_tpr": round(tpr, 4),
        "dev_tnr": round(tnr, 4),
        "label_flips": label_flips,
        "ts": _utcnow(),
    }
    judge.setdefault("iterations", []).append(row)
    _state.write_json(_judge_path(judge["judge_id"]), judge)


# ---------------------------------------------------------------------------
# iteration_log
# ---------------------------------------------------------------------------


def iteration_log(judge_or_mode: str) -> list[dict[str, Any]]:
    """Return the hill-climbing table for a judge or a whole mode.

    Each row is one iteration: version, change note, dev TPR, dev TNR, and
    label flips (Artifact L / Artifact F). Passing a mode name concatenates
    the logs of all that mode's versions in version order, which is the
    homework artifact.

    Args:
        judge_or_mode: a ``<mode>-v<N>`` judge id, or a bare mode name.

    Returns:
        A list of iteration-row dicts.
    """
    judge_path = _judge_path(judge_or_mode)
    if judge_path.exists():
        return _load_judge(judge_or_mode).get("iterations", [])

    # Treat it as a mode: gather every version's rows in version order.
    history = _state.read_json(
        _state.state_path("judges", f"_history_{judge_or_mode}.json"),
        default={"versions": []},
    )
    rows: list[dict[str, Any]] = []
    for entry in history["versions"]:
        judge = _load_judge(entry["judge_id"])
        rows.extend(judge.get("iterations", []))
    return rows


# ---------------------------------------------------------------------------
# freeze_judge
# ---------------------------------------------------------------------------


def freeze_judge(judge_id: str) -> dict[str, Any]:
    """Freeze a judge version: lock its prompt and unlock the test split.

    Freezing is one-way per version (the guard): fixing a frozen judge means
    registering a new version, which re-locks test. After freezing,
    ``judge_alignment(judge_id, "test")`` and ``corrected_prevalence`` become
    available, and no further dev iterations are accepted on this version.

    Args:
        judge_id: the judge version to freeze.

    Returns:
        The updated judge record (with ``status == "frozen"`` and a
        ``frozen_at`` timestamp).
    """
    judge = _load_judge(judge_id)
    guards.check_freeze_allowed(judge)
    judge["status"] = "frozen"
    judge["frozen_at"] = _utcnow()
    _state.write_json(_judge_path(judge_id), judge)
    return judge
