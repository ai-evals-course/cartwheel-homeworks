"""Keep CLI debug output and replay transcripts consistent with SDK items."""

import json

import pytest
from agents import Agent
from agents.items import MessageOutputItem, ToolCallItem, ToolCallOutputItem

from agent.cli import _print_tool_calls
from replay.rollout import _extract_turn
from tests.eval.fake_model import text_message, tool_call


def test_cli_and_replay_pair_repeated_calls_by_id(capsys) -> None:
    agent = Agent(name="offline")
    first = tool_call("lookup", {"order_id": 4127})
    second = tool_call("lookup", {"order_id": 3980})
    items = [
        ToolCallItem(agent=agent, raw_item=first),
        ToolCallItem(agent=agent, raw_item=second.model_dump()),
        ToolCallOutputItem(
            agent=agent, raw_item={"call_id": second.call_id}, output={"eligible": False}
        ),
        ToolCallOutputItem(
            agent=agent, raw_item={"call_id": first.call_id}, output={"eligible": True}
        ),
        MessageOutputItem(agent=agent, raw_item=text_message("Done.")),
    ]

    _print_tool_calls(items)
    assert capsys.readouterr().out == (
        "  [tool] lookup({'order_id': 4127})\n    -> {'eligible': True}\n"
        "  [tool] lookup({'order_id': 3980})\n    -> {'eligible': False}\n"
    )
    assert _extract_turn(items) == {
        "reply": "Done.",
        "tool_calls": [
            {"name": "lookup", "args": {"order_id": 4127}, "result": {"eligible": True}},
            {"name": "lookup", "args": {"order_id": 3980}, "result": {"eligible": False}},
        ],
        "steps": 5,
    }


def test_missing_output_differs_from_none(capsys) -> None:
    agent = Agent(name="offline")
    missing = tool_call("lookup", {})
    completed = tool_call("lookup", {})
    items = [
        ToolCallItem(agent=agent, raw_item=missing),
        ToolCallItem(agent=agent, raw_item=completed),
        ToolCallOutputItem(agent=agent, raw_item={"call_id": completed.call_id}, output=None),
    ]

    _print_tool_calls(items)
    assert capsys.readouterr().out == (
        "  [tool] lookup({})\n"
        "  [tool] lookup({})\n    -> None\n"
    )
    # Replay keeps its existing schema, with a result key even when output is absent.
    assert _extract_turn(items) == {
        "reply": "",
        "tool_calls": [
            {"name": "lookup", "args": {}, "result": None},
            {"name": "lookup", "args": {}, "result": None},
        ],
        "steps": 3,
    }


@pytest.mark.parametrize(
    "arguments,cli_args,replay_args", [("", "", {}), ("null", "None", None)]
)
def test_empty_arguments_and_json_null_keep_consumer_formats(
    arguments, cli_args, replay_args, capsys
) -> None:
    raw = tool_call("lookup", {})
    raw.arguments = arguments
    items = [ToolCallItem(agent=Agent(name="offline"), raw_item=raw)]

    _print_tool_calls(items)
    assert capsys.readouterr().out == f"  [tool] lookup({cli_args})\n"
    assert _extract_turn(items)["tool_calls"][0]["args"] == replay_args


def test_malformed_arguments_print_in_cli_and_raise_in_replay(capsys) -> None:
    raw = tool_call("lookup", {})
    raw.arguments = "{unfinished"
    items = [ToolCallItem(agent=Agent(name="offline"), raw_item=raw)]

    _print_tool_calls(items)
    assert capsys.readouterr().out == "  [tool] lookup({unfinished)\n"
    with pytest.raises(json.JSONDecodeError):
        _extract_turn(items)
