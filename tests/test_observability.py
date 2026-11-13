from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from fastapi import HTTPException
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.auth import AuthContext
from observability.instrument import record_tool_result


@pytest.fixture
def server_app():
    from server import app

    app._SESSIONS.clear()
    yield app
    app._SESSIONS.clear()


@pytest.fixture
def message_trace(server_app, monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(server_app, "_tracer", provider.get_tracer("test.server"))
    yield exporter
    provider.shutdown()


@pytest.fixture
def stub_runner(server_app, monkeypatch):
    calls = []

    async def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(final_output="The final reply.")

    monkeypatch.setattr(server_app.Runner, "run", run)
    return calls


@pytest.fixture
def tool_tracer():
    provider = TracerProvider()
    yield provider.get_tracer("test.tool")
    provider.shutdown()


def _authorized_session(server_app, session_id="test-session"):
    context = AuthContext(user_id=1, role="shopper", store_id=None)
    server_app._SESSIONS[session_id] = (context, object())
    token = server_app.create_token(
        {
            "session_id": session_id,
            "user_id": context.user_id,
            "role": context.role,
            "store_id": context.store_id,
            "issued_at": 1,
        }
    )
    return session_id, f"Bearer {token}", context


def test_create_session_rejects_role_that_differs_from_database(server_app, world):
    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(server_app.SessionCreate(user_id=1, role="merchant"))

    assert exc_info.value.status_code == 403


def test_post_message_captures_content_and_identity_when_enabled(
    server_app, monkeypatch, message_trace, stub_runner
):
    monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "true")
    session_id, authorization, context = _authorized_session(server_app)
    monkeypatch.setattr(server_app, "build_agent", lambda ctx, model=None: "stub-agent")

    response = asyncio.run(
        server_app.post_message(
            session_id,
            server_app.MessageIn(message="Where is my order?", scenario_id="scenario-7"),
            authorization,
        )
    )

    assert response == {
        "session_id": session_id,
        "reply": "The final reply.",
        "prompt_version": server_app.prompt_version(),
    }
    assert len(stub_runner) == 1
    spans = message_trace.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "cartwheel.session_message"
    assert span.attributes["cartwheel.session_id"] == session_id
    assert span.attributes["cartwheel.user_role"] == context.role
    assert span.attributes["cartwheel.user_id"] == str(context.user_id)
    assert span.attributes["cartwheel.prompt_version"] == server_app.prompt_version()
    assert span.attributes["cartwheel.scenario_id"] == "scenario-7"
    assert span.attributes["gen_ai.input.messages"] == json.dumps(
        [{"role": "user", "parts": [{"type": "text", "content": "Where is my order?"}]}]
    )
    assert span.attributes["gen_ai.output.messages"] == json.dumps(
        [{"role": "assistant", "parts": [{"type": "text", "content": "The final reply."}]}]
    )


@pytest.mark.parametrize("capture", ["false", None])
def test_post_message_omits_content_when_capture_disabled(
    server_app, monkeypatch, message_trace, stub_runner, capture
):
    if capture is None:
        monkeypatch.delenv("TRACELOOP_TRACE_CONTENT", raising=False)
    else:
        monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", capture)
    session_id, authorization, _ = _authorized_session(server_app)
    monkeypatch.setattr(server_app, "build_agent", lambda ctx, model=None: "stub-agent")

    response = asyncio.run(
        server_app.post_message(
            session_id,
            server_app.MessageIn(message="Where is my order?"),
            authorization,
        )
    )

    assert response["reply"] == "The final reply."
    span = message_trace.get_finished_spans()[0]
    assert "gen_ai.input.messages" not in span.attributes
    assert "gen_ai.output.messages" not in span.attributes
    assert "cartwheel.scenario_id" not in span.attributes


def test_post_message_rejects_unauthorized_token_before_running_agent(
    server_app, monkeypatch, stub_runner
):
    session_id, _, _ = _authorized_session(server_app)
    build_calls = []
    monkeypatch.setattr(
        server_app,
        "build_agent",
        lambda ctx, model=None: build_calls.append((ctx, model)),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            server_app.post_message(
                session_id,
                server_app.MessageIn(message="Where is my order?"),
                "Bearer unauthorized",
            )
        )

    assert exc_info.value.status_code == 401
    assert stub_runner == []
    assert build_calls == []


def test_create_session_rejects_unsupported_role(server_app, world):
    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(server_app.SessionCreate(user_id=1, role="admin"))

    assert exc_info.value.status_code == 400


def test_create_session_rejects_unknown_user(server_app, world):
    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(
            server_app.SessionCreate(user_id=999_999, role="shopper")
        )

    assert exc_info.value.status_code == 404


def test_session_token_cannot_authorize_another_session(server_app, world):
    from agent.auth import AuthContext

    first = server_app.create_session(
        server_app.SessionCreate(user_id=1, role="shopper")
    )
    second = server_app.create_session(
        server_app.SessionCreate(user_id=2, role="shopper")
    )

    context, session = server_app._SESSIONS[first["session_id"]]
    assert context == AuthContext(user_id=1, role="shopper", store_id=None)
    assert session is not None
    payload = server_app.verify_token(first["token"])
    assert payload is not None
    assert payload["session_id"] == first["session_id"]
    assert payload["user_id"] == 1
    assert payload["role"] == "shopper"
    assert payload["store_id"] is None
    assert isinstance(payload["issued_at"], int)

    with pytest.raises(HTTPException) as exc_info:
        server_app._authorize(
            second["session_id"], f"Bearer {first['token']}"
        )

    assert exc_info.value.status_code == 403


def test_record_tool_result_records_shopper_identity(tool_tracer):
    context = AuthContext(user_id=37, role="shopper")

    with tool_tracer.start_as_current_span("tool") as span:
        record_tool_result(context, {"ok": True})

        assert span.attributes["cartwheel.user_role"] == "shopper"
        assert span.attributes["cartwheel.user_id"] == "37"
        assert "cartwheel.store_id" not in span.attributes


def test_record_tool_result_records_merchant_identity_with_string_store_id(tool_tracer):
    context = AuthContext(user_id=82, role="merchant", store_id=901)

    with tool_tracer.start_as_current_span("tool") as span:
        record_tool_result(context, {"ok": True})

        assert span.attributes["cartwheel.user_role"] == "merchant"
        assert span.attributes["cartwheel.user_id"] == "82"
        assert span.attributes["cartwheel.store_id"] == "901"
        assert isinstance(span.attributes["cartwheel.store_id"], str)


def test_record_tool_result_records_allowed_decision_without_reason(tool_tracer):
    context = AuthContext(user_id=37, role="shopper")

    with tool_tracer.start_as_current_span("tool") as span:
        record_tool_result(context, {"ok": True})

        assert span.attributes["cartwheel.permission_denied"] is False
        assert "cartwheel.permission_denied.reason" not in span.attributes


def test_record_tool_result_records_denial_reason(tool_tracer):
    context = AuthContext(user_id=37, role="shopper")

    with tool_tracer.start_as_current_span("tool") as span:
        record_tool_result(
            context,
            {"ok": False, "error": "permission_denied", "reason": "not your order"},
        )

        assert span.attributes["cartwheel.permission_denied"] is True
        assert span.attributes["cartwheel.permission_denied.reason"] == "not your order"


def test_record_tool_result_defaults_missing_denial_reason_to_empty_string(tool_tracer):
    context = AuthContext(user_id=37, role="shopper")

    with tool_tracer.start_as_current_span("tool") as span:
        record_tool_result(context, {"ok": False, "error": "permission_denied"})

        assert span.attributes["cartwheel.permission_denied"] is True
        assert span.attributes["cartwheel.permission_denied.reason"] == ""


def test_record_tool_result_does_not_set_attributes_on_non_recording_span(monkeypatch):
    class NonRecordingSpan:
        def __init__(self):
            self.attributes = []

        def is_recording(self):
            return False

        def set_attribute(self, name, value):
            self.attributes.append((name, value))

    span = NonRecordingSpan()
    monkeypatch.setattr(trace, "get_current_span", lambda: span)

    record_tool_result(AuthContext(user_id=37, role="shopper"), {"ok": True})

    assert span.attributes == []
