"""Homework 5 judge pipeline for ``irrelevant_policy_detail``.

Parts B through D: prepare the judge inputs, split the labels, run the judge on the
development split, then freeze and test.

    .venv/bin/python analysis/run_judges.py prepare
    .venv/bin/python analysis/run_judges.py split
    .venv/bin/python analysis/run_judges.py dev  analysis/prompts/<mode>-v0.txt
    .venv/bin/python analysis/run_judges.py test <judge_id>

The judge model is ``openai/rl-muse-spark-1-1-playground``. The handout specifies
``gpt-4o-mini``, which this endpoint does not serve; see
``analysis/report/workshop_notes.md``. The model was chosen deliberately rather than by
default: the agent under test ran on ``rl-muse-spark-1-3-sglang-playground``, and a judge
that shares the model it grades is least likely to notice the mistakes that model makes.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from analysis.helpers import (freeze_judge, judge_alignment, register_judge,
                              run_judge, split_labels)
from analysis.tools.muse_classify import make_classifier
from observability.instrument import load_env

# The DocETL backend switches on only when a model key is in the environment, and the
# key lives in .env. Without this the judge raises "no scaling backend configured",
# which reads like a missing dependency rather than an unloaded file.
load_env()

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "analysis" / "state"
MODE = "irrelevant_policy_detail"
JUDGE_MODEL = "openai/rl-muse-spark-1-1-playground"

LABELS = STATE / "hw5_labels" / f"{MODE}.jsonl"
SOURCE = STATE / "hw5_trace_source.json"
INPUTS = STATE / "hw5_trace_inputs.json"

# .env carries LANGFUSE_* keys from the Homework 2 template, so loading it makes the
# helpers believe Langfuse is available and try to fetch traces from a server that never
# ran. The handout's answer is this variable: it pins the judge to the saved export even
# when Langfuse looks configured. Set here rather than left to the shell so a forgotten
# export cannot silently send the judge somewhere else.
os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(INPUTS)


def _labels() -> dict[str, int]:
    return {json.loads(l)["trace_id"]: json.loads(l)["label"]
            for l in LABELS.read_text().splitlines() if l.strip()}


def prepare_inputs() -> None:
    """Write one judge input per labelled conversation.

    The verdict cannot be reached from the reply alone. Deciding whether a cited rule
    governs needs the store's window override, the order total against the $100
    threshold, the restocking opt-in, and whether a refund actually ran -- all of which
    live in the tool results. The shared trace normaliser returns early when
    conversation turns are present and drops tool calls entirely, so the evidence is
    assembled here instead.

    Human labels, review notes and the scenario's expected outcome are excluded. Any of
    them would hand the judge the answer.
    """
    labels = _labels()
    traces = json.loads(SOURCE.read_text())
    out, missing = [], []

    for t in traces:
        tid = t.get("id")
        if tid not in labels:
            continue
        messages = []
        for turn in t.get("turns") or t.get("conversation") or []:
            if turn.get("user"):
                messages.append({"role": "user", "text": turn["user"]})
            if turn.get("agent"):
                messages.append({"role": "assistant", "text": turn["agent"]})
        for obs in t.get("observations") or []:
            if obs.get("type") != "TOOL" or not obs.get("tool_name"):
                continue
            messages.append({
                "role": "tool_call",
                "name": obs["tool_name"],
                "arguments": obs.get("tool_arguments"),
            })
            messages.append({
                "role": "tool_result",
                "name": obs["tool_name"],
                "text": obs.get("tool_result"),
            })
        if not any(m["role"] == "assistant" for m in messages):
            missing.append(tid)
            continue
        out.append({"trace_id": tid, "trace": messages})

    INPUTS.write_text(json.dumps(out, indent=1) + "\n")
    tools = sum(1 for r in out for m in r["trace"] if m["role"] == "tool_call")
    print(f"{len(out)} judge inputs -> {INPUTS}")
    print(f"  labelled conversations: {len(labels)}")
    print(f"  tool calls carried:     {tools} "
          f"({tools / len(out):.1f} per conversation)")
    if missing:
        print(f"  dropped, no assistant reply: {len(missing)}")
    leaked = [k for r in out for m in r["trace"] for k in m
              if k in ("label", "expected", "note", "annotation", "outcome")]
    print(f"  leakage check (label/expected/note fields present): {len(leaked)}")


def split_data(mode: str = MODE) -> dict:
    """Split the labels, with the class-count guard lowered deliberately.

    The handout's ``min_per_class=10`` refuses to split this mode at all: there are 12
    Fail labels in total. Lowering the guard to 4 is a documented override, not a
    workaround -- see the stop-early section of analysis/report/hw5-labelling-outcome.md.
    """
    records = json.loads(INPUTS.read_text())
    labels = _labels()
    splits = split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=4,
        eligible_trace_ids=[r["trace_id"] for r in records],
    )
    print(f"splits for {mode}:")
    for name in ("train", "dev", "test"):
        ids = splits.get(name, [])
        fails = sum(1 for i in ids if labels.get(i) == 0)
        print(f"  {name:6} {len(ids):>3} traces   {fails:>2} Fail / {len(ids) - fails:>3} Pass")
    return splits


def run_development(mode: str, prompt_path: str) -> dict:
    record = register_judge(mode=mode, prompt_text=Path(prompt_path).read_text(),
                            judge_model=JUDGE_MODEL)
    judge_id = record["judge_id"]
    print(f"judge {judge_id}  model {JUDGE_MODEL}  prompt {prompt_path}")
    run_judge(judge_id, split="dev", batch_size=10,
              classify=make_classifier(JUDGE_MODEL))
    metrics = judge_alignment(judge_id, split="dev")
    out = REPO / "analysis" / "report" / f"dev-{judge_id}.json"
    out.write_text(json.dumps(metrics, indent=1) + "\n")
    print(f"metrics -> {out}")
    print(json.dumps(metrics, indent=1)[:600])
    return {"judge_id": judge_id, "metrics": metrics}


def run_test(judge_id: str) -> dict:
    """Freeze the prompt, then score the held-out split.

    Freezing is one-way and locks the prompt; the test split stays unavailable until it
    happens. No test prediction has been looked at before this point, which is the whole
    reason the split exists.
    """
    record = freeze_judge(judge_id)
    print(f"frozen: {judge_id}  at {record.get('frozen_at')}")
    run_judge(judge_id, split="test", batch_size=10,
              classify=make_classifier(JUDGE_MODEL))
    metrics = judge_alignment(judge_id, split="test")
    out = REPO / "analysis" / "report" / f"test-{judge_id}.json"
    out.write_text(json.dumps(metrics, indent=1) + "\n")
    print(f"metrics -> {out}")
    print(json.dumps(metrics, indent=1)[:600])
    return metrics


def recalc(judge_id: str | None = None) -> None:
    """Recompute both splits from the saved predictions. No model is called.

    The handout asks for the test metrics to be recalculated live on camera. Everything
    here reads the cached predictions and the human labels on disk, so it is instant and
    reproducible, and it demonstrates that the reported numbers are not hand-copied.
    """
    if judge_id is None:
        judges = sorted((STATE / "judges").glob(f"{MODE}-v*.json"),
                        key=lambda f: int(f.stem.rsplit("-v", 1)[1]))
        frozen = [f.stem for f in judges
                  if json.loads(f.read_text()).get("status") == "frozen"]
        judge_id = frozen[-1] if frozen else judges[-1].stem
    rec = json.loads((STATE / "judges" / f"{judge_id}.json").read_text())
    cached = sum(len(v) for v in rec.get("predictions", {}).values())
    print(f"judge {judge_id}   status {rec['status']}   model {rec['model']}")
    print(f"prompt hash {rec['prompt_hash']}   {cached} cached predictions, no model call\n")
    print(f"{'':8}{'TPR':>8}{'95% CI':>20}{'TNR':>8}{'95% CI':>20}{'n':>5}")
    for split in ("dev", "test"):
        try:
            m = judge_alignment(judge_id, split=split)
        except Exception as e:                      # test is locked until frozen
            print(f"  {split:6} unavailable: {type(e).__name__}")
            continue
        ci = lambda k: f"[{m[k][0]:.2f}, {m[k][1]:.2f}]"
        print(f"  {split:6}{m['tpr']:>8.2f}{ci('tpr_interval'):>20}"
              f"{m['tnr']:>8.2f}{ci('tnr_interval'):>20}{m['n']:>5}")
        print(f"          agreement {m['agreement']:.2f}   "
              f"caught {m['tn']} of {m['tn'] + m['fp']} real failures, "
              f"{m['fn']} false alarms")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if cmd == "prepare":
        prepare_inputs()
    elif cmd == "split":
        split_data()
    elif cmd == "dev":
        # Default to the latest prompt version so the command stays short enough to
        # paste on one line; a long path wrapped in the terminal and the shell split it.
        prompts = sorted((REPO / "analysis" / "prompts").glob(f"{MODE}-v*.txt"))
        path = sys.argv[2] if len(sys.argv) > 2 else str(prompts[-1])
        print(f"prompt: {path}")
        run_development(MODE, path)
    elif cmd == "test":
        # Default to the judge with predictions, so the command stays short enough to
        # paste on one line. A wrapped argument was silently split by the shell earlier.
        if len(sys.argv) > 2:
            run_test(sys.argv[2])
        else:
            judges = sorted((STATE / "judges").glob(f"{MODE}-v*.json"),
                            key=lambda f: int(f.stem.rsplit("-v", 1)[1]))
            withpreds = [f for f in judges
                         if sum(len(v) for v in
                                json.loads(f.read_text()).get("predictions", {}).values())]
            if not withpreds:
                raise SystemExit("no judge has predictions; run dev first")
            jid = withpreds[-1].stem
            print(f"judge: {jid}")
            run_test(jid)
    elif cmd == "recalc":
        recalc(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        raise SystemExit(
            "commands: prepare | split | dev [prompt] | test [judge_id] | recalc [judge_id]")
