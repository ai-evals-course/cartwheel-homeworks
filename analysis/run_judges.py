"""HW5 judge pipeline: exports, splits, and DocETL judge runs.

Run from the repository root, for example::

    uv run python analysis/run_judges.py export-labels excessive_policy_exposition
    uv run python analysis/run_judges.py prepare-inputs excessive_policy_exposition
    uv run python analysis/run_judges.py split excessive_policy_exposition
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.helpers import (
    freeze_judge,
    judge_alignment,
    register_judge,
    run_judge,
    split_labels,
)

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "analysis" / "state"
HW4_LABELS = STATE / "labels"
HW5_LABELS = STATE / "hw5_labels"
SAMPLES = STATE / "samples.json"
TRACE_INPUTS = STATE / "hw5_trace_inputs.json"
REPORT = ROOT / "analysis" / "report"


def _latest_hw4_labels(mode: str) -> dict[str, dict]:
    """Collapse append-only HW4 labels to the live label per trace."""
    path = HW4_LABELS / f"{mode}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing HW4 labels at {path}")
    live: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("superseded_by"):
            continue
        if row.get("label") not in (0, 1):
            raise ValueError(f"label must be 0 or 1 in {path}")
        live[row["trace_id"]] = row
    return live


def export_hw5_labels(mode: str) -> Path:
    """Copy HW4 labels into HW5 convention (1=Pass, 0=Fail).

    HW4 structured labeling uses 1 when the failure is present and 0 when
    absent. HW5 flips that so Pass is 1 throughout judge evaluation.
    """
    HW5_LABELS.mkdir(parents=True, exist_ok=True)
    out = HW5_LABELS / f"{mode}.jsonl"
    live = _latest_hw4_labels(mode)
    rows = []
    for trace_id in sorted(live):
        hw4 = live[trace_id]
        rows.append(
            {
                "trace_id": trace_id,
                "label": 1 - int(hw4["label"]),
                "source": "human",
                "note": hw4.get("note"),
            }
        )
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return out


def prepare_inputs(mode: str) -> Path:
    """Save judge-facing trace records for every labeled conversation.

    Includes only ``trace_id`` and the conversation ``trace`` (roles, user
    text, tool calls, tool results, assistant replies). Review metadata,
    open codes, and human labels stay out so the judge cannot leak on them.
    """
    labels = _latest_hw4_labels(mode)
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    by_id = {row["trace_id"]: row for row in samples}

    missing = sorted(set(labels) - set(by_id))
    if missing:
        raise ValueError(f"labeled traces missing from samples.json: {missing[:5]}")

    records = []
    for trace_id in sorted(labels):
        sample = by_id[trace_id]
        trace = sample.get("trace")
        if not isinstance(trace, list) or not trace:
            raise ValueError(f"trace {trace_id} has no message list in samples.json")
        records.append({"trace_id": trace_id, "trace": trace})

    TRACE_INPUTS.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return TRACE_INPUTS


def split_data(mode: str, *, seed: int = 7) -> dict[str, list[str]]:
    """Stratified train/dev/test split via ``split_labels`` (run once)."""
    if not TRACE_INPUTS.exists():
        raise FileNotFoundError(f"missing {TRACE_INPUTS}; run prepare-inputs first")
    records = json.loads(TRACE_INPUTS.read_text(encoding="utf-8"))
    return split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=seed,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )


def _split_class_counts(mode: str, assignment: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    """Report Pass/Fail counts per split using HW5 labels (1=Pass)."""
    hw5_path = HW5_LABELS / f"{mode}.jsonl"
    labels = {
        json.loads(line)["trace_id"]: json.loads(line)["label"]
        for line in hw5_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    out: dict[str, dict[str, int]] = {}
    for split_name, trace_ids in assignment.items():
        if split_name not in {"train", "dev", "test"}:
            continue
        pass_n = sum(1 for tid in trace_ids if labels.get(tid) == 1)
        fail_n = sum(1 for tid in trace_ids if labels.get(tid) == 0)
        out[split_name] = {"pass": pass_n, "fail": fail_n, "total": len(trace_ids)}
    return out


def run_development(mode: str, prompt_path: Path, *, judge_model: str = "gpt-4o-mini") -> dict:
    """Register a prompt, score the dev split, and save metrics."""
    record = register_judge(
        mode=mode,
        prompt_text=prompt_path.read_text(encoding="utf-8"),
        judge_model=judge_model,
    )
    judge_id = record["judge_id"]
    run_judge(judge_id, split="dev", batch_size=10)
    development = judge_alignment(judge_id, split="dev")
    REPORT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT / f"dev-{judge_id}.json"
    report_path.write_text(json.dumps(development, indent=2), encoding="utf-8")
    return {"judge_id": judge_id, "metrics": development, "report_path": str(report_path)}


def run_test(judge_id: str, *, batch_size: int = 10) -> dict:
    """Freeze the chosen judge, score test once, and save metrics."""
    from analysis.helpers import guards
    from analysis.helpers.tools import _load_judge

    if not guards.is_frozen(_load_judge(judge_id)):
        freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=batch_size)
    test = judge_alignment(judge_id, split="test")
    REPORT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT / f"test-{judge_id}.json"
    report_path.write_text(json.dumps(test, indent=2), encoding="utf-8")
    return {"judge_id": judge_id, "metrics": test, "report_path": str(report_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="HW5 judge pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export-labels", help="HW4 labels -> hw5_labels (1=Pass)")
    p_export.add_argument("mode")

    p_prep = sub.add_parser("prepare-inputs", help="build hw5_trace_inputs.json")
    p_prep.add_argument("mode")

    p_split = sub.add_parser("split", help="train/dev/test split (run once)")
    p_split.add_argument("mode")
    p_split.add_argument("--seed", type=int, default=7)

    p_dev = sub.add_parser("run-dev", help="register prompt and score dev split")
    p_dev.add_argument("mode")
    p_dev.add_argument("prompt_path", type=Path)
    p_dev.add_argument("--model", default="gpt-4o-mini")

    p_test = sub.add_parser("run-test", help="freeze judge and score test split")
    p_test.add_argument("judge_id")

    args = parser.parse_args()

    if args.command == "export-labels":
        path = export_hw5_labels(args.mode)
        print(f"wrote {path}")
    elif args.command == "prepare-inputs":
        path = prepare_inputs(args.mode)
        print(f"wrote {path} ({len(json.loads(path.read_text()))} records)")
    elif args.command == "split":
        assignment = split_data(args.mode, seed=args.seed)
        counts = _split_class_counts(args.mode, assignment)
        print(json.dumps({"splits": assignment, "class_counts_hw5": counts}, indent=2))
    elif args.command == "run-dev":
        result = run_development(args.mode, args.prompt_path, judge_model=args.model)
        print(json.dumps(result, indent=2))
    elif args.command == "run-test":
        result = run_test(args.judge_id)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
