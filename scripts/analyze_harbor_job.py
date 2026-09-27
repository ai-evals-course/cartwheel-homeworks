"""Write the Homework 6 pass@k comparison from a Harbor job."""

from __future__ import annotations

import argparse
from pathlib import Path

from harbor_adapter.analysis import analyze_capability_job, write_analysis
from replay.rollout import load_cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--case", required=True, dest="case_id")
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cases = {case["id"]: case for case in load_cases(args.cases)}
    case = cases.get(args.case_id)
    if case is None:
        parser.error(f"unknown case id: {args.case_id}")
    if case["kind"] != "capability":
        parser.error(f"{args.case_id} is not a capability case")
    analysis = analyze_capability_job(args.job_dir, args.case_id)
    write_analysis(args.out, analysis)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
