"""Workshop mirroring must leave existing telemetry and agent behavior intact."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from opentelemetry import trace

from observability import workshop


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    clear = workshop.get_client.cache_clear
    clear()
    monkeypatch.delenv("RAINDROP_LOCAL_DEBUGGER", raising=False)
    yield
    clear()


def test_disabled_without_explicit_local_destination():
    assert workshop.get_client() is None


def test_existing_provider_keeps_exporting_and_workshop_receives_spans(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    provider = TracerProvider()
    existing, mirror = InMemorySpanExporter(), InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(existing))
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(workshop, "_span_processor", None, raising=False)
    monkeypatch.setenv("RAINDROP_LOCAL_DEBUGGER", "http://localhost:5899/v1/")
    factory = Mock(return_value=mirror)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", factory)
    try:
        assert workshop.setup_span_export() is True
        assert workshop.setup_span_export() is True
        with provider.get_tracer("cartwheel.test").start_as_current_span("tool.get_order"):
            pass
        provider.force_flush()
        assert [s.name for s in existing.get_finished_spans()] == ["tool.get_order"]
        assert [s.name for s in mirror.get_finished_spans()] == ["tool.get_order"]
        assert trace.get_tracer_provider() is provider
        factory.assert_called_once()
        assert factory.call_args.kwargs["endpoint"] == "http://localhost:5899/v1/traces"
        assert "Authorization" not in factory.call_args.kwargs["headers"]
    finally:
        provider.shutdown()


def test_span_export_disabled_without_destination_or_owned_provider(monkeypatch):
    monkeypatch.setattr(workshop, "_span_processor", None, raising=False)
    assert workshop.setup_span_export() is False
    monkeypatch.setenv("RAINDROP_LOCAL_DEBUGGER", "http://localhost:5899/v1/")
    monkeypatch.setattr(trace, "get_tracer_provider", trace.ProxyTracerProvider)
    assert workshop.setup_span_export() is False


def test_local_client_does_not_install_another_otel_provider(monkeypatch):
    import raindrop
    factory = Mock(return_value=Mock())
    monkeypatch.setattr(raindrop, "Raindrop", factory)
    monkeypatch.setenv("RAINDROP_LOCAL_DEBUGGER", "http://localhost:5899/v1/")
    provider = trace.get_tracer_provider()
    assert workshop.get_client() is workshop.get_client()
    factory.assert_called_once_with(api_key=None, local_workshop_url="http://localhost:5899/v1/",
                                    tracing_enabled=False, auto_instrument=False)
    assert trace.get_tracer_provider() is provider


def test_turn_records_input_reply_and_session_metadata(monkeypatch):
    client = Mock()
    monkeypatch.setattr(workshop, "get_client", lambda: client)
    monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "true")
    ctx = SimpleNamespace(user_id=1, role="shopper")
    interaction = workshop.begin_turn(ctx, "session-a", "Help", "version-a", "scenario-a", "gpt-4o-mini")
    workshop.finish_turn(interaction, "Done")
    kwargs = client.begin.call_args.kwargs
    assert kwargs["input"] == "Help"
    assert kwargs["convo_id"] == "session-a"
    assert kwargs["properties"]["cartwheel.scenario_id"] == "scenario-a"
    client.begin.return_value.finish.assert_called_once_with(output="Done")


def test_content_opt_out_and_export_errors_do_not_break_agent(monkeypatch):
    client = Mock()
    monkeypatch.setattr(workshop, "get_client", lambda: client)
    monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "false")
    ctx = SimpleNamespace(user_id=1, role="shopper")
    interaction = workshop.begin_turn(ctx, "s", "Private", "v", None, "gpt-4o-mini")
    workshop.finish_turn(interaction, "Private reply")
    assert client.begin.call_args.kwargs["input"] is None
    interaction.finish.assert_called_once_with(output=None)
    client.begin.side_effect = RuntimeError("offline")
    assert workshop.begin_turn(ctx, "s", "Help", "v", None, "gpt-4o-mini") is None
    interaction.finish.side_effect = RuntimeError("offline")
    workshop.finish_turn(interaction, "Reply")


@pytest.mark.parametrize("fails", [False, True])
def test_message_endpoint_records_reply_or_error_without_changing_runner_arguments(monkeypatch, fails):
    import asyncio
    from server import app as server
    from agent.auth import AuthContext
    ctx = AuthContext(user_id=1, role="shopper")
    session, agent = object(), object()
    monkeypatch.setattr(server, "_authorize", lambda *_: ctx)
    monkeypatch.setitem(server._SESSIONS, "test-session", (ctx, session))
    monkeypatch.setattr(server.agent, "build_agent", lambda *_args, **_kwargs: agent)
    begin, finish = Mock(), Mock()
    monkeypatch.setattr(workshop, "begin_turn", begin)
    monkeypatch.setattr(workshop, "finish_turn", finish)

    async def run(actual_agent, message, **kwargs):
        assert actual_agent is agent
        assert message == "What is the return window?"
        assert kwargs == {"session": session, "context": ctx, "max_turns": server.MAX_TURNS}
        if fails:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(final_output="30 days")

    monkeypatch.setattr(server.Runner, "run", run)
    body = server.MessageIn(message="What is the return window?", model="gpt-4o-mini")
    if fails:
        with pytest.raises(RuntimeError, match="model unavailable"):
            asyncio.run(server.post_message("test-session", body, "test-token"))
        finish.assert_called_once_with(begin.return_value, "Error: RuntimeError")
    else:
        result = asyncio.run(server.post_message("test-session", body, "test-token"))
        assert result["reply"] == "30 days"
        finish.assert_called_once_with(begin.return_value, "30 days")
