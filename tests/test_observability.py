"""Offline authentication tests for the Homework 2 endpoint."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import app as server_app


def test_create_session_rejects_claimed_role_mismatch(
    world: dict, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(server_app, "_SESSIONS", {})
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")

    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(
            server_app.SessionCreate(user_id=1, role="merchant")
        )

    assert exc_info.value.status_code == 403


def test_token_for_one_session_cannot_authorize_another(
    world: dict, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(server_app, "_SESSIONS", {})
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")

    first = server_app.create_session(
        server_app.SessionCreate(user_id=1, role="shopper")
    )
    second = server_app.create_session(
        server_app.SessionCreate(user_id=2, role="shopper")
    )

    with pytest.raises(HTTPException) as exc_info:
        server_app._authorize(
            second["session_id"], f"Bearer {first['token']}"
        )

    assert exc_info.value.status_code == 403
