"""Regression checks for the review server's state directory and atomic saves."""

import importlib.util
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CARTWHEEL_ANALYSIS_STATE", str(tmp_path / "state"))
    # Load afresh because the server resolves its state directory at startup.
    source = Path(__file__).resolve().parents[1] / "analysis/server.py"
    spec = importlib.util.spec_from_file_location("review_server", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_override_includes_api_files_and_replay(server, tmp_path):
    state = tmp_path / "state"
    assert server.STATE_DIR == state
    assert all(path.parent == state for path in server.API_FILES.values())
    for path in server.API_FILES.values():
        server._write_json(path, [])
        assert json.loads(path.read_text()) == []

    canned = tmp_path / "canned.json"
    annotations = [{"id": "demo", "note": "late delivery"}]
    canned.write_text(json.dumps({"annotations": annotations}))
    server._replay_annotations(canned, interval=0)
    assert json.loads((state / "annotations.json").read_text()) == annotations


def test_concurrent_saves_use_distinct_complete_files(server, tmp_path, monkeypatch):
    path = tmp_path / "state/annotations.json"
    payloads = [{"writer": i, "note": "x" * 10000} for i in range(2)]
    ready = threading.Barrier(2)
    replace = os.replace
    temp_paths = []

    def synchronized_replace(src, dst):
        temp_paths.append(Path(src))
        # Both saves finish writing before either replaces the destination.
        ready.wait(timeout=5)
        assert json.loads(Path(src).read_text()) in payloads
        return replace(src, dst)

    monkeypatch.setattr(os, "replace", synchronized_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(server._write_json, path, payload) for payload in payloads]
        for future in futures:
            future.result(timeout=10)
    assert len(set(temp_paths)) == 2
    assert json.loads(path.read_text()) in payloads
    assert list(path.parent.iterdir()) == [path]


def test_failed_serialization_preserves_previous_file(server, tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text("[]")
    with pytest.raises(TypeError):
        server._write_json(path, {"bad": object()})
    assert path.read_text() == "[]"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_preserves_previous_file(server, tmp_path, monkeypatch):
    path = tmp_path / "annotations.json"
    path.write_text("[]")

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        server._write_json(path, {"note": "new"})
    assert path.read_text() == "[]"
    assert list(tmp_path.iterdir()) == [path]
