"""HW5: prepare judge inputs, split labels, and run the verbose_reply judge.

Run from the repository root:

    uv run python -m analysis.run_judges prepare     # write hw5_trace_inputs.json
    uv run python -m analysis.run_judges split       # split labels once (20/40/40, seed 7)
    uv run --env-file .env python -m analysis.run_judges dev analysis/prompts/verbose_reply-v0.txt
    uv run --env-file .env python -m analysis.run_judges resume verbose_reply-v0

The judge reads ``analysis/state/hw5_trace_inputs.json`` through
``CARTWHEEL_JUDGE_TRACE_SOURCE``. The helpers flatten each record's ``trace``
into ``role: content`` lines, so the records are shaped for that text:

- ``user``: the user's message.
- Text the model wrote before a tool call ("I'll look up...") is left out.
  The chat does not show it to the user, and the judge rates only the reply
  the user saw.
- ``tool_call`` / ``tool_result``: ``name`` plus the tool data. The flattened
  text only prints ``arguments`` and ``content``, so the tool name is carried
  inside them as well.
- ``assistant``: the reply the user saw. The last ``assistant`` message is the
  reply under evaluation; earlier ones belong to earlier turns.

Labels, notes, quotes, scenario metadata, and the system prompt stay out of
the input.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from analysis.review_app.server import EXPORT_FILE, build_turn

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "analysis" / "state"
INPUTS_FILE = STATE / "hw5_trace_inputs.json"
REPORT = ROOT / "analysis" / "report"
MODE = "verbose_reply"
JUDGE_MODEL = "gpt-4o-mini"

# Labeled conversations left out of the judge inputs. Their labels stay in
# hw5_labels/; they are only ineligible for the split.
EXCLUDED = {
    "support-0235": "close variant of support-0052 (late refund refusal on an "
                    "ineligible order, same tool sequence); keep 0052 (2026-09-26)",
}


def _hw5_labels(mode: str) -> list[dict[str, Any]]:
    path = STATE / "hw5_labels" / f"{mode}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _eligible_labels(mode: str) -> list[dict[str, Any]]:
    return [r for r in _hw5_labels(mode) if r["scenario_id"] not in EXCLUDED]


def _turn_messages(turn: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "user", "text": turn["user"]}]
    for step in turn["steps"]:
        for call in step["calls"]:
            messages.append({
                "role": "tool_call",
                "name": call["name"],
                "arguments": {"tool": call["name"], "arguments": call["args"]},
            })
            messages.append({
                "role": "tool_result",
                "name": call["name"],
                "content": {"tool": call["name"], "result": call["result"]},
            })
    for orphan in turn["orphan_tools"]:
        messages.append({
            "role": "tool_result",
            "name": orphan["name"],
            "content": {"tool": orphan["name"], "result": orphan["result"]},
        })
    messages.append({"role": "assistant", "text": turn["reply"]})
    return messages


def build_inputs(mode: str = MODE) -> list[dict[str, Any]]:
    """One record per labeled conversation: earlier turns, then the target turn."""
    raw = json.loads(EXPORT_FILE.read_text())["traces"]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for trace in raw:
        sid = trace.get("cartwheel_scenario_id")
        if sid:
            by_scenario.setdefault(sid, []).append(trace)

    records = []
    for label in sorted(_eligible_labels(mode), key=lambda r: r["scenario_id"]):
        group = sorted(by_scenario[label["scenario_id"]], key=lambda t: t.get("timestamp") or "")
        ids = [t["id"] for t in group]
        target = ids.index(label["trace_id"])  # raises if the label points elsewhere
        messages: list[dict[str, Any]] = []
        for index, trace in enumerate(group[: target + 1]):
            messages.extend(_turn_messages(build_turn(trace, index)))
        records.append({"trace_id": label["trace_id"], "trace": messages})
    return records


def check_inputs(records: list[dict[str, Any]], mode: str = MODE) -> dict[str, Any]:
    """One input per label, no duplicates, no label or scenario metadata."""
    from analysis.helpers.normalization import normalize_trace

    label_ids = {r["trace_id"] for r in _eligible_labels(mode)}
    input_ids = [r["trace_id"] for r in records]
    assert len(input_ids) == len(set(input_ids)), "duplicate trace ids in the inputs"
    assert set(input_ids) == label_ids, "inputs and labels do not match one to one"
    allowed = {"role", "text", "name", "arguments", "content"}
    leaked = ("scenario_id", "support-0", "verbose_reply", "cartwheel.", "coverage", "challenge")
    for record in records:
        assert set(record) == {"trace_id", "trace"}
        assert record["trace"][-1]["role"] == "assistant", record["trace_id"]
        for message in record["trace"]:
            assert set(message) <= allowed, (record["trace_id"], set(message) - allowed)
        text = normalize_trace(record)["text"]
        hits = [word for word in leaked if word in text]
        assert not hits, (record["trace_id"], hits)
    return {"records": len(records), "labels": len(label_ids)}


def prepare_inputs(mode: str = MODE, force: bool = False) -> Path:
    """Write ``analysis/state/hw5_trace_inputs.json`` and check it.

    Refuses to change an existing file once a judge is registered for the mode,
    because every prompt version must see the same inputs.
    """
    records = build_inputs(mode)
    check_inputs(records, mode)
    payload = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    judges = list((STATE / "judges").glob(f"{mode}-v*.json"))
    if INPUTS_FILE.exists() and INPUTS_FILE.read_text() != payload and judges and not force:
        raise RuntimeError(
            f"{INPUTS_FILE.name} would change after judges were registered for {mode}; "
            "keep the saved inputs, or pass force=True deliberately."
        )
    INPUTS_FILE.write_text(payload)
    return INPUTS_FILE


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Split the HW5 labels once: 20% train, 40% dev, 40% test, seed 7."""
    from analysis.helpers import split_labels

    splits_file = STATE / "splits.json"
    existing = json.loads(splits_file.read_text()).get(mode) if splits_file.exists() else None
    if existing:
        raise RuntimeError(f"splits.json already has a split for {mode}; keep it unchanged.")
    records = json.loads(INPUTS_FILE.read_text())
    return split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )


def split_counts(mode: str = MODE) -> dict[str, dict[str, int]]:
    """Pass / Fail counts per split, from the HW5 labels (1 = Pass)."""
    splits = json.loads((STATE / "splits.json").read_text())[mode]
    labels = {r["trace_id"]: r["label"] for r in _hw5_labels(mode)}
    return {
        name: {"pass": sum(labels[t] == 1 for t in splits[name]),
               "fail": sum(labels[t] == 0 for t in splits[name])}
        for name in ("train", "dev", "test")
    }


def _use_saved_inputs() -> None:
    """Point the judge helpers at the saved inputs, never Langfuse."""
    source = os.environ.setdefault("CARTWHEEL_JUDGE_TRACE_SOURCE", str(INPUTS_FILE))
    if Path(source).resolve() != INPUTS_FILE.resolve():
        raise RuntimeError(f"CARTWHEEL_JUDGE_TRACE_SOURCE points at {source}, not {INPUTS_FILE}")


def _dev_metrics(judge_id: str) -> dict[str, Any]:
    """Run the judge on the dev split (cached) and save its metrics."""
    from analysis.helpers import judge_alignment, run_judge

    run_judge(judge_id, split="dev", batch_size=10)
    metrics = judge_alignment(judge_id, split="dev")
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f"dev-{judge_id}.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def run_development(mode: str, prompt_path: str | Path) -> dict[str, Any]:
    """Register a prompt version, run it on the dev split, save the metrics."""
    from analysis.helpers import register_judge

    _use_saved_inputs()
    record = register_judge(
        mode=mode,
        prompt_text=Path(prompt_path).read_text(),
        judge_model=JUDGE_MODEL,
    )
    return _dev_metrics(record["judge_id"])


def resume_development(judge_id: str) -> dict[str, Any]:
    """Finish an interrupted dev run without registering a new version."""
    _use_saved_inputs()
    return _dev_metrics(judge_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "split", "counts", "dev", "resume"])
    parser.add_argument("target", nargs="?", help="prompt path (dev) or judge id (resume)")
    args = parser.parse_args()
    if args.command == "prepare":
        path = prepare_inputs()
        print(f"wrote {path.relative_to(ROOT)}: {check_inputs(json.loads(path.read_text()))}")
    elif args.command == "split":
        split_data()
        print(split_counts())
    elif args.command == "dev":
        metrics = run_development(MODE, args.target)
        print(json.dumps({k: v for k, v in metrics.items() if k != "disagreements"}, indent=2))
    elif args.command == "resume":
        metrics = resume_development(args.target)
        print(json.dumps({k: v for k, v in metrics.items() if k != "disagreements"}, indent=2))
    else:
        print(split_counts())


if __name__ == "__main__":
    main()
