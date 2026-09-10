"""Normalize Module 1 and Langfuse traces for Module 2 review.

Every Module 2 component consumes one record shape. The original Langfuse
identifier remains the primary identifier, so a human judgment can be written
back to the trace as a score.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


def _data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "dict"):
        return value.dict(by_alias=True)
    return value


def _text(value: Any) -> str:
    value = _data(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _timestamp(value: Any) -> str | None:
    """Return an ISO timestamp without dropping an existing string value."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _observation_record(value: Any) -> dict[str, Any] | None:
    """Keep the observation fields needed by monitoring and cost review."""
    observation = _data(value)
    if not isinstance(observation, dict):
        return None
    return {
        "id": observation.get("id"),
        "type": observation.get("type"),
        "name": observation.get("name"),
        "start_time": _timestamp(
            observation.get("start_time") or observation.get("startTime")
        ),
        "end_time": _timestamp(
            observation.get("end_time") or observation.get("endTime")
        ),
        "model": observation.get("model") or observation.get("model_id"),
        "model_parameters": _data(
            observation.get("model_parameters") or observation.get("modelParameters")
        ),
        "input": _data(observation.get("input")),
        "output": _data(observation.get("output")),
        "usage_details": _data(
            observation.get("usage_details")
            or observation.get("usageDetails")
            or observation.get("usage")
        ),
        "cost_details": _data(
            observation.get("cost_details") or observation.get("costDetails")
        ),
        "total_cost": observation.get("total_cost")
        if observation.get("total_cost") is not None
        else observation.get("totalCost"),
        "latency_seconds": observation.get("latency"),
        "time_to_first_token_seconds": observation.get("time_to_first_token")
        if observation.get("time_to_first_token") is not None
        else observation.get("timeToFirstToken"),
        "metadata": _data(observation.get("metadata")),
    }


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Return trace metadata with nested OpenTelemetry attributes merged in.

    Langfuse stores span attributes under ``metadata.attributes`` (a JSON
    string in ClickHouse, a dict from the API). Top level keys win when both
    are present.
    """
    metadata = _data(record.get("metadata"))
    if not isinstance(metadata, dict):
        return {}
    attributes = metadata.get("attributes")
    if isinstance(attributes, str):
        try:
            attributes = json.loads(attributes)
        except ValueError:
            attributes = None
    merged = dict(attributes) if isinstance(attributes, dict) else {}
    merged.update(metadata)
    return merged


def _observation_message(observation: Any) -> list[dict[str, Any]]:
    obs = _data(observation)
    if not isinstance(obs, dict):
        return []
    name = str(obs.get("name") or obs.get("type") or "step")
    inp = obs.get("input")
    out = obs.get("output")
    lowered = name.lower()
    messages: list[dict[str, Any]] = []
    if "tool" in lowered or obs.get("type") in {"TOOL", "tool"}:
        if inp is not None:
            messages.append(
                {"role": "tool_call", "name": name, "arguments": _data(inp)}
            )
        if out is not None:
            messages.append(
                {"role": "tool_result", "name": name, "content": _data(out)}
            )
    elif out is not None:
        messages.append({"role": "observation", "label": name, "text": _text(out)})
    return messages


def _messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    existing = record.get("trace")
    if isinstance(existing, list):
        return [dict(_data(item)) for item in existing if isinstance(_data(item), dict)]

    turns = record.get("turns")
    if isinstance(turns, list):
        messages: list[dict[str, Any]] = []
        for turn in turns:
            item = _data(turn)
            if not isinstance(item, dict):
                continue
            if item.get("user") is not None:
                messages.append({"role": "user", "text": _text(item["user"])})
            if item.get("agent") is not None:
                messages.append({"role": "assistant", "text": _text(item["agent"])})
        if messages:
            return messages

    messages = []
    if record.get("input") is not None:
        messages.append({"role": "user", "text": _text(record.get("input"))})
    for observation in record.get("observations") or []:
        messages.extend(_observation_message(observation))
    if record.get("output") is not None:
        messages.append({"role": "assistant", "text": _text(record.get("output"))})

    segments = record.get("segments")
    if not messages and isinstance(segments, dict):
        for name, value in segments.items():
            messages.append({"role": "observation", "label": str(name), "text": _text(value)})
    if not messages and record.get("text") is not None:
        messages.append({"role": "observation", "label": "trace", "text": _text(record["text"])})
    return messages


def _flatten(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "step")
        if role == "tool_call":
            content = _text(message.get("arguments"))
        else:
            content = _text(message.get("text", message.get("content")))
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def normalize_trace(value: Any) -> dict[str, Any]:
    """Return one trace in the shared Module 2 and Module 3 representation.

    The compact message and feature fields support error analysis. The time,
    model, input, output, and observation fields let a monitoring job select a
    time window and prepare the exact evidence needed by a saved judge.
    """
    raw = _data(value)
    if not isinstance(raw, dict):
        raise ValueError("a trace record must be an object")
    metadata = _metadata(raw)
    trace_id = raw.get("id") or raw.get("trace_id")
    if not trace_id:
        raise ValueError("a trace record has no stable id or trace_id")
    messages = _messages(raw)
    if not messages and not isinstance(raw.get("features"), dict):
        raise ValueError(f"trace {trace_id} contains no renderable messages or segments")

    tool_calls = [m for m in messages if m.get("role") == "tool_call"]
    tools = {str(m.get("name")) for m in tool_calls if m.get("name")}
    retrieval = any(
        "retriev" in str(m.get("label", m.get("name", ""))).lower()
        or "policy" in str(m.get("label", m.get("name", ""))).lower()
        for m in messages
    )
    text = _flatten(messages)
    usage = _data(raw.get("usage"))
    token_total = 0
    if isinstance(usage, dict):
        token_total = int(usage.get("total_tokens") or usage.get("total") or 0)
    supplied_features = raw.get("features")
    features = dict(supplied_features) if isinstance(supplied_features, dict) else {}
    features.update(
        {
            "turn_count": sum(m.get("role") in {"user", "assistant"} for m in messages),
            "tool_call_count": len(tool_calls),
            "distinct_tools": len(tools),
            "has_retrieval": int(retrieval),
            "tokens": int(features.get("tokens") or token_total or len(text.split())),
        }
    )
    meta = {
        "role": metadata.get("cartwheel.user_role") or metadata.get("role"),
        "store": metadata.get("cartwheel.store_id") or metadata.get("store_id"),
        "prompt_version": metadata.get("cartwheel.prompt_version")
        or metadata.get("prompt_version"),
        "scenario_id": raw.get("cartwheel_scenario_id")
        or metadata.get("cartwheel.scenario_id")
        or metadata.get("scenario_id"),
    }
    supplied_segments = raw.get("segments")
    segments = dict(supplied_segments) if isinstance(supplied_segments, dict) else {}
    segments.update({key: val for key, val in meta.items() if val is not None})
    observations = [
        record
        for observation in raw.get("observations") or []
        if (record := _observation_record(observation)) is not None
    ]
    models = list(
        dict.fromkeys(
            str(observation["model"])
            for observation in observations
            if observation.get("model")
        )
    )
    return {
        "id": str(trace_id),
        "trace_id": str(trace_id),
        "timestamp": _timestamp(raw.get("timestamp")),
        "models": models,
        "input": _data(raw.get("input")),
        "output": _data(raw.get("output")),
        "observations": observations,
        "trace": messages,
        "text": text,
        "features": features,
        "meta": {key: val for key, val in meta.items() if val is not None},
        "segments": segments,
        "metadata": metadata,
        "permalink": raw.get("permalink") or raw.get("url"),
    }


def normalize_traces(values: list[Any]) -> list[dict[str, Any]]:
    """Normalize a collection and reject duplicate identifiers."""
    normalized = [normalize_trace(value) for value in values]
    ids = [record["id"] for record in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("the trace source contains duplicate identifiers")
    return normalized
