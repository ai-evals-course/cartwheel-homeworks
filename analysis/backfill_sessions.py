"""Build analysis/state/session_backfill.json from the Langfuse trace store.

Usage:
    uv run python -m analysis.backfill_sessions
    uv run python -m analysis.backfill_sessions traces/support_traces.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from observability.instrument import load_env

from analysis.helpers.session_backfill import build_session_backfill
from analysis.helpers.tools import _load_trace_source


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        default="langfuse",
        help='trace source ("langfuse" or a JSON export path)',
    )
    args = parser.parse_args()
    traces = _load_trace_source(args.source)
    payload = build_session_backfill(traces)
    print(
        f"Wrote {payload['mapped_count']} trace mappings "
        f"({payload['inferred_session_count']} inferred sessions, "
        f"{payload['existing_session_count']} already had session ids) "
        f"to analysis/state/session_backfill.json"
    )


if __name__ == "__main__":
    main()
