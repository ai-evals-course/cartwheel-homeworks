"""Shared extraction of tool calls from Agents SDK run items."""

from __future__ import annotations

import json
from typing import Any, NotRequired, TypedDict

from agents.items import RunItem


class ToolCallRecord(TypedDict):
    name: str | None
    args: Any
    result: NotRequired[Any]


def tool_calls_from_items(items: list[RunItem]) -> list[ToolCallRecord]:
    """Return calls in order, matching results by call ID.

    A missing result key means no output arrived; an output can itself be
    None. Keep malformed argument strings available for inspection.
    """
    outputs = {
        item.call_id: item.output
        for item in items
        if item.type == "tool_call_output_item" and item.call_id is not None
    }
    calls: list[ToolCallRecord] = []
    for item in items:
        if item.type != "tool_call_item":
            continue
        raw = item.raw_item
        args = raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        call: ToolCallRecord = {"name": item.tool_name, "args": args}
        if item.call_id in outputs:
            call["result"] = outputs[item.call_id]
        calls.append(call)
    return calls
