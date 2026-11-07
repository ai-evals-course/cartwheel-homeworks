"""Judge development for internal_language_exposed mode.

Run this script step-by-step:
  python analysis/run_judges.py prepare_inputs
  python analysis/run_judges.py split_data
  python analysis/run_judges.py run_development <prompt_path>
  python analysis/run_judges.py run_test <judge_id>
"""

import json
from pathlib import Path
from analysis.helpers import split_labels, register_judge, run_judge, judge_alignment, freeze_judge


def prepare_inputs():
    """Export labeled scenarios as judge inputs.

    For each labeled trace, extract the agent's final reply.
    Save to analysis/state/hw5_trace_inputs.json.
    """
    # Load HW4 labels (internal_language_exposed)
    labels_path = Path("analysis/state/labels/internal_language_exposed.json")
    with open(labels_path) as f:
        labels_data = json.load(f)

    labeled_ids = {l["scenario_id"]: l["label"] for l in labels_data["labels"]}
    print(f"Loaded {len(labeled_ids)} labels from HW4")
    print(f"  Pass: {sum(1 for l in labeled_ids.values() if l == 'Pass')}")
    print(f"  Fail: {sum(1 for l in labeled_ids.values() if l == 'Fail')}")

    # Load all traces
    traces_path = Path("traces/support_traces.json")
    with open(traces_path) as f:
        traces_data = json.load(f)

    # Build map: scenario_id -> trace
    traces_by_scenario = {}
    for trace in traces_data["traces"]:
        scenario_id = trace.get("cartwheel_scenario_id")
        if scenario_id:
            traces_by_scenario[scenario_id] = trace

    print(f"Loaded {len(traces_by_scenario)} traces")

    # Create judge inputs: extract agent reply only
    inputs = []
    missing_count = 0

    for scenario_id, label in labeled_ids.items():
        if scenario_id not in traces_by_scenario:
            missing_count += 1
            continue

        trace = traces_by_scenario[scenario_id]

        # Extract agent's final reply
        output = trace.get("output", [])
        if not output:
            continue

        # Last output item is typically the agent's final response
        agent_response = output[-1]
        agent_text = ""

        if isinstance(agent_response, dict) and "parts" in agent_response:
            parts = agent_response["parts"]
            if parts and isinstance(parts, list):
                agent_text = parts[0].get("content", "")

        if not agent_text:
            continue

        # Create input record: just the agent's reply
        inputs.append({
            "trace_id": scenario_id,
            "trace": [
                {
                    "role": "assistant",
                    "content": agent_text
                }
            ]
        })

    # Save
    output_path = Path("analysis/state/hw5_trace_inputs.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(inputs, f, indent=2)

    print(f"Saved {len(inputs)} judge inputs to {output_path}")
    print(f"Skipped {missing_count} labels with no matching trace")


def split_data(mode="internal_language_exposed"):
    """Split labels into train/dev/test using validate-evaluator.

    Splits: 20% train (6 Pass, 6 Fail), 40% dev (12 Pass, 12 Fail), 40% test (12 Pass, 12 Fail)
    """
    # Load trace inputs to get eligible trace IDs
    inputs_path = Path("analysis/state/hw5_trace_inputs.json")
    with open(inputs_path) as f:
        inputs = json.load(f)

    eligible_trace_ids = [record["trace_id"] for record in inputs]
    print(f"Splitting {len(eligible_trace_ids)} traces into train/dev/test")

    # Use helper to split
    splits = split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=eligible_trace_ids,
    )

    # Save splits
    splits_path = Path("analysis/state/splits.json")
    with open(splits_path, "w") as f:
        json.dump(splits, f, indent=2)

    # Report
    print("\nSplit results:")
    for split_name, split_data in splits.items():
        print(f"  {split_name}: {len(split_data)} traces")


def run_development(mode, prompt_path, judge_model="claude-haiku-4-5"):
    """Run judge on development set and calculate metrics.

    Args:
        mode: Failure mode ID (e.g., "internal_language_exposed")
        prompt_path: Path to prompt file (e.g., "analysis/prompts/internal_language_exposed-v0.txt")
        judge_model: Judge model to use (default: claude-haiku-4-5)
    """
    import os
    from anthropic import Anthropic

    # Load .env file
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value

    prompt_text = Path(prompt_path).read_text()

    # Register judge
    print(f"Registering judge from {prompt_path}")
    record = register_judge(
        mode=mode,
        prompt_text=prompt_text,
        judge_model=judge_model,
    )
    judge_id = record["judge_id"]
    print(f"Judge registered: {judge_id}")

    # Create Claude classifier
    client = Anthropic()

    def classify_with_claude(prompt_text, trace_ids):
        """Classify traces using Claude."""
        with open("analysis/state/hw5_trace_inputs.json") as f:
            all_inputs = {record["trace_id"]: record for record in json.load(f)}

        results = {}
        for trace_id in trace_ids:
            trace_input = all_inputs[trace_id]
            agent_text = trace_input["trace"][0]["content"]

            # Build messages for Claude
            full_prompt = prompt_text + "\n" + agent_text

            response = client.messages.create(
                model=judge_model,
                max_tokens=200,
                messages=[
                    {"role": "user", "content": full_prompt}
                ]
            )

            # Parse response for verdict (Pass=0, Fail=1)
            verdict_text = response.content[0].text.lower()
            if "fail" in verdict_text and "pass" not in verdict_text:
                results[trace_id] = 1
            else:
                results[trace_id] = 0

        return results

    # Run on development set
    print(f"Running judge on development set...")
    run_judge(judge_id, split="dev", batch_size=10, classify=classify_with_claude)

    # Calculate alignment
    development = judge_alignment(judge_id, split="dev")

    # Save metrics
    metrics_path = Path(f"analysis/report/dev-{judge_id}.json")
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path, "w") as f:
        json.dump(development, f, indent=2)

    print(f"\nDevelopment metrics saved to {metrics_path}")
    print(f"TPR: {development.get('tpr', 'N/A'):.2%}")
    print(f"TNR: {development.get('tnr', 'N/A'):.2%}")

    return judge_id, development


def run_test(judge_id):
    """Run judge on test set and freeze the version.

    Args:
        judge_id: Judge ID from run_development
    """
    import os
    from anthropic import Anthropic

    # Load .env file
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value

    print(f"Judge {judge_id} (freezing if not already frozen)")

    # Create Claude classifier for test
    client = Anthropic()
    judge_data = {}

    def classify_with_claude(prompt_text, trace_ids):
        """Classify traces using Claude."""
        with open("analysis/state/hw5_trace_inputs.json") as f:
            all_inputs = {record["trace_id"]: record for record in json.load(f)}

        results = {}
        for trace_id in trace_ids:
            trace_input = all_inputs[trace_id]
            agent_text = trace_input["trace"][0]["content"]

            # Build messages for Claude
            full_prompt = prompt_text + "\n" + agent_text

            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=200,
                messages=[
                    {"role": "user", "content": full_prompt}
                ]
            )

            # Parse response for verdict (Pass=0, Fail=1)
            verdict_text = response.content[0].text.lower()
            if "fail" in verdict_text and "pass" not in verdict_text:
                results[trace_id] = 1
            else:
                results[trace_id] = 0

        return results

    print(f"Running judge on test set...")
    run_judge(judge_id, split="test", batch_size=10, classify=classify_with_claude)

    # Calculate alignment
    test = judge_alignment(judge_id, split="test")

    # Save metrics
    metrics_path = Path(f"analysis/report/test-{judge_id}.json")
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path, "w") as f:
        json.dump(test, f, indent=2)

    print(f"\nTest metrics saved to {metrics_path}")
    print(f"TPR: {test.get('tpr', 'N/A'):.2%}")
    print(f"TNR: {test.get('tnr', 'N/A'):.2%}")

    return test


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "prepare_inputs":
        prepare_inputs()
    elif command == "split_data":
        split_data()
    elif command == "run_development":
        if len(sys.argv) < 3:
            print("Usage: python analysis/run_judges.py run_development <prompt_path>")
            sys.exit(1)
        run_development("internal_language_exposed", sys.argv[2])
    elif command == "run_test":
        if len(sys.argv) < 3:
            print("Usage: python analysis/run_judges.py run_test <judge_id>")
            sys.exit(1)
        run_test(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
