"""Export all Langfuse traces joined to a scenario JSONL file.

Usage (after loading ``.env`` and completing the runs):

    uv run python -m scenarios.export_langfuse \
      scenarios/support_scenarios.jsonl traces/support_traces.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from observability.instrument import load_env
from scenarios.validate import load_jsonl, validate_scenarios


def _jsonable(value: Any) -> Any:
    """Convert an SDK response model into plain JSON data.

    The Langfuse SDK returns pydantic v1 models, whose ``dict()`` keeps
    datetime objects, so those models go through their own JSON encoder.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "json") and hasattr(value, "dict"):
        return json.loads(value.json(by_alias=True))
    if hasattr(value, "dict"):
        return value.dict(by_alias=True)
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _attribute_scenario_id(metadata: Any) -> str | None:
    """Read the scenario id from trace or observation metadata.

    Langfuse stores OpenTelemetry span attributes under ``metadata.attributes``
    (a JSON string in ClickHouse, a dict from the API), so the id is checked
    there as well as at the top level.
    """
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("cartwheel.scenario_id")
    if not value:
        attributes = metadata.get("attributes")
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except ValueError:
                attributes = None
        if isinstance(attributes, dict):
            value = attributes.get("cartwheel.scenario_id")
    return str(value) if value else None


def _scenario_id(record: Any) -> str | None:
    """Find the scenario attribute on a trace or one of its observations."""
    if isinstance(record, dict):
        found = _attribute_scenario_id(record.get("metadata"))
        if found:
            return found
        for value in record.values():
            found = _scenario_id(value)
            if found:
                return found
    elif isinstance(record, list):
        for value in record:
            found = _scenario_id(value)
            if found:
                return found
    return None


def export_scenario_traces(
    scenario_ids: set[str], client: Any, *, page_size: int = 100
) -> list[dict[str, Any]]:
    """Fetch full trace records whose metadata carries a selected scenario id."""
    matches: list[dict[str, Any]] = []
    page = 1
    while True:
        response = client.api.trace.list(page=page, limit=page_size)
        batch = list(response.data or [])
        for trace_summary in batch:
            scenario_id = _attribute_scenario_id(getattr(trace_summary, "metadata", None))
            full = client.api.trace.get(getattr(trace_summary, "id"))
            record = _jsonable(full)
            scenario_id = scenario_id or _scenario_id(record)
            if scenario_id not in scenario_ids:
                continue
            if isinstance(record, dict):
                record.setdefault("cartwheel_scenario_id", scenario_id)
            matches.append(record)
        if len(batch) < page_size:
            break
        page += 1
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Cartwheel scenario traces from Langfuse.")
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="write a partial export instead of failing when a scenario has no trace",
    )
    args = parser.parse_args()

    records = load_jsonl(args.scenarios)
    validate_scenarios(records)
    scenario_ids = {record["id"] for record in records}
    load_env()
    from langfuse import Langfuse

    traces = export_scenario_traces(scenario_ids, Langfuse())
    exported_ids = {trace.get("cartwheel_scenario_id") for trace in traces}
    missing = sorted(scenario_ids - exported_ids)
    if missing and not args.allow_missing:
        preview = ", ".join(missing[:10])
        raise RuntimeError(
            f"{len(missing)} scenario ids have no exported trace ({preview}); "
            "finish the runs or pass --allow-missing for a diagnostic export"
        )
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(scenario_ids),
        "trace_count": len(traces),
        "missing_scenario_ids": missing,
        "traces": traces,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n"
    )
    print(
        f"Exported {len(traces)} traces for {len(exported_ids)} of "
        f"{len(scenario_ids)} scenarios to {args.output}"
    )


if __name__ == "__main__":
    main()
