"""Run one Cartwheel evaluation case inside a Harbor sandbox."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from replay.rollout import fresh_world, retrieved_docs_text, run_case


def run(case_path: Path, output_path: Path, model: str) -> dict[str, Any]:
    """Run the case in a freshly seeded world and save verifier evidence."""
    case = json.loads(case_path.read_text())
    state_root = Path("/app/data")
    with fresh_world(state_root):
        transcript = run_case(case, model=model)

    evidence = {
        "case_id": case["id"],
        "kind": case.get("kind", "unclassified"),
        "transcript": transcript,
        "retrieved_policy_documents": retrieved_docs_text(transcript),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=Path("/app/case.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("/app/cartwheel-result.json")
    )
    parser.add_argument("--model", default=os.environ.get("CARTWHEEL_MODEL"))
    args = parser.parse_args()
    if not args.model:
        parser.error("pass --model or set CARTWHEEL_MODEL")
    run(args.case, args.output, args.model)


if __name__ == "__main__":
    main()
