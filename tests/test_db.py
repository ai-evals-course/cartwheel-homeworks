"""Connection cleanup and unchanged SQLite write behavior; no model calls."""

from pathlib import Path
import sqlite3

import pytest

from agent import db, review
from agent.agent import escalate_to_human_logic, get_order_logic, issue_refund_logic
from agent.auth import AuthContext
from agent.cli import resolve_auth
from agent.review import resolve_support, review_queue


@pytest.mark.parametrize("exit_kind", ["normal", "return", "error"])
def test_connection_closes_on_every_exit(world_copy: Path, exit_kind: str) -> None:
    opened = []
    error = RuntimeError("original error")

    def run() -> None:
        with db.connection() as conn:
            opened.append(conn)
            assert conn.execute("SELECT 1 AS value").fetchone()["value"] == 1
            if exit_kind == "return":
                return
            if exit_kind == "error":
                raise error

    if exit_kind == "error":
        with pytest.raises(RuntimeError) as caught:
            run()
        assert caught.value is error
    else:
        run()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize("raise_error", [False, True])
def test_uncommitted_writes_are_not_committed_on_exit(world_copy: Path, raise_error: bool) -> None:
    with db.connection() as conn:
        before = db.get_order(conn, 4127).status
    try:
        with db.connection() as conn:
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = 4127")
            if raise_error:
                raise RuntimeError("abort")
    except RuntimeError:
        pass
    with db.connection() as conn:
        assert db.get_order(conn, 4127).status == before


def test_existing_helper_commits_survive_later_error(world_copy: Path) -> None:
    with pytest.raises(RuntimeError, match="later failure"):
        with db.connection() as conn:
            db.set_order_status(conn, 4127, "cancelled")
            raise RuntimeError("later failure")
    with db.connection() as conn:
        assert db.get_order(conn, 4127).status == "cancelled"


def test_explicit_path_overrides_environment(world_copy: Path, monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("CARTWHEEL_DB", str(missing))
    with db.connection(world_copy) as conn:
        assert db.get_order(conn, 4127).id == 4127
    with pytest.raises(FileNotFoundError, match="seed.generate"):
        with db.connection():
            pytest.fail("missing database must fail before entering the block")
    assert not missing.exists()


@pytest.mark.parametrize("operation", ["lookup", "denied", "refund", "escalate", "cli", "support", "review"])
def test_supplied_callers_close_connections(world_copy: Path, monkeypatch, operation: str) -> None:
    opened = []
    original_connect = db.connect

    def tracked_connect(path=None):
        conn = original_connect(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db, "connect", tracked_connect)
    shopper = AuthContext(user_id=1, role="shopper")
    if operation == "lookup":
        assert get_order_logic(shopper, 4127)["ok"]
    elif operation == "denied":
        result = get_order_logic(AuthContext(user_id=9002, role="merchant", store_id=2), 4127)
        assert result["error"] == "permission_denied"
    elif operation == "refund":
        assert issue_refund_logic(shopper, 4127, 84, "test")["status"] == "auto_approved"
    elif operation == "escalate":
        assert escalate_to_human_logic(shopper, "account help", "student needs assistance")["ok"]
    elif operation == "cli":
        assert resolve_auth("shopper", 1).user_id == 1
    elif operation == "support":
        assert resolve_support(9501).role == "support"
    else:
        # Fail in supplied setup, without requiring the HW8 student seam to stay unfinished.
        def setup_failure(conn):
            raise RuntimeError("review setup failed")
        monkeypatch.setattr(review, "ensure_approvals_table", setup_failure)
        with pytest.raises(RuntimeError, match="review setup failed"):
            review_queue(AuthContext(user_id=9501, role="support"))
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
