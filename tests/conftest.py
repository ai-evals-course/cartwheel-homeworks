"""Test fixtures. Everything runs offline with no API keys.

The session-scoped `world` fixture seeds a fresh dev-scale world into a
temp directory and points the agent at it through the CARTWHEEL_DB and
CARTWHEEL_POLICIES_DIR env vars, so tests never touch data/. Tests that
mutate the database (refunds, cancellations) use `world_copy`, which hands
each test its own copy.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from seed.generate import generate_world


class _NoOpTracingProcessor:
    """Inert stand-in for the SDK's own real hosted-export singleton.

    ``agents.tracing.setup.get_trace_provider()`` lazily creates, the first
    time anything calls it in the process, a real ``BatchTraceProcessor``
    wrapping a keyless ``BackendSpanExporter`` and registers it as the
    default global provider's processor -- this is the SDK's own global
    state, not ours, and it is never routed through our
    ``instrument.default_processor`` patch. Its background thread outlives
    whichever test triggered it, and every later ``hosted_exports`` fixture
    teardown (``tests/test_cli.py``) restores that same captured provider as
    the active one via ``set_trace_provider(previous_provider)``. Any trace
    emitted afterwards -- by any test, tracing-related or not -- gets queued
    onto that real singleton, whose timer thread then calls
    ``exporter.export()`` on its own schedule and, whenever OPENAI_API_KEY
    isn't set at that moment, logs "OPENAI_API_KEY is not set, skipping
    trace export" into whatever test (or nothing, after the session ends)
    happens to be running then. Patching the SDK's real
    ``default_processor`` to return this no-op instead means that singleton
    is never constructed, so nothing is ever there to leak.
    """

    def on_trace_start(self, trace) -> None:
        pass

    def on_trace_end(self, trace) -> None:
        pass

    def on_span_start(self, span) -> None:
        pass

    def on_span_end(self, span) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_leaked_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard every test against real credentials/global tracing state that
    leaked in from outside this test, before this test's own body runs.

    Three known, unrelated leaks motivate this, all invisible to the test
    that actually trips over them:

    - Importing litellm (e.g. via agents.extensions.models.litellm_model,
      triggered by building an agent for any non-OpenAI model) runs
      litellm's own `_dotenv.load_dotenv(override=True)` as a *module
      import* side effect. That overwrites os.environ with this repo's
      real .env values (LANGFUSE_*, etc.) once per process, on whichever
      test happens to import it first -- invisible to and unfixable by
      that test's own mocking, since it's third-party code.
    - Calling the real (unmocked) instrument.setup_openai_tracing() or
      instrument.instrument_genai() sets module-level globals
      (_openai_tracing_enabled / _genai_instrumented) directly, which
      monkeypatch cannot track or undo, so they stay flipped for every
      later test.
    - The SDK's own ``agents.tracing.processors.default_processor()``
      singleton (see ``_NoOpTracingProcessor`` above) leaks a live
      background thread across tests via ``get_trace_provider()``.

    Reset before each test, not just once at session start, because any of
    these leaks can first occur mid-session at any point.
    """
    from observability import instrument

    for key in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "CARTWHEEL_JUDGE_TRACE_SOURCE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(instrument, "_genai_instrumented", False)
    monkeypatch.setattr(instrument, "_openai_tracing_enabled", False)
    monkeypatch.setattr(
        "agents.tracing.processors.default_processor",
        lambda: _NoOpTracingProcessor(),
    )


@pytest.fixture(scope="session")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("world")
    db = root / "cartwheel.db"
    policies = root / "policies"
    generate_world(scale="dev", db_path=db, policies_dir=policies)
    os.environ["CARTWHEEL_DB"] = str(db)
    os.environ["CARTWHEEL_POLICIES_DIR"] = str(policies)
    return {"db": db, "policies": policies}


@pytest.fixture
def world_copy(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "cartwheel.db"
    shutil.copy(world["db"], db)
    monkeypatch.setenv("CARTWHEEL_DB", str(db))
    return db


@pytest.fixture
def analysis_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hand each Module 2 test its own copy of the committed demo state.

    The error-analysis helpers read and write files under
    ``analysis/state/`` (the Artifact J layout). Copying the committed demo
    state into a temp dir and pointing ``CARTWHEEL_ANALYSIS_STATE`` there
    lets the invariant tests exercise writes (freeze, label appends) without
    mutating the checked-in fixture, exactly as ``world_copy`` does for the
    database. Everything here is offline: no keys, no LLM calls.
    """
    src = Path(__file__).resolve().parent.parent / "analysis" / "state"
    dst = tmp_path / "state"
    shutil.copytree(src, dst)
    monkeypatch.setenv("CARTWHEEL_ANALYSIS_STATE", str(dst))
    return dst


@pytest.fixture
def order_search_cases(world_copy):
    """Old matches across independent user/store scopes behind 20 newer orders."""
    from agent import db

    with db.connection() as conn:
        title = "Unique Search Fixture Product"
        matching_products = {}
        ordinary_products = {}
        for store in (1, 2):
            products = db.list_products(conn, store_id=store)
            ordinary_products[store] = products[0].id
            matching_products[store] = products[1].id
            conn.execute("UPDATE products SET title = ? WHERE id = ?", (title, products[1].id))
            conn.execute(
                "UPDATE orders SET product_id = ? WHERE store_id = ?",
                (products[0].id, store),
            )
        ids = [row["id"] for row in conn.execute("SELECT id FROM orders ORDER BY id LIMIT 60")]
        matches = []
        for i, order_id in enumerate(ids):
            user = i % 2 + 1
            store = i // 2 % 2 + 1
            is_match = i < 8
            product = matching_products[store] if is_match else ordinary_products[store]
            ordered_at = "1900-01-01" if is_match else "2099-01-01"
            conn.execute(
                "UPDATE orders SET user_id = ?, store_id = ?, product_id = ?, ordered_at = ? WHERE id = ?",
                (user, store, product, ordered_at, order_id),
            )
            if is_match:
                matches.append((order_id, user, store))
        conn.commit()
        expected = {
            "shopper": [oid for oid, user, store in reversed(matches) if user == 1],
            "merchant": [oid for oid, user, store in reversed(matches) if store == 2],
            "support": [oid for oid, user, store in reversed(matches)],
        }
    return title, expected
