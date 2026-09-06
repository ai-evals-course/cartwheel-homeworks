"""Exercise the CLI with the real SDK and an offline model."""

from __future__ import annotations

import json
from typing import Any

import httpx
import langfuse
import pytest
from agents import Agent, function_tool
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tracing import get_trace_provider, set_trace_provider, trace
from agents.tracing.processors import BackendSpanExporter, BatchTraceProcessor
from agents.tracing.provider import DefaultTraceProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from opentelemetry.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent import cli
from agent.auth import AuthContext
from observability import instrument


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


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("tracing", ["plain", "missing_public", "missing_secret", "configured"])
def test_cli_tool_results(debug, tracing, tmp_path, monkeypatch, capsys, caplog) -> None:
    executed = []

    @function_tool
    def lookup(order_id: int) -> dict:
        executed.append(order_id)
        return {"eligible": order_id == 4127}

    model = ScriptedModel()
    agent = Agent(name="offline-cli", model=model, tools=[lookup])
    ctx = AuthContext(user_id=1, role="shopper")
    messages = iter(["Check both orders", "quit"])
    argv = ["agent.cli"] + (["--debug"] if debug else [])
    if tracing != "plain":
        argv.append("--trace")
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    monkeypatch.setattr(cli, "build_agent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(cli, "resolve_auth", lambda *args: ctx)
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(cli, "SESSIONS_DB", tmp_path / "sessions.db")

    # Use the real setup and processor replacement with a local OTel sink.
    monkeypatch.setattr(instrument, "load_env", lambda: None)
    monkeypatch.setattr(instrument, "_genai_instrumented", False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "offline-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "offline-secret")
    if tracing == "missing_public":
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY")
    elif tracing == "missing_secret":
        monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    otel_provider = TracerProvider()
    otel_exporter = InMemorySpanExporter()
    otel_provider.add_span_processor(SimpleSpanProcessor(otel_exporter))
    setup_calls = []
    monkeypatch.setattr(langfuse, "get_client", lambda: setup_calls.append(True))
    monkeypatch.setattr(instrument.trace, "get_tracer_provider", lambda: otel_provider)

    # A hosted export would fail for ZDR. Capture it without contacting OpenAI.
    requests = []

    def reject_export(request):
        requests.append(request)
        return httpx.Response(403, text="simulated ZDR tracing rejection")

    exporter = BackendSpanExporter(api_key="offline-placeholder")
    exporter._client.close()
    exporter._client = httpx.Client(transport=httpx.MockTransport(reject_export))
    hosted_processor = BatchTraceProcessor(exporter)
    previous_provider = get_trace_provider()
    provider = DefaultTraceProvider()
    provider.set_disabled(False)
    provider.register_processor(hosted_processor)
    set_trace_provider(provider)
    try:
        cli.main()
        assert sorted(executed) == [3980, 4127]
        assert model.calls == 2
        output = capsys.readouterr().out
        if debug:
            assert (
                "  [tool] lookup({'order_id': 4127})\n"
                "    -> {'eligible': True}\n"
                "  [tool] lookup({'order_id': 3980})\n"
                "    -> {'eligible': False}\n"
            ) in output
        else:
            assert "[tool]" not in output
        assert "agent> Done." in output
        hosted_processor.force_flush()
        assert requests == []
        spans = otel_exporter.get_finished_spans()
        if tracing == "configured":
            assert setup_calls == [True]
            assert sum(span.name == "lookup.tool" for span in spans) == 2
        else:
            assert setup_calls == []
            assert spans == ()
        if tracing.startswith("missing_"):
            assert "tracing is off" in caplog.text
        # Disabling tracing for CLI runs must not disable unrelated SDK traces.
        with trace("unrelated") as unrelated:
            assert unrelated.export() is not None
        hosted_processor.force_flush()
        assert len(requests) == (0 if tracing == "configured" else 1)
    finally:
        if tracing == "configured":
            OpenAIAgentsInstrumentor().uninstrument()
        set_trace_provider(previous_provider)
        provider.shutdown()
        hosted_processor.shutdown()
        exporter._client.close()
        otel_provider.shutdown()
