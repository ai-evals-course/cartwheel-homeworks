"""Exercise the CLI with the real SDK and an offline model."""

from __future__ import annotations

import asyncio
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
from opentelemetry.trace import NoOpTracerProvider
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


@pytest.fixture
def hosted_exports(monkeypatch):
    """Isolate SDK tracing and capture hosted exports without network calls."""
    monkeypatch.setattr(instrument, "load_env", lambda: None)
    monkeypatch.setattr(instrument, "_genai_instrumented", False)
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
        yield hosted_processor, requests
    finally:
        instrumentor = OpenAIAgentsInstrumentor()
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
        set_trace_provider(previous_provider)
        provider.shutdown()
        hosted_processor.shutdown()
        exporter._client.close()


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("tracing", ["plain", "missing_public", "missing_secret", "configured", "openai"])
def test_cli_tool_results(debug, tracing, tmp_path, monkeypatch, capsys, caplog, hosted_exports) -> None:
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
    if tracing == "openai":
        argv.append("--trace-openai")
    elif tracing != "plain":
        argv.append("--trace")
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    monkeypatch.setattr(cli, "build_agent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(cli, "resolve_auth", lambda *args: ctx)
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(cli, "SESSIONS_DB", tmp_path / "sessions.db")

    # Use the real setup and processor replacement with a local OTel sink.
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
    selected_provider = NoOpTracerProvider() if tracing == "missing_secret" else otel_provider
    monkeypatch.setattr(instrument.trace, "get_tracer_provider", lambda: selected_provider)

    hosted_processor, requests = hosted_exports
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
        assert len(requests) == int(tracing == "openai")
        spans = otel_exporter.get_finished_spans()
        assert setup_calls == ([True] if tracing in {"configured", "missing_secret"} else [])
        if tracing == "configured":
            assert sum(span.name == "lookup.tool" for span in spans) == 2
        else:
            assert spans == ()
        if tracing == "missing_public":
            assert "tracing is off" in caplog.text
        # Disabling tracing for CLI runs must not disable unrelated SDK traces.
        with trace("unrelated") as unrelated:
            assert unrelated.export() is not None
        hosted_processor.force_flush()
        expected = 0 if tracing in {"configured", "missing_secret"} else 1
        assert len(requests) == expected + int(tracing == "openai")
    finally:
        otel_provider.shutdown()


def test_trace_destinations_are_mutually_exclusive(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["agent.cli", "--trace", "--trace-openai"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_server_missing_secret_still_replaces_hosted_exporter(monkeypatch, hosted_exports) -> None:
    from server import app as server

    monkeypatch.setattr(server, "load_env", lambda: None)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "offline-public-server")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # Use real Langfuse initialization: absent secret creates a no-op client.
    hosted_processor, requests = hosted_exports

    async def run() -> None:
        async with server.lifespan(server.app):
            with trace("student-completed-server-run"):
                pass

    asyncio.run(run())
    hosted_processor.force_flush()
    assert requests == []


def test_instrumentation_failure_does_not_report_success(monkeypatch) -> None:
    monkeypatch.setattr(instrument, "_genai_instrumented", False)
    monkeypatch.setattr(
        OpenAIAgentsInstrumentor, "_check_dependency_conflicts",
        lambda self: "simulated dependency conflict",
    )
    with pytest.raises(RuntimeError, match="failed to install"):
        instrument.instrument_genai(NoOpTracerProvider())
    assert instrument._genai_instrumented is False
