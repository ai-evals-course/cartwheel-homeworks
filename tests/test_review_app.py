"""Review data must preserve provenance and human decisions (offline)."""
import copy
import pytest

from analysis.review_app.data import build_turn, group_sessions, ReviewStore


def test_rejected_final_mode_cannot_receive_new_labels(tmp_path):
    from analysis.helpers._state import write_json
    write_json(tmp_path / "review_app.json", {
        "revision": 0, "annotations": [], "reviews": {}, "labels": {},
        "modes": [{"id": "issue", "definition": "Rejected failure mode",
                   "final": True, "review_status": "rejected"}], "decisions": {},
    })
    synced = []
    store = ReviewStore(tmp_path, {"a"}, sync=lambda *args: synced.append(args))
    with pytest.raises(ValueError, match="Confirm this mode"):
        store.apply({"action": "label", "trace_id": "a", "mode": "issue", "value": 1})
    assert store.read()["labels"] == {}
    assert synced == []


def test_live_reads_retry_listing_and_details_without_losing_records(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import httpx
    from analysis.review_app import server

    first_page = SimpleNamespace(data=[SimpleNamespace(id=str(i)) for i in range(100)])
    last_page = SimpleNamespace(data=[SimpleNamespace(id="100")])
    listing = Mock(side_effect=[httpx.ReadTimeout("slow"), first_page, last_page])
    failed = False

    def get(tid, **kwargs):
        nonlocal failed
        if tid == "0" and not failed:
            failed = True
            raise httpx.ReadTimeout("slow detail")
        return trace(tid, scenario=None if tid == "100" else "scenario")

    details = Mock(side_effect=get)
    monkeypatch.setattr(server, "_client", lambda: SimpleNamespace(
        api=SimpleNamespace(trace=SimpleNamespace(list=listing, get=details))))
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    records = server.load_live(timeout=60)
    assert {r["id"] for r in records} == {str(i) for i in range(100)}
    assert [call.kwargs["page"] for call in listing.call_args_list] == [1, 1, 2]
    for call in listing.call_args_list + details.call_args_list:
        assert call.kwargs["request_options"] == {"timeout_in_seconds": 60, "max_retries": 0}
    assert details.call_count == 102


def test_live_read_failure_is_bounded_and_explains_recovery(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import httpx
    from analysis.review_app import server

    listing = Mock(side_effect=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(server, "_client", lambda: SimpleNamespace(
        api=SimpleNamespace(trace=SimpleNamespace(list=listing))))
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="after 3 attempts.*--langfuse-timeout.*--source"):
        server.load_live()
    assert listing.call_count == 3


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


def test_session_dimensions_use_scenario_tuple_and_authenticated_trace_role():
    scenarios = [{"id": "same-scenario", "tuple": {"role": "merchant", "intent": "refund",
                  "order_age_days_range": "8–14", "tools_needed": "several_calls"}}]
    groups = group_sessions([trace("a"), trace("b", "other", scenario="missing")], scenarios)
    dims = next(g for g in groups if g["id"] == "session-a")["traces"][0]["dimensions"]
    assert dims == {"authenticated role": "shopper", "intent": "refund",
                    "age since placement": "8–14", "tools needed": "several_calls"}
    assert next(g for g in groups if g["id"] == "other")["traces"][0]["dimensions"] == {"authenticated role": "shopper"}


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


def test_note_marks_trace_reviewed_and_explicit_outcome_survives_restart(tmp_path):
    store = ReviewStore(tmp_path, {"a"})
    store.apply({"action": "note", "trace_id": "a", "id": "n", "note": "First issue", "anchor": {"block_id": "b", "field": "text", "quote": "Done", "start": 0, "end": 4}})
    assert store.read()["reviews"]["a"]["status"] == "reviewed"
    store.apply({"action": "review", "trace_id": "a", "status": "first_failure"})
    assert ReviewStore(tmp_path, {"a"}).read()["reviews"]["a"]["status"] == "first_failure"
    assert store.read()["annotations"][0]["anchor"]["quote"] == "Done"


def test_existing_comments_are_marked_reviewed_without_changing_assessments(tmp_path):
    from analysis.helpers._state import write_json
    state = {"revision": 3, "annotations": [
        {"id": "n1", "trace_id": "a", "note": "Observation"},
        {"id": "n2", "trace_id": "b", "note": "Another observation"}],
        "reviews": {"b": {"status": "no_failure"}}, "labels": {}, "modes": [], "decisions": {}}
    write_json(tmp_path / "review_app.json", state)
    store = ReviewStore(tmp_path, {"a", "b"})
    saved = store.read()
    assert saved["reviews"]["a"]["status"] == "reviewed"
    assert saved["reviews"]["b"]["status"] == "no_failure"
    assert saved["annotations"] == state["annotations"]
    assert saved["labels"] == {}
    assert ReviewStore(tmp_path, {"a", "b"}).read()["revision"] == saved["revision"]


def test_mark_conversation_reviewed_persists_all_turns_and_preserves_assessments(tmp_path):
    store = ReviewStore(tmp_path, {"a", "b", "c"})
    store.apply({"action": "review", "trace_id": "a", "status": "no_failure"})
    store.apply({"action": "review", "trace_id": "b", "status": "unreviewed"})
    store.apply({"action": "mark_reviewed", "trace_ids": ["a", "b", "c"]})
    saved = ReviewStore(tmp_path, {"a", "b", "c"}).read()
    assert saved["reviews"]["a"]["status"] == "no_failure"
    assert saved["reviews"]["b"]["status"] == "reviewed"
    assert saved["reviews"]["c"]["status"] == "reviewed"
    assert saved["labels"] == {}
    assert saved["annotations"] == []
    store.apply({"action": "review", "trace_id": "c", "status": "unreviewed"})
    assert store.read()["reviews"]["c"]["status"] == "unreviewed"


@pytest.mark.parametrize("trace_ids", [[], ["a", "unknown"], "a", None])
def test_mark_reviewed_rejects_invalid_trace_lists_without_partial_writes(tmp_path, trace_ids):
    store = ReviewStore(tmp_path, {"a"})
    with pytest.raises(ValueError):
        store.apply({"action": "mark_reviewed", "trace_ids": trace_ids})
    assert store.read()["reviews"] == {}


def test_toggle_review_round_trip_and_comment_pins_reviewed_state(tmp_path):
    store = ReviewStore(tmp_path, {"a", "b"})
    event = {"action": "toggle_review", "trace_ids": ["a", "b"]}
    assert store.apply(event)["reviews"]["a"]["status"] == "reviewed"
    saved = store.apply(event)
    assert all(r["status"] == "unreviewed" for r in saved["reviews"].values())
    store.apply({"action": "note", "trace_id": "a", "note": "Observation"})
    store.apply({"action": "review", "trace_id": "a", "status": "first_failure"})
    for _ in range(2):
        saved = store.apply(event)
        assert saved["reviews"]["a"]["status"] == "first_failure"
        assert saved["reviews"]["b"]["status"] == "reviewed"


def test_invalid_label_never_calls_langfuse_and_pending_can_retry(tmp_path):
    writes = []
    def fail(*args):
        writes.append(args)
        raise RuntimeError("network down")
    store = ReviewStore(tmp_path, {"a"}, sync=fail)
    store.apply({"action": "note", "trace_id": "a", "id": "origin", "note": "Unsupported claim observed"})
    store.apply({"action": "mode", "id": "claim", "definition": "Unsupported claim", "final": True,
                 "boundaries": "A missing citation alone is excluded", "requirement": "RESP-1",
                 "evaluator_type": "llm_judge", "annotation_ids": ["origin"]})
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


def test_accepting_suggestion_links_note_to_mode_and_is_idempotent(tmp_path):
    from analysis.helpers._state import write_json
    write_json(tmp_path / 'suggestions.json', [{'id': 's', 'trace_id': 'a', 'mode': 'issue',
                                               'note': 'Observed issue', 'quote': 'Evidence'}])
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: pytest.fail('No score should be written'))
    store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Observed issue', 'final': False})
    saved = store.apply({'action': 'suggestion', 'id': 's', 'decision': 'accept'})
    assert saved['modes'][0]['annotation_ids'] == ['accepted:s']
    assert saved['modes'][0]['final'] is False
    revision = saved['revision']
    saved = store.apply({'action': 'suggestion', 'id': 's', 'decision': 'accept'})
    assert saved['revision'] == revision
    assert len(saved['annotations']) == 1
    assert saved['modes'][0]['annotation_ids'] == ['accepted:s']
    assert saved['labels'] == {}
    assert ReviewStore(tmp_path, {'a'}).read()['modes'][0]['annotation_ids'] == ['accepted:s']


def test_retry_accept_repairs_old_missing_link_without_changing_human_decision(tmp_path):
    from analysis.helpers._state import write_json
    suggestion = {'id': 's', 'trace_id': 'a', 'mode': 'issue', 'note': 'Original suggestion'}
    write_json(tmp_path / 'suggestions.json', [suggestion])
    initial = {'revision': 7, 'annotations': [{'id': 'accepted:s', 'trace_id': 'a',
                'source': 'human_accepted_ai', 'note': 'Human-edited note'}],
               'modes': [{'id': 'issue', 'definition': 'Human definition', 'final': True, 'annotation_ids': []}],
               'decisions': {'s': {'decision': 'accept', 'updated_at': 'original timestamp'}},
               'reviews': {'a': {'status': 'reviewed'}}, 'labels': {'a:issue': {'value': 0}}}
    write_json(tmp_path / 'review_app.json', initial)
    store = ReviewStore(tmp_path, {'a'})
    saved = store.apply({'action': 'suggestion', 'id': 's', 'decision': 'accept'})
    assert saved['modes'][0]['annotation_ids'] == ['accepted:s']
    assert saved['modes'][0]['final'] is True
    for key in ['annotations', 'decisions', 'reviews', 'labels']:
        assert saved[key] == initial[key]


def test_rejected_suggestion_does_not_add_note_or_taxonomy_link(tmp_path):
    from analysis.helpers._state import write_json
    write_json(tmp_path / 'suggestions.json', [{'id': 's', 'trace_id': 'a', 'mode': 'issue', 'note': 'Candidate'}])
    store = ReviewStore(tmp_path, {'a'})
    store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Issue'})
    saved = store.apply({'action': 'suggestion', 'id': 's', 'decision': 'reject'})
    assert saved['modes'][0]['annotation_ids'] == []
    assert saved['annotations'] == []
    assert saved['labels'] == {}


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


@pytest.mark.parametrize('missing', ['boundaries', 'requirement', 'evaluator_type', 'annotation_ids'])
def test_final_mode_requires_all_six_fields_without_partial_save(tmp_path, missing):
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None)
    store.apply({'action': 'note', 'trace_id': 'a', 'id': 'origin', 'note': 'Observed issue'})
    event = {'action': 'mode', 'id': 'unsupported_claim', 'definition': 'Present for unsupported policy claims',
             'boundaries': 'Grounded claims without a citation are a separate mode',
             'requirement': 'RESP-1', 'evaluator_type': 'llm_judge',
             'annotation_ids': ['origin'], 'final': True}
    del event[missing]
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='Final modes require'):
        store.apply(event)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('evaluator', ['code_check', 'llm_judge'])
def test_complete_mode_can_be_finalised_and_evaluator_persists(tmp_path, evaluator):
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None)
    store.apply({'action': 'note', 'trace_id': 'a', 'id': 'origin', 'note': 'Observed issue'})
    store.apply({'action': 'mode', 'id': 'unsupported_claim', 'definition': 'Present for unsupported policy claims',
                 'boundaries': 'Exclude missing citations alone', 'requirement': 'RESP-1',
                 'evaluator_type': evaluator, 'annotation_ids': ['origin'], 'final': True})
    mode = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None).read()['modes'][0]
    assert mode['final'] is True
    assert mode['evaluator_type'] == evaluator
    assert mode['annotation_ids'] == ['origin']
    assert store.read()['labels'] == {}


def test_draft_mode_can_be_incomplete_and_preserves_existing_metadata(tmp_path):
    from analysis.helpers._state import write_json
    write_json(tmp_path / 'patterns.json', {'modes': [{
        'id': 'unsupported_claim', 'definition': 'Draft definition',
        'examples': 'Previously recorded trace examples', 'source': 'coding_agent_proposal',
        'evaluator': 'LLM judge with full policy context', 'annotation_ids': []}]})
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None)
    saved = store.apply({'action': 'mode', 'id': 'unsupported_claim', 'definition': 'Revised definition',
                         'evaluator_type': '', 'annotation_ids': [], 'final': False})['modes'][0]
    assert saved['examples'] == 'Previously recorded trace examples'
    assert saved['source'] == 'coding_agent_proposal'
    assert saved['evaluator'] == 'LLM judge with full policy context'
    assert saved['final'] is False


def test_unknown_evaluator_type_is_not_saved(tmp_path):
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: None)
    with pytest.raises(ValueError, match='Choose code check or LLM judge'):
        store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Draft', 'evaluator_type': 'other'})
    assert not store.path.exists()


def test_mode_review_status_persists_without_changing_labels_or_definition(tmp_path):
    store = ReviewStore(tmp_path, {'a'}, sync=lambda *_: pytest.fail('No score should be written'))
    saved = store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Original definition',
                         'review_status': 'approved', 'final': False})
    assert saved['modes'][0]['review_status'] == 'approved'
    saved = store.apply({'action': 'mode_review', 'id': 'issue', 'decision': 'rejected'})
    assert saved['modes'][0]['review_status'] == 'rejected'
    assert saved['modes'][0]['definition'] == 'Original definition'
    assert saved['modes'][0]['final'] is False
    assert saved['labels'] == {}
    assert saved['annotations'] == []
    assert ReviewStore(tmp_path, {'a'}).read()['modes'][0]['review_status'] == 'rejected'
    saved = store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Revised definition',
                         'review_status': 'approved', 'final': False})
    assert saved['modes'][0]['review_status'] == 'approved'


def test_unreviewed_mode_has_no_review_status(tmp_path):
    store = ReviewStore(tmp_path, {'a'})
    saved = store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Draft'})
    assert 'review_status' not in saved['modes'][0]


@pytest.mark.parametrize('event', [
    {'action': 'mode_review', 'id': 'unknown', 'decision': 'rejected'},
    {'action': 'mode_review', 'id': 'issue', 'decision': 'approved'},
    {'action': 'mode_review', 'id': 'issue', 'decision': 'other'},
    {'action': 'mode', 'id': 'issue', 'definition': 'Changed', 'review_status': 'other'},
])
def test_invalid_mode_review_does_not_change_state(tmp_path, event):
    store = ReviewStore(tmp_path, {'a'})
    store.apply({'action': 'mode', 'id': 'issue', 'definition': 'Draft'})
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.apply(event)
    assert store.path.read_bytes() == before
