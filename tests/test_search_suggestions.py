"""Retrieval produces review candidates, never labels or human decisions."""
import copy

from analysis.review_app.data import build_turn
from analysis.search_suggestions import search


def record(tid, timestamp, *, tool=False):
    return {
        'id': tid, 'timestamp': timestamp,
        'metadata': {'attributes': {'cartwheel.session_id': 'session',
                                    'cartwheel.scenario_id': 'example',
                                    'cartwheel.user_role': 'shopper'}},
        'input': [{'role': 'user', 'parts': [{'type': 'text', 'content': 'What is the return window?'}]}],
        'output': [{'role': 'assistant', 'parts': [{'type': 'text', 'content': 'The return window is 30 days.'}]}],
        'observations': ([{'id': 'policy', 'type': 'TOOL', 'name': 'get_policy',
                           'startTime': timestamp, 'input': {'policy_id': 'cw-returns'},
                           'output': {'ok': True, 'body': 'Returns within 30 days.'}}] if tool else []),
    }


def mode():
    return {'id': 'unsupported_policy_answer', 'definition': 'Unsupported policy claim.',
            'annotation_ids': [], 'final': False}


def test_retrieval_anchor_is_exact_and_does_not_mutate_human_state():
    records = [record('first', '2026-01-01')]
    state = {'annotations': [], 'labels': {}, 'decisions': {}, 'reviews': {}}
    before = copy.deepcopy(state)
    suggestions, counts = search(records, state, [mode()], [], 5)
    assert counts['unsupported_policy_answer'] == {'retrieved': 1, 'queued': 1}
    suggestion = suggestions[0]
    anchor = suggestion['anchor']
    block = next(b for b in build_turn(records[0])['blocks'] if b['id'] == anchor['block_id'])
    assert block['text'][anchor['start']:anchor['end']] == anchor['quote']
    assert suggestion['retrieval']['signal_is_label'] is False
    assert suggestion['mode_status'] == 'provisional'
    assert suggestion['status'] == 'pending'
    assert state == before


def test_earlier_policy_evidence_counts_but_future_evidence_does_not():
    early = record('early', '2026-01-01')
    late = record('late', '2026-01-02', tool=True)
    suggestions, _ = search([late, early], {'annotations': []}, [mode()], [], 5)
    assert [s['trace_id'] for s in suggestions] == ['early']
    early['observations'] = late['observations']
    late['observations'] = []
    suggestions, _ = search([late, early], {'annotations': []}, [mode()], [], 5)
    assert suggestions == []


def test_excludes_supporting_traces_and_preserves_existing_suggestions():
    records = [record('first', '2026-01-01'), record('second', '2026-01-02')]
    candidate_mode = mode()
    candidate_mode['annotation_ids'] = ['human-note']
    state = {'annotations': [{'id': 'human-note', 'trace_id': 'first'}]}
    existing = [{'id': 'previous', 'mode': candidate_mode['id'], 'trace_id': 'second'}]
    before = copy.deepcopy(existing)
    suggestions, counts = search(records, state, [candidate_mode], existing, 5)
    assert suggestions == []
    assert counts[candidate_mode['id']]['retrieved'] == 0
    assert existing == before


def test_limit_is_per_mode_and_ids_are_stable():
    records = [record('first', '2026-01-01'), record('second', '2026-01-02')]
    state = {'annotations': []}
    first, counts = search(records, state, [mode()], [], 1)
    again, _ = search(list(reversed(records)), state, [mode()], [], 1)
    assert len(first) == 1
    assert first[0]['id'] == again[0]['id']
    assert counts[mode()['id']] == {'retrieved': 2, 'queued': 1}


def test_uncapped_search_returns_all_matches_and_rerun_does_not_duplicate():
    records = [record(f'trace-{i}', f'2026-01-{i + 1:02}') for i in range(9)]
    state = {'annotations': []}
    suggestions, counts = search(records, state, [mode()], [], None)
    assert len(suggestions) == 9
    assert counts[mode()['id']] == {'retrieved': 9, 'queued': 9}
    repeated, counts = search(records, state, [mode()], suggestions, None)
    assert repeated == []
    assert counts[mode()['id']] == {'retrieved': 0, 'queued': 0}
