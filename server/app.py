"""The Cartwheel endpoint, with the session routes completed in Homework 2.

A thin FastAPI wrapper with three routes (Lecture 2.3):

  - POST /sessions            binds a user + role, returns a signed dev token
  - POST /sessions/{id}/messages   one conversation turn
  - GET  /health              liveness

Why an endpoint at all: one choke point to authenticate, log, sample,
rate-limit, and replay. Modules 3 and 4 need a surface to monitor and attack.

The token is dev-only auth: a base64 JSON payload signed with an HMAC over a
shared secret (CARTWHEEL_DEV_SECRET). It is not real auth; the *shape* (a
server-issued credential carrying user id + role that tools trust) is what
Module 4 attacks. In production you would stream responses and assemble the
final message in middleware; this server does not stream.

Run with:
    uv run uvicorn server.app:app --port 8010
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from agents import Runner, SQLiteSession
from fastapi import FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel

from agent import agent, db
from agent.auth import ROLES, AuthContext
from agent.config import REPO_ROOT, db_path
from observability.instrument import load_env, setup_tracing
from observability import workshop

MAX_TURNS = 12  # cap runaway loops; keeps conversations bounded
SESSIONS_DB = REPO_ROOT / ".sessions.db"

_tracer = trace.get_tracer("cartwheel.server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_env()
    setup_tracing()  # no-op with a warning if LANGFUSE_PUBLIC_KEY is unset
    workshop.setup_span_export()
    try:
        yield
    finally:
        await asyncio.to_thread(workshop.shutdown)


app = FastAPI(title="Cartwheel support agent", lifespan=lifespan)

# session_id -> (AuthContext, SQLiteSession). In-memory on purpose: the trace
# store is the durable record, not this dict.
_SESSIONS: dict[str, tuple[AuthContext, SQLiteSession]] = {}


# ---------------------------------------------------------------------------
# Signed dev token: base64url(JSON payload) + "." + HMAC-SHA256 signature.
# ---------------------------------------------------------------------------


def _secret() -> bytes:
    return os.environ.get("CARTWHEEL_DEV_SECRET", "cartwheel-dev-secret").encode()


def create_token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode()
    ).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> dict[str, Any] | None:
    """Return the payload if the signature checks out, else None."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(body.encode()))
    except (binascii.Error, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    user_id: int
    role: str


class MessageIn(BaseModel):
    message: str
    model: str | None = None
    # Set by the scenario runner (Lecture 3) so a trace links back to its
    # ground truth. Manual sessions leave it null.
    scenario_id: str | None = None


@app.post("/sessions")
def create_session(body: SessionCreate) -> dict[str, Any]:
    """Bind a verified database user to a new server-side session.

    Validate the requested role, load the user from the database, and reject
    a request whose claimed role differs from the stored role. Create an
    AuthContext and SQLiteSession, save them in _SESSIONS, then return the
    session id and a signed token. The token payload must contain session_id,
    user_id, role, store_id, and issued_at.
    """
    ### YOUR CODE HERE (HW2)
    import time
    import uuid

    with db.connection() as conn:
        user = db.get_user(conn, body.user_id)

        if body.role not in ROLES:
            raise HTTPException(status_code=400, detail="unknown role")
        if user is None:
            raise HTTPException(status_code=404, detail="unknown user")

        if user.role != body.role:
            raise HTTPException(status_code=403, detail="role does not match user")

        ctx = AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)

        session_id = str(uuid.uuid4())
        session = SQLiteSession(session_id, str(SESSIONS_DB))
        _SESSIONS[session_id] = (ctx, session)
        token = create_token(
            {
                "session_id": session_id,
                "user_id": ctx.user_id,
                "role": ctx.role,
                "store_id": ctx.store_id,
                "issued_at": time.time(),
            }
        )
        return {"session_id": session_id, "token": token}


def _authorize(session_id: str, authorization: str | None) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = verify_token(authorization.removeprefix("Bearer "))
    if payload is None:
        raise HTTPException(status_code=401, detail="bad token signature")
    if payload.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="token is for another session")
    if session_id not in _SESSIONS:
        raise HTTPException(
            status_code=404, detail="unknown session (server restarted?)"
        )
    return _SESSIONS[session_id][0]


@app.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageIn,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run one authenticated conversation turn inside a root trace span.

    Authorize the token, recover the server-side session, and build the agent
    for the authenticated context. Hash only the system prompt template.
    The cartwheel.session_message span must record the session id, user role,
    user id, prompt version, and a nonempty scenario id when one is supplied. Run the
    agent inside that span, then return the session id, final reply, and
    prompt version.
    When TRACELOOP_TRACE_CONTENT is true, record gen_ai.input.messages and
    gen_ai.output.messages on the root span as JSON arrays of OTel GenAI
    messages with role and parts fields.
    """
    ### YOUR CODE HERE (HW2)

    ctx = _authorize(session_id, authorization)
    _, session = _SESSIONS[session_id]
    support_agent = agent.build_agent(ctx, model=body.model)
    version = agent.prompt_version()

    with _tracer.start_as_current_span("cartwheel.session_message") as span:
        span.set_attribute("cartwheel.session_id", session_id)
        span.set_attribute("cartwheel.user_role", ctx.role)
        span.set_attribute("cartwheel.user_id", str(ctx.user_id))
        span.set_attribute("cartwheel.prompt_version", version)

        if body.scenario_id:
            span.set_attribute("cartwheel.scenario_id", body.scenario_id)

        capture_content = (
            os.environ.get("TRACELOOP_TRACE_CONTENT", "false").lower() == "true"
        )

        input_messages = [
            {"role": "user", "parts": [{"type": "text", "content": body.message}]}
        ]
        if capture_content:
            span.set_attribute("gen_ai.input.messages", json.dumps(input_messages))

        interaction = workshop.begin_turn(
            ctx, session_id, body.message, version, body.scenario_id,
            body.model or os.environ.get("CARTWHEEL_MODEL") or agent.DEFAULT_MODEL,
        )
        try:
            result = await Runner.run(
                support_agent,
                body.message,
                session=session,
                context=ctx,
                max_turns=MAX_TURNS,
            )
        except BaseException as exc:
            workshop.finish_turn(interaction, "Error: " + type(exc).__name__)
            raise
        reply = str(result.final_output)
        workshop.finish_turn(interaction, reply)

        output_messages = [
            {"role": "assistant", "parts": [{"type": "text", "content": reply}]}
        ]
        if capture_content:
            span.set_attribute("gen_ai.output.messages", json.dumps(output_messages))

    return {
        "session_id": session_id,
        "reply": reply,
        "prompt_version": version,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "db_exists": db_path().exists(),
        "active_sessions": len(_SESSIONS),
    }
