"""Review data must preserve provenance and human decisions (offline)."""
import copy
import pytest

from analysis.review_app.data import build_turn, group_sessions, ReviewStore


def trace(tid, session="session-a", scenario="same-scenario", timestamp="2026-01-01"):
    return {"id": tid, "timestamp": timestamp, "sessionId": None,
            "metadata": {"attributes": {"cartwheel.session_id": session,
                "cartwheel.scenario_id": scenario, "cartwheel.user_role": "shopper"}},
            "input": [{"role": "user", "parts": [{"type": "text", "content": "Help"}]}],
            "output": [{"role": "assistant", "parts": [{"type": "text", "content": "Done"}]}]}


def test_sessions_use_nested_identity_and_never_merge_scenario_repeats():
    groups = group_sessions([trace("b", timestamp="2026-01-02"), trace("c", "other"), trace("a")])
    group = next(g for g in groups if g["id"] == "session-a")
    assert [t["id"] for t in group["traces"]] == ["a", "b"]
    assert len(groups) == 2
    assert len(group_sessions([trace("x", None), trace("y", None)])) == 2


def test_turn_sorts_observations_and_does_not_repeat_history_or_final():
    raw = trace("a")
    raw["observations"] = [
        {"id": "last", "type": "GENERATION", "startTime": "3", "input": {"messages": [{"role": "user", "parts": [{"type": "text", "content": "OLD"}]}]}, "output": raw["output"]},
        {"id": "tool", "type": "TOOL", "name": "get_order", "startTime": "2", "input": {"order_id": 1}, "output": {"ok": False, "error": "permission_denied"}},
        {"id": "gen", "type": "GENERATION", "startTime": "1", "output": [{"role": "assistant", "parts": [{"type": "tool_call", "id": "call-1", "name": "get_order", "arguments": {"order_id": 1}}]}]},
    ]
    original = copy.deepcopy(raw)
    turn = build_turn(raw)
    assert [b["role"] for b in turn["blocks"]] == ["user", "tool", "assistant"]
    assert turn["blocks"][1]["call_id"] == "call-1"
    assert turn["blocks"][1]["result"]["error"] == "permission_denied"
    assert "OLD" not in str(turn["blocks"])
    assert raw == original


def test_ambiguous_tool_match_is_visible():
    raw = trace("a")
    raw["observations"] = [{"id": "g", "type": "GENERATION", "startTime": "1", "output": [{"parts": [
        {"type": "tool_call", "id": "c1", "name": "get_order", "arguments": {}},
        {"type": "tool_call", "id": "c2", "name": "get_order", "arguments": {}}]}]},
        {"id": "t", "type": "TOOL", "name": "get_order", "startTime": "2", "input": {}, "output": {"ok": True}}]
    assert next(b for b in build_turn(raw)["blocks"] if b["role"] == "tool")["match"] == "ambiguous"


def test_missing_capture_is_not_an_empty_successful_conversation():
    turn = build_turn({"id": "missing", "observations": []})
    assert turn["warnings"]


def test_note_and_review_are_separate_and_survive_restart(tmp_path):
    store = ReviewStore(tmp_path, {"a"})
    store.apply({"action": "note", "trace_id": "a", "id": "n", "note": "First issue", "anchor": {"block_id": "b", "field": "text", "quote": "Done", "start": 0, "end": 4}})
    assert store.read()["reviews"] == {}
    store.apply({"action": "review", "trace_id": "a", "status": "first_failure"})
    assert ReviewStore(tmp_path, {"a"}).read()["reviews"]["a"]["status"] == "first_failure"
    assert store.read()["annotations"][0]["anchor"]["quote"] == "Done"


def test_invalid_label_never_calls_langfuse_and_pending_can_retry(tmp_path):
    writes = []
    def fail(*args):
        writes.append(args)
        raise RuntimeError("network down")
    store = ReviewStore(tmp_path, {"a"}, sync=fail)
    store.apply({"action": "mode", "id": "claim", "definition": "Unsupported claim", "final": True})
    with pytest.raises(ValueError):
        store.apply({"action": "label", "trace_id": "a", "mode": "claim", "value": 2})
    assert not writes
    store.apply({"action": "label", "trace_id": "a", "mode": "claim", "value": 0})
    assert store.read()["labels"]["a:claim"]["sync"] == "pending"
    assert store.read()["labels"]["a:claim"]["value"] == 0
    store.sync = lambda *args: writes.append(args)
    store.apply({"action": "retry"})
    assert store.read()["labels"]["a:claim"]["sync"] == "synced"
    assert writes[0] == writes[1]


def test_suggestion_requires_explicit_decision_and_does_not_label(tmp_path):
    from analysis.helpers._state import write_json
    write_json(tmp_path / "suggestions.json", [{"id": "s", "trace_id": "a", "note": "Maybe wrong", "quote": "Done"}])
    store = ReviewStore(tmp_path, {"a"})
    assert store.read()["annotations"] == []
    store.apply({"action": "suggestion", "id": "s", "decision": "accept"})
    store.apply({"action": "suggestion", "id": "s", "decision": "accept"})
    assert len(store.read()["annotations"]) == 1
    assert store.read()["labels"] == {}
    with pytest.raises(ValueError):
        store.apply({"action": "review", "trace_id": "unknown", "status": "no_failure"})


def test_stale_revision_does_not_overwrite_another_browser(tmp_path):
    store = ReviewStore(tmp_path, {"a"})
    revision = store.read()["revision"]
    store.apply({"action": "review", "trace_id": "a", "status": "no_failure", "revision": revision})
    with pytest.raises(ValueError, match="changed"):
        store.apply({"action": "review", "trace_id": "a", "status": "unreviewed", "revision": revision})


def test_score_retries_use_same_id_and_confirm_zero(monkeypatch):
    from types import SimpleNamespace
    from analysis.review_app.data import sync_label
    writes = []
    def create(*, request):
        writes.append(request)
    fake = SimpleNamespace(api=SimpleNamespace(
        score=SimpleNamespace(create=create),
        score_v_2=SimpleNamespace(get_by_id=lambda sid: SimpleNamespace(value=0, trace_id="a" * 32))))
    monkeypatch.setattr("analysis.helpers.langfuse_io._client", lambda: fake)
    sync_label("a" * 32, "claim", 0, "Human note")
    sync_label("a" * 32, "claim", 0, "Human note")
    assert writes[0].id == writes[1].id
    assert writes[0].trace_id == "a" * 32
    assert writes[0].value == 0


def test_http_session_state_validation_and_origin_protection(tmp_path):
    import json
    import threading
    import urllib.request
    import urllib.error
    from analysis.review_app.server import ReviewServer
    server = ReviewServer(("127.0.0.1", 0), [trace("a")], tmp_path, "Test export", sync=lambda *_: None)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/api/session?id=session-a") as response:
            assert json.load(response)["turns"][0]["id"] == "a"
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        request = urllib.request.Request(base + "/api/action", data=json.dumps({
            "action": "review", "trace_id": "a", "status": "no_failure"}).encode(),
            headers={"Content-Type": "application/json", "Origin": "https://unrelated.example"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
        assert not (tmp_path / "review_app.json").exists()
        request.remove_header("Origin")
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["reviews"]["a"]["status"] == "no_failure"
        with urllib.request.urlopen(base + "/api/state") as response:
            assert json.load(response)["reviews"]["a"]["status"] == "no_failure"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_deleting_comment_keeps_other_comments_and_resets_empty_failure_review(tmp_path):
    store = ReviewStore(tmp_path, {'a', 'b'}, sync=lambda *_: None)
    store.apply({'action': 'note', 'trace_id': 'a', 'id': 'n1', 'note': 'Issue'})
    store.apply({'action': 'note', 'trace_id': 'b', 'id': 'n2', 'note': 'Another issue'})
    store.apply({'action': 'review', 'trace_id': 'a', 'status': 'first_failure'})
    result = store.apply({'action': 'delete_note', 'trace_id': 'a', 'id': 'n1'})
    assert [note['id'] for note in result['annotations']] == ['n2']
    assert result['reviews']['a']['status'] == 'unreviewed'
    with pytest.raises(ValueError):
        store.apply({'action': 'delete_note', 'trace_id': 'a', 'id': 'n2'})


def test_cannot_delete_comment_supporting_a_mode(tmp_path):
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None)
    store.apply({'action': 'note', 'trace_id': 'a', 'id': 'n1', 'note': 'Issue'})
    store.apply({'action': 'mode', 'id': 'issue', 'definition': 'An issue', 'annotation_ids': ['n1']})
    with pytest.raises(ValueError, match='supports a failure mode'):
        store.apply({'action': 'delete_note', 'trace_id': 'a', 'id': 'n1'})
    assert store.read()['annotations'][0]['id'] == 'n1'
