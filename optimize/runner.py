"""Run a Homework 9 development or test evaluation."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from observability.instrument import load_env
from replay.__main__ import make_runner
from replay.harness import replay_case
from replay.rollout import WRITE_TOOLS, load_cases, load_frozen_judge, world_reset
from agent.agent import prompt_version

from optimize.workflow import (
    CASES_PATH,
    RESULTS_DIR,
    SPLIT_PATH,
    current_commit,
    now_utc,
    read_json,
    reserve_search_calls,
    validate_split,
    validate_model_selection,
    write_json,
)

DEFAULT_CONFIG = Path(__file__).with_name("config.json")


def is_expected_write(case: dict[str, Any]) -> bool:
    return any(
        check["check"] == "refund_status"
        or (check["check"] == "tool_called" and check.get("name") in WRITE_TOOLS)
        for check in case["expected"].get("checks", [])
    )


def runs_for_case(case: dict[str, Any]) -> int:
    return 5 if is_expected_write(case) else 1


def required_judge_keys(cases: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    modes = {
        mode for case in cases for mode in case["expected"].get("judges", {})
    }
    for mode in modes:
        model = load_frozen_judge(mode)["model"]
        if model.startswith("claude"):
            keys.add("ANTHROPIC_API_KEY")
        elif model.startswith("gpt") or model.startswith("openai/"):
            keys.add("OPENAI_API_KEY")
    return keys


def model_provider_key(model: str) -> str | None:
    if model.startswith("gpt") or model.startswith("openai/"):
        return "OPENAI_API_KEY"
    if model.startswith("claude") or model.startswith("anthropic/"):
        return "ANTHROPIC_API_KEY"
    if model.startswith("glm") or model.startswith("together_ai/") or model.startswith("zai-org/"):
        return "TOGETHER_API_KEY"
    return None


def read_prices(path: Path, model: str) -> tuple[str, float, float]:
    config = read_json(path)
    date = config.get("price_date")
    prices = config.get("prices_per_million_tokens_usd", {}).get(model)
    if not date or str(date).startswith("REPLACE") or not prices:
        raise ValueError(f"add a price date and {model} prices to {path}")
    if prices.get("input") is None or prices.get("output") is None:
        raise ValueError(f"add both input and output prices for {model} to {path}")
    return str(date), float(prices["input"]), float(prices["output"])


def default_output(split_name: str, candidate: str, model: str) -> Path:
    safe = "-".join(part for part in (candidate, model) if part).replace("/", "_")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return RESULTS_DIR / f"{split_name}-{safe}-{stamp}.json"


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    load_env()
    split = read_json(args.split_file)
    validate_split(split, args.cases_file)
    cases_by_id = {case["id"]: case for case in load_cases(args.cases_file)}
    ids = split[f"{args.split}_case_ids"]
    cases = [cases_by_id[case_id] for case_id in ids]
    missing_keys = sorted(key for key in required_judge_keys(cases) if not os.getenv(key))
    if missing_keys:
        raise ValueError(
            "the Homework 5 judges need " + ", ".join(missing_keys) + " for this run"
        )

    planned_runs = sum(runs_for_case(case) for case in cases)
    if args.search:
        reserve_search_calls(planned_runs, args.candidate)

    price_date, input_price, output_price = read_prices(args.config, args.model)
    prompt_template = args.prompt_file.read_text() if args.prompt_file else None
    prompt_hash = prompt_version(prompt_template)
    world_temp = tempfile.TemporaryDirectory(prefix="hw9-eval-")
    world_root = Path(world_temp.name)
    records: list[dict[str, Any]] = []
    total_input = 0
    total_output = 0

    for case in cases:
        reset = world_reset(world_root)
        runner = make_runner(case, world_root, args.model, prompt_template)
        case_records = []
        latencies = []
        for _ in range(runs_for_case(case)):
            started = time.perf_counter()
            record = replay_case(runner, reset, n=1)[0]
            elapsed = time.perf_counter() - started
            latencies.append(float(record.get("agent_latency_seconds", elapsed)))
            case_records.append(record)
            usage = record.get("usage", {})
            total_input += int(usage.get("input_tokens", 0))
            total_output += int(usage.get("output_tokens", 0))
        passes = sum(bool(record["passed"]) for record in case_records)
        records.append(
            {
                "case_id": case["id"],
                "expected_write": is_expected_write(case),
                "runs": len(case_records),
                "passes": passes,
                "pass_rate": passes / len(case_records),
                "failure_modes": sorted(
                    {
                        failure
                        for record in case_records
                        for failure in record.get("failure_modes", [])
                    }
                ),
                "latencies_seconds": [round(value, 4) for value in latencies],
            }
        )

    score = statistics.mean(record["pass_rate"] for record in records)
    write_records = [record for record in records if record["expected_write"]]
    write_pass_5 = (
        statistics.mean(record["passes"] == 5 for record in write_records)
        if write_records
        else None
    )
    all_latencies = [value for record in records for value in record["latencies_seconds"]]
    total_cost = (total_input * input_price + total_output * output_price) / 1_000_000
    result = {
        "schema_version": 1,
        "created_at": now_utc(),
        "split": args.split,
        "candidate": args.candidate,
        "git_commit": current_commit(Path.cwd()),
        "model": args.model,
        "prompt_sha256_12": prompt_hash,
        "test_plan_sha256": args.test_plan_hash,
        "case_count": len(cases),
        "evaluated_case_runs": planned_runs,
        "score": round(score, 6),
        "write_pass_5": None if write_pass_5 is None else round(write_pass_5, 6),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "price_date": price_date,
        "cost_usd": round(total_cost, 6),
        "cost_per_100_conversations_usd": round(total_cost / planned_runs * 100, 6),
        "median_latency_seconds": round(statistics.median(all_latencies), 4),
        "cases": records,
    }
    world_temp.cleanup()
    write_json(args.output, result)
    if args.split == "development":
        write_json(RESULTS_DIR / "latest-development.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("development", "test"), required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--model", default=os.getenv("CARTWHEEL_MODEL"))
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--cases-file", type=Path, default=CASES_PATH)
    parser.add_argument("--split-file", type=Path, default=SPLIT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--test-plan-hash")
    args = parser.parse_args()
    config = read_json(args.config)
    validate_model_selection(config)
    if not args.model:
        args.model = config["models"]["development_and_search"]
    args.output = args.output or default_output(args.split, args.candidate, args.model)
    return args


def main() -> None:
    args = parse_args()
    result = run_evaluation(args)
    print(json.dumps({key: result[key] for key in (
        "split", "candidate", "model", "score", "write_pass_5",
        "cost_per_100_conversations_usd", "median_latency_seconds"
    )}, indent=2))
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
