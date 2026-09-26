"""Homework 2: authentication tests for the session and message endpoints.

Offline only — no Langfuse, Docker, or model provider key required.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import app as server_app


@pytest.fixture(autouse=True)
def _clear_sessions():
    server_app._SESSIONS.clear()
    yield
    server_app._SESSIONS.clear()


def test_create_session_rejects_role_mismatch(world: dict) -> None:
    """User 9002 is a merchant in the seeded data; claiming shopper must fail."""
    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(server_app.SessionCreate(user_id=9002, role="shopper"))
    assert exc_info.value.status_code == 403


def test_token_for_one_session_cannot_authorize_another(world: dict) -> None:
    session_a = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))
    session_b = server_app.create_session(server_app.SessionCreate(user_id=9501, role="support"))

    with pytest.raises(HTTPException) as exc_info:
        server_app._authorize(session_b["session_id"], f"Bearer {session_a['token']}")
    assert exc_info.value.status_code == 403
