"""Exercise the CLI with the real SDK and an offline model."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from agents import Agent, function_tool
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tracing import (
    TracingProcessor,
    get_trace_provider,
    set_trace_provider,
    trace,
)
from agents.tracing.provider import DefaultTraceProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from agent import cli
from agent.auth import AuthContext


class ScriptedModel(Model):
    def __init__(self) -> None:
        self.calls = 0

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    call_id=f"call-{order_id}",
                    name="lookup",
                    arguments=json.dumps({"order_id": order_id}),
                )
                for order_id in (4127, 3980)
            ]
        else:
            output = [
                ResponseOutputMessage(
                    id="reply",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(type="output_text", text="Done.", annotations=[])
                    ],
                )
            ]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    async def stream_response(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("The CLI uses non-streaming runs")
        yield


@pytest.mark.parametrize("tracing", [False, True])
def test_cli_tool_results_and_tracing(tracing, tmp_path, monkeypatch, capsys) -> None:
    executed = []

    @function_tool
    def lookup(order_id: int) -> dict:
        executed.append(order_id)
        return {"eligible": order_id == 4127}

    model = ScriptedModel()
    agent = Agent(name="offline-cli", model=model, tools=[lookup])
    ctx = AuthContext(user_id=1, role="shopper")
    messages = iter(["Check both orders", "quit"])
    setup_tracing = Mock()
    monkeypatch.setattr(
        "sys.argv", ["agent.cli", "--debug"] + (["--trace"] if tracing else [])
    )
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    monkeypatch.setattr(cli, "build_agent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(cli, "resolve_auth", lambda *args: ctx)
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(cli, "setup_tracing", setup_tracing)
    monkeypatch.setattr(cli, "SESSIONS_DB", tmp_path / "sessions.db")

    # Collect SDK callbacks locally so the test never exports to a backend.
    previous_provider = get_trace_provider()
    provider = DefaultTraceProvider()
    provider.set_disabled(False)
    processor = create_autospec(TracingProcessor, instance=True)
    provider.register_processor(processor)
    set_trace_provider(provider)
    try:
        cli.main()
        assert sorted(executed) == [3980, 4127]
        assert model.calls == 2
        output = capsys.readouterr().out
        assert (
            "  [tool] lookup({'order_id': 4127})\n"
            "    -> {'eligible': True}\n"
            "  [tool] lookup({'order_id': 3980})\n"
            "    -> {'eligible': False}\n"
        ) in output
        assert "agent> Done." in output
        assert processor.on_trace_end.call_count == int(tracing)
        assert setup_tracing.call_count == int(tracing)

        # A plain CLI run must not disable tracing for other SDK callers.
        with trace("unrelated-run"):
            pass
        assert processor.on_trace_end.call_count == int(tracing) + 1
    finally:
        set_trace_provider(previous_provider)
        provider.shutdown()
