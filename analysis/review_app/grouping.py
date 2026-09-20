"""Group Cartwheel traces into conversations for human review."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

GAP_MINUTES = 5


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata(trace: dict[str, Any]) -> dict[str, Any]:
    md = trace.get("metadata")
    if isinstance(md, dict):
        return md
    return {}


def _attributes(trace: dict[str, Any]) -> dict[str, Any]:
    attrs = _metadata(trace).get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            return {}
    return attrs if isinstance(attrs, dict) else {}


def session_id(trace: dict[str, Any]) -> str | None:
    meta = trace.get("meta") or {}
    value = meta.get("session_id")
    if value:
        return str(value)
    sid = _attributes(trace).get("cartwheel.session_id")
    return str(sid) if sid else None


def scenario_id(trace: dict[str, Any]) -> str | None:
    meta = trace.get("meta") or {}
    value = meta.get("scenario_id")
    if value:
        return str(value)
    value = _attributes(trace).get("cartwheel.scenario_id")
    return str(value) if value else None


def _trace_id(trace: dict[str, Any]) -> str:
    return str(trace.get("trace_id") or trace.get("id"))


def cluster_by_conversation(
    traces: list[dict[str, Any]], gap_minutes: int = GAP_MINUTES
) -> list[list[dict[str, Any]]]:
    """Partition traces into conversation groups."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    no_session: list[dict[str, Any]] = []
    for trace in traces:
        sid = session_id(trace)
        if sid:
            by_session.setdefault(sid, []).append(trace)
        else:
            no_session.append(trace)

    groups: list[list[dict[str, Any]]] = []
    for bucket in by_session.values():
        bucket.sort(key=lambda t: t.get("timestamp") or "")
        groups.append(bucket)

    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for trace in no_session:
        sc = scenario_id(trace) or _trace_id(trace)
        by_scenario.setdefault(sc, []).append(trace)

    gap_secs = gap_minutes * 60
    for bucket in by_scenario.values():
        bucket.sort(key=lambda t: t.get("timestamp") or "")
        run: list[dict[str, Any]] = []
        last_ts: datetime | None = None
        for trace in bucket:
            ts = _parse_ts(trace.get("timestamp"))
            if run and last_ts and ts and (ts - last_ts).total_seconds() > gap_secs:
                groups.append(run)
                run = []
            run.append(trace)
            if ts:
                last_ts = ts
        if run:
            groups.append(run)
    return groups


def _group_for_trace(
    trace_id: str, groups: list[list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    for group in groups:
        if any(_trace_id(t) == trace_id for t in group):
            return group
    return []


def build_conversations(
    samples: list[dict[str, Any]],
    store_traces: list[dict[str, Any]],
    sample_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return one conversation view per sample, with sibling turns included."""
    sample_ids = sample_ids or {_trace_id(s) for s in samples}
    by_id = {_trace_id(t): t for t in store_traces}
    for sample in samples:
        tid = _trace_id(sample)
        existing = by_id.get(tid)
        if existing is None:
            by_id[tid] = sample
            continue
        merged = dict(existing)
        for key in ("trace", "features", "stats", "meta", "timestamp", "reason", "flags"):
            if not merged.get(key) and sample.get(key):
                merged[key] = sample[key]
        by_id[tid] = merged

    groups = cluster_by_conversation(list(by_id.values()))
    conversations: list[dict[str, Any]] = []
    for sample in samples:
        focus_id = _trace_id(sample)
        group = _group_for_trace(focus_id, groups) or [sample]
        group.sort(key=lambda t: t.get("timestamp") or "")
        sid = session_id(group[0])
        sc = scenario_id(group[0])
        conv_id = f"session:{sid}" if sid else f"scenario:{sc}:{focus_id[:8]}"
        turns = []
        for turn in group:
            tid = _trace_id(turn)
            turns.append(
                {
                    "trace_id": tid,
                    "timestamp": turn.get("timestamp"),
                    "trace": turn.get("trace", []),
                    "meta": turn.get("meta") or {},
                    "features": turn.get("features") or {},
                    "stats": turn.get("stats") or {},
                    "reason": turn.get("reason"),
                    "flags": turn.get("flags", []),
                    "in_sample": tid in sample_ids,
                }
            )
        conversations.append(
            {
                "conversation_id": conv_id,
                "focus_trace_id": focus_id,
                "turns": turns,
                "meta": group[0].get("meta", {}),
                "reason": sample.get("reason"),
            }
        )
    return conversations
