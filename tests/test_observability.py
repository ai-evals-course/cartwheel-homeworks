"""Authentication tests for the Homework 2 endpoints.

Everything here runs offline: no Langfuse, no Docker, no model provider key.
The `world` fixture (tests/conftest.py) seeds a temp database and points the
agent at it, so create_session can look up real users without touching data/.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import app as server_app


@pytest.fixture(autouse=True)
def _clear_sessions() -> None:
    server_app._SESSIONS.clear()
    yield
    server_app._SESSIONS.clear()


def test_create_session_rejects_role_mismatch(world: dict) -> None:
    # User 1 is a shopper in the seeded data; claiming "merchant" must fail.
    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(server_app.SessionCreate(user_id=1, role="merchant"))
    assert exc_info.value.status_code == 403


def test_token_cannot_authorize_a_different_session(world: dict) -> None:
    first = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))
    second = server_app.create_session(server_app.SessionCreate(user_id=2, role="shopper"))

    with pytest.raises(HTTPException) as exc_info:
        server_app._authorize(second["session_id"], f"Bearer {first['token']}")
    assert exc_info.value.status_code == 403
