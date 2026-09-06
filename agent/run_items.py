"""Shared extraction of tool calls from Agents SDK run items."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from agents.items import RunItem


class ToolCallRecord(TypedDict):
    name: str | None
    arguments: Any
    result: NotRequired[Any]


def tool_calls_from_items(items: list[RunItem]) -> list[ToolCallRecord]:
    """Return calls with raw SDK arguments, matching results by call ID.

    A missing result key means no output arrived; an output can itself be
    None. Each consumer decides how to decode the arguments.
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
        arguments = (
            raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)
        )
        call: ToolCallRecord = {"name": item.tool_name, "arguments": arguments}
        if item.call_id in outputs:
            call["result"] = outputs[item.call_id]
        calls.append(call)
    return calls
