"""Authentication tests for Homework 2 endpoints.

These tests verify that the session creation and message endpoints correctly
enforce authentication. They run offline with no external dependencies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


def test_session_creation_rejects_role_mismatch(client: TestClient, world: dict) -> None:
    """Session creation must reject a user claiming a different role.

    User 1 in the database has role 'shopper'. If they try to create a session
    claiming role 'merchant', the server should reject with HTTP 403 (forbidden).
    This prevents privilege escalation through false claims in the request.
    """
    # User 1 is a shopper; try to claim merchant role
    response = client.post(
        "/sessions",
        json={"user_id": 1, "role": "merchant"},
    )

    # Should get 403 Forbidden because the claimed role doesn't match the database
    assert response.status_code == 403
    assert "mismatch" in response.json()["detail"].lower()


def test_token_locked_to_session(client: TestClient, world: dict) -> None:
    """A token issued for one session cannot authorize a different session.

    Create two sessions (A and B), then try to use session A's token to access
    session B's message endpoint. The server should reject with HTTP 403 because
    the token was issued for a different session.
    """
    # Create session A for user 1
    response_a = client.post(
        "/sessions",
        json={"user_id": 1, "role": "shopper"},
    )
    assert response_a.status_code == 200
    session_a = response_a.json()["session_id"]
    token_a = response_a.json()["token"]

    # Create session B for user 9002 (a merchant)
    response_b = client.post(
        "/sessions",
        json={"user_id": 9002, "role": "merchant"},
    )
    assert response_b.status_code == 200
    session_b = response_b.json()["session_id"]
    # (don't use token_b; we'll try token_a instead)

    # Try to use token_a (issued for session A) on session B's endpoint
    response = client.post(
        f"/sessions/{session_b}/messages",
        json={"message": "Show my recent orders."},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # Should get 403 Forbidden because the token is for a different session
    assert response.status_code == 403
    assert "another session" in response.json()["detail"].lower()
