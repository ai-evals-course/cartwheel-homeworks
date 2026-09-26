"""Print a Harbor job summary and fail on regression cases."""

from __future__ import annotations

import argparse
from pathlib import Path

from harbor_adapter.summary import summarize_job, write_github_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--expected-attempts", type=int, default=None)
    parser.add_argument(
        "--classify",
        action="store_true",
        help="report regression or capability from five unclassified baseline runs",
    )
    args = parser.parse_args()
    markdown, passed = summarize_job(
        args.job_dir,
        cases_path=args.cases,
        expected_attempts=args.expected_attempts,
        classify=args.classify,
    )
    print(markdown, end="")
    write_github_summary(markdown)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
