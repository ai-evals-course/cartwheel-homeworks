"""Generate Harbor tasks from the Cartwheel evaluation case set."""

from __future__ import annotations

import argparse
from pathlib import Path

from harbor_adapter.export import DEFAULT_OUTPUT, export_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="export cases before their five-run classification",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="export one case id; repeat this option to select more cases",
    )
    args = parser.parse_args()
    tasks = export_tasks(
        args.cases,
        args.output,
        baseline=args.baseline,
        case_ids=set(args.case_ids) if args.case_ids else None,
    )
    print(f"Generated {len(tasks)} Harbor tasks in {args.output}")


if __name__ == "__main__":
    main()
