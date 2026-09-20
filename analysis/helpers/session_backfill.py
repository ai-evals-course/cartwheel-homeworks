"""Infer session ids for traces recorded before cartwheel.session_id was exported.

Langfuse trace metadata is immutable after ingestion, so historical traces
cannot be rewritten in the store. This module assigns a stable inferred
session id to each trace from scenario id and timestamp clustering, persists
the mapping under ``analysis/state/session_backfill.json``, and lets
normalization attach the id during review.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ._state import read_json, state_path, write_json

GAP_MINUTES = 5
BACKFILL_PATH = state_path("session_backfill.json")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _trace_id(trace: dict[str, Any]) -> str:
    return str(trace.get("trace_id") or trace.get("id"))


def _scenario_id(trace: dict[str, Any]) -> str:
    meta = trace.get("meta") or {}
    if meta.get("scenario_id"):
        return str(meta["scenario_id"])
    metadata = trace.get("metadata") or {}
    attrs = metadata.get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    if isinstance(attrs, dict) and attrs.get("cartwheel.scenario_id"):
        return str(attrs["cartwheel.scenario_id"])
    return "unknown"


def _existing_session_id(trace: dict[str, Any]) -> str | None:
    meta = trace.get("meta") or {}
    if meta.get("session_id"):
        return str(meta["session_id"])
    metadata = trace.get("metadata") or {}
    attrs = metadata.get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    if isinstance(attrs, dict):
        value = attrs.get("cartwheel.session_id")
        if value:
            return str(value)
    return None


def _make_inferred_session_id(scenario_id: str, first_trace_id: str, first_ts: str | None) -> str:
    """Return a stable 32-hex id in the same shape as server session ids."""
    seed = f"inferred:{scenario_id}:{first_trace_id}:{first_ts or 'unknown'}"
    try:
        from observability.instrument import load_env

        load_env()
        from analysis.helpers import langfuse_io

        if langfuse_io.is_configured():
            return langfuse_io.logical_to_langfuse_id(seed)
    except Exception:
        pass
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def infer_session_mapping(traces: list[dict[str, Any]]) -> dict[str, str]:
    """Map trace_id -> session_id for traces missing cartwheel.session_id."""
    mapping: dict[str, str] = {}
    needs_backfill: list[dict[str, Any]] = []
    for trace in traces:
        tid = _trace_id(trace)
        existing = _existing_session_id(trace)
        if existing:
            mapping[tid] = existing
        else:
            needs_backfill.append(trace)

    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for trace in needs_backfill:
        by_scenario.setdefault(_scenario_id(trace), []).append(trace)

    gap_secs = GAP_MINUTES * 60
    for scenario, bucket in by_scenario.items():
        bucket.sort(key=lambda t: t.get("timestamp") or "")
        run: list[dict[str, Any]] = []
        last_ts: datetime | None = None
        runs: list[list[dict[str, Any]]] = []
        for trace in bucket:
            ts = _parse_ts(trace.get("timestamp"))
            if run and last_ts and ts and (ts - last_ts).total_seconds() > gap_secs:
                runs.append(run)
                run = []
            run.append(trace)
            if ts:
                last_ts = ts
        if run:
            runs.append(run)
        for group in runs:
            first = group[0]
            session = _make_inferred_session_id(
                scenario, _trace_id(first), first.get("timestamp")
            )
            for trace in group:
                mapping[_trace_id(trace)] = session
    return mapping


def load_session_backfill() -> dict[str, str]:
    """Return trace_id -> session_id from the committed backfill file."""
    data = read_json(BACKFILL_PATH, {})
    if not isinstance(data, dict):
        return {}
    mapping = data.get("mapping")
    return {str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {}


def build_session_backfill(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute and persist the session backfill manifest."""
    mapping = infer_session_mapping(traces)
    source_with_session = sum(1 for t in traces if _existing_session_id(t))
    backfilled_ids = [_trace_id(t) for t in traces if not _existing_session_id(t)]
    inferred_sessions = {mapping[tid] for tid in backfilled_ids if tid in mapping}
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "trace_count": len(traces),
        "mapped_count": len(mapping),
        "existing_session_count": source_with_session,
        "inferred_session_count": len(inferred_sessions),
        "gap_minutes": GAP_MINUTES,
        "mapping": mapping,
    }
    write_json(BACKFILL_PATH, payload)
    return payload
