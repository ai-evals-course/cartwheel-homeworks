"""HW5: build and evaluate an LLM judge for one HW4/HW5 failure mode.

Mode: mishandles_vague_requests (merged from HW4's no_clarifying_question +
asks_for_unusable_information, broadened during HW5 label collection to also
cover redundant speculative searching and unsupported "maybe it exists"
assertions in response to a vague request).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from observability.instrument import load_env

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path("analysis/state")
MODE = "mishandles_vague_requests"


def _judge_model() -> str:
    """The judge model, overridable via CARTWHEEL_JUDGE_MODEL for
    experimentation. The handout's baseline (dev and test must match) is
    gpt-4o-mini -- change the env var, not this default, to try another."""
    load_env()
    return os.environ.get("CARTWHEEL_JUDGE_MODEL", "gpt-4o-mini")

# Records that share this key test the same underlying record with only the
# customer's phrasing varied -- true duplicates for judge-input purposes, not
# independent conversations. Everything else keeps its own trace_id as its
# key (different customers/orders/products, even when thematically similar).
_DUPLICATE_CATEGORY_TAGS = {"duplicate_title", "duplicate_title_action"}


def _dq_case_lookup() -> dict[str, str]:
    """scenario_id -> data_quality_case_id, for the HW3-era 5-variant groups."""
    lookup: dict[str, str] = {}
    with open(STATE_DIR / "scenario_lookup.json") as f:
        raw = json.load(f)
    for scenario_id, entry in raw.items():
        case_id = entry.get("data_quality_case_id")
        if case_id:
            lookup[scenario_id] = case_id
    return lookup


def _dedupe_key(sample: dict, dq_lookup: dict[str, str]) -> str:
    scenario_id = sample.get("meta", {}).get("scenario_id", "")
    if scenario_id in dq_lookup:
        return f"dq:{dq_lookup[scenario_id]}"
    flags = sample.get("flags", [])
    for tag in _DUPLICATE_CATEGORY_TAGS:
        if tag in flags:
            return f"cat:{tag}"
    return f"trace:{sample['trace_id']}"


def prepare_inputs() -> list[dict]:
    """Export one judge-input record per distinct conversation.

    Reads every reviewed HW4/HW5 trace, drops excluded (invalid-scenario)
    traces, keeps one representative per duplicate-record group, and writes
    plain conversation content only -- no labels, annotations, or scenario
    metadata that would leak the answer to the judge.

    Saves to analysis/state/hw5_trace_inputs.json.
    """
    with open(STATE_DIR / "samples.json") as f:
        samples = json.load(f)
    with open(STATE_DIR / "annotations.json") as f:
        anns = json.load(f)

    excluded = {a["trace_id"] for a in anns if a.get("note") == "excluded"}
    dq_lookup = _dq_case_lookup()

    groups: dict[str, dict] = {}
    for s in samples:
        if s["trace_id"] in excluded:
            continue
        key = _dedupe_key(s, dq_lookup)
        # Deterministic representative: first by trace_id per group, so
        # reruns of this function are stable.
        if key not in groups or s["trace_id"] < groups[key]["trace_id"]:
            groups[key] = s

    records = []
    for s in sorted(groups.values(), key=lambda s: s["trace_id"]):
        records.append({"trace_id": s["trace_id"], "trace": s["trace"]})

    out_path = STATE_DIR / "hw5_trace_inputs.json"
    with out_path.open("w") as f:
        json.dump(records, f, indent=2)

    print(f"prepare_inputs: {len(samples)} reviewed traces -> {len(records)} deduplicated records")
    return records


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Split human judgments for `mode` into disjoint train/dev/test.

    20% train / 40% dev / 40% test, stratified by label, seed=7. Restricted
    to trace_ids that survived prepare_inputs()'s dedup (eligible_trace_ids).
    """
    from analysis.helpers import split_labels

    records = json.loads((STATE_DIR / "hw5_trace_inputs.json").read_text())
    splits = split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )
    for split_name, ids in splits.items():
        print(f"{split_name}: {len(ids)} traces")
    return splits


def run_development(mode: str = MODE, prompt_path: str | Path = "analysis/prompts/mishandles_vague_requests-v0.txt") -> dict:
    """Register a judge version, run it on the dev split, and score alignment.

    Uses CARTWHEEL_JUDGE_MODEL (default gpt-4o-mini, the handout's baseline)
    for both this call and run_test() later -- keep the env var unchanged
    between the two so dev and test use the same model.
    """
    os.environ.setdefault(
        "CARTWHEEL_JUDGE_TRACE_SOURCE", str(REPO_ROOT / "analysis/state/hw5_trace_inputs.json")
    )
    from analysis.helpers import register_judge, run_judge, judge_alignment

    prompt_path = Path(prompt_path)
    record = register_judge(
        mode=mode,
        prompt_text=prompt_path.read_text(),
        judge_model=_judge_model(),
    )
    judge_id = record["judge_id"]
    print(f"registered {judge_id} (model={_judge_model()})")
    run_judge(judge_id, split="dev", batch_size=10)
    development = judge_alignment(judge_id, split="dev")

    report_path = Path("analysis/report") / f"dev-{judge_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(development, indent=2))
    print(f"dev TPR={development['tpr']:.2f} {development['tpr_interval']}  "
          f"TNR={development['tnr']:.2f} {development['tnr_interval']}  "
          f"(tp={development['tp']} fn={development['fn']} tn={development['tn']} fp={development['fp']})")
    return {"judge_id": judge_id, **development}


def run_test(judge_id: str) -> dict:
    """Freeze the prompt version and evaluate the held-out test split once."""
    _judge_model()  # loads .env so OPENAI_API_KEY is set in this process
    os.environ.setdefault(
        "CARTWHEEL_JUDGE_TRACE_SOURCE", str(REPO_ROOT / "analysis/state/hw5_trace_inputs.json")
    )
    from analysis.helpers import freeze_judge, run_judge, judge_alignment

    freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=10)
    test = judge_alignment(judge_id, split="test")

    report_path = Path("analysis/report") / f"test-{judge_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(test, indent=2))
    print(f"test TPR={test['tpr']:.2f} {test['tpr_interval']}  "
          f"TNR={test['tnr']:.2f} {test['tnr_interval']}  "
          f"(tp={test['tp']} fn={test['fn']} tn={test['tn']} fp={test['fp']})")
    return {"judge_id": judge_id, **test}


if __name__ == "__main__":
    prepare_inputs()
    split_data()
