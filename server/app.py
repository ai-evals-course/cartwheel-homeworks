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

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from agents import Runner, SQLiteSession
from fastapi import FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel

from agent import db
from agent.agent import build_agent, prompt_version
from agent.auth import ROLES, AuthContext
from agent.config import REPO_ROOT, db_path
from observability.instrument import load_env, setup_tracing

MAX_TURNS = 12  # cap runaway loops; keeps conversations bounded
SESSIONS_DB = REPO_ROOT / ".sessions.db"

_tracer = trace.get_tracer("cartwheel.server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_env()
    setup_tracing()  # no-op with a warning if LANGFUSE_PUBLIC_KEY is unset
    yield


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
    raise NotImplementedError("HW2: implement POST /sessions")


def _authorize(session_id: str, authorization: str | None) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = verify_token(authorization.removeprefix("Bearer "))
    if payload is None:
        raise HTTPException(status_code=401, detail="bad token signature")
    if payload.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="token is for another session")
    if session_id not in _SESSIONS:
        raise HTTPException(status_code=404, detail="unknown session (server restarted?)")
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
    raise NotImplementedError("HW2: implement the traced message endpoint")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "db_exists": db_path().exists(),
        "active_sessions": len(_SESSIONS),
    }
