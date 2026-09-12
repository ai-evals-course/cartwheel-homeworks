"""Homework 2 authentication checks. Offline: no Langfuse, Docker, or model key."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import app as server_app


def test_create_session_rejects_role_mismatch(world: dict) -> None:
    """A database merchant cannot open a session by claiming to be a shopper."""
    server_app._SESSIONS.clear()
    with pytest.raises(HTTPException) as exc:
        server_app.create_session(
            server_app.SessionCreate(user_id=9002, role="shopper")
        )
    assert exc.value.status_code == 403


def test_token_cannot_authorize_another_session(world: dict) -> None:
    """A token issued for one session must not authorize a different session."""
    server_app._SESSIONS.clear()
    first = server_app.create_session(
        server_app.SessionCreate(user_id=1, role="shopper")
    )
    second = server_app.create_session(
        server_app.SessionCreate(user_id=9002, role="merchant")
    )
    with pytest.raises(HTTPException) as exc:
        server_app._authorize(second["session_id"], f"Bearer {first['token']}")
    assert exc.value.status_code == 403
