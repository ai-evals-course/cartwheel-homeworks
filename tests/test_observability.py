"""Homework 2, Part D: authentication tests for the session endpoints.

These test the two ways a caller could forge a boarding pass:

  1. Lying at check-in: claiming a role the database does not agree with.
  2. Using someone else's pass: presenting a token issued for another session.

Plus the two ways a pass can simply be invalid: absent, or tampered with.

Deliberately offline. No Langfuse, no Docker, no model provider key, no network.
A test that needs infrastructure gets skipped, and a skipped test protects nothing.
The endpoints are called as plain Python functions rather than over HTTP, so the
authorization logic is exercised without running a server.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.app import (
    SessionCreate,
    _SESSIONS,
    _authorize,
    create_session,
    verify_token,
)


@pytest.fixture(autouse=True)
def clean_sessions() -> None:
    """Each test starts with an empty session store."""
    _SESSIONS.clear()


# ---------------------------------------------------------------------------
# 1. Session creation rejects a claimed role the database does not agree with.
# ---------------------------------------------------------------------------


def test_create_session_rejects_role_mismatch(world: dict) -> None:
    """User 9002 is a merchant in the database; claiming shopper must fail.

    The request body is a claim, not evidence. create_session checks it against
    the stored row and refuses when they disagree.
    """
    with pytest.raises(HTTPException) as exc:
        create_session(SessionCreate(user_id=9002, role="shopper"))
    assert exc.value.status_code == 403
    assert not _SESSIONS, "a rejected check-in must not leave a session behind"


def test_create_session_binds_the_stored_identity(world: dict) -> None:
    """The token carries the database identity, not the claimed one.

    Nothing in the request mentions store 2. It appears in the token only
    because the database says user 9002 belongs to it, and can_view_order
    depends on that value being right.
    """
    response = create_session(SessionCreate(user_id=9002, role="merchant"))
    payload = verify_token(response["token"])
    assert payload is not None
    assert payload["user_id"] == 9002
    assert payload["role"] == "merchant"
    assert payload["store_id"] == 2


# ---------------------------------------------------------------------------
# 2. A token issued for one session cannot authorize another.
# ---------------------------------------------------------------------------


def test_token_from_one_session_cannot_authorize_another(world: dict) -> None:
    """Session A's token must not open session B.

    Both sessions are real and both tokens are validly signed, so the signature
    check alone would let this through. The session_id binding is what stops it.
    """
    a = create_session(SessionCreate(user_id=1, role="shopper"))
    b = create_session(SessionCreate(user_id=2, role="shopper"))

    # Sanity check first: A's token DOES open A. Without this, the assertion
    # below would also pass if _authorize rejected every token ever issued.
    ctx = _authorize(a["session_id"], f"Bearer {a['token']}")
    assert ctx.user_id == 1

    with pytest.raises(HTTPException) as exc:
        _authorize(b["session_id"], f"Bearer {a['token']}")
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# An invalid pass: absent, or tampered with.
# ---------------------------------------------------------------------------


def test_missing_token_is_rejected(world: dict) -> None:
    """No Authorization header at all is a 401, before any session lookup."""
    session = create_session(SessionCreate(user_id=1, role="shopper"))
    with pytest.raises(HTTPException) as exc:
        _authorize(session["session_id"], None)
    assert exc.value.status_code == 401


def test_tampered_token_is_rejected(world: dict) -> None:
    """Editing the payload invalidates the signature.

    The token is a base64 payload plus an HMAC over it. Changing the payload
    without the signing secret breaks the match, so a caller cannot promote
    themselves by rewriting their own user id or role.
    """
    session = create_session(SessionCreate(user_id=1, role="shopper"))
    body, signature = session["token"].rsplit(".", 1)
    forged = f"{body}x.{signature}"

    assert verify_token(forged) is None

    with pytest.raises(HTTPException) as exc:
        _authorize(session["session_id"], f"Bearer {forged}")
    assert exc.value.status_code == 401
