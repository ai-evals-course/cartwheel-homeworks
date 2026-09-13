"""Homework 2 authentication tests (offline, no Langfuse or model key)."""

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_create_session_rejects_role_mismatch() -> None:
    from server import app as server_app

    server_app._SESSIONS.clear()

    response = client.post(
        "/sessions",
        json={"user_id": 1, "role": "merchant"},
    )

    assert response.status_code == 403


def test_token_cannot_authorize_different_session() -> None:
    from server import app as server_app

    server_app._SESSIONS.clear()

    session_a = client.post(
        "/sessions",
        json={"user_id": 1, "role": "shopper"},
    ).json()
    session_b = client.post(
        "/sessions",
        json={"user_id": 1, "role": "shopper"},
    ).json()

    response = client.post(
        f"/sessions/{session_b['session_id']}/messages",
        json={"message": "hello"},
        headers={"Authorization": f"Bearer {session_a['token']}"},
    )

    assert response.status_code == 403
