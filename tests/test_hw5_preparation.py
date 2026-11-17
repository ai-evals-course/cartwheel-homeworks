"""HW5 preparation tests use temporary exports, never student state."""
import json

import pytest

from analysis.run_judges import prepare_inputs, split_data


def make_export(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    monkeypatch.setenv('CARTWHEEL_ANALYSIS_STATE', str(state))
    (state / 'hw5_labels').mkdir(parents=True)
    labels, traces = [], []
    for i in range(60):
        tid = f'trace-{i:02}'
        labels.append({'trace_id': tid, 'label': i % 2, 'comment': 'SECRET REVIEW'})
        traces.append({
            'id': tid, 'cartwheel_scenario_id': f'scenario-{i}',
            'timestamp': f'2026-11-17T00:00:{i:02}Z', 'scores': ['SECRET SCORE'],
            'observations': [{'type': 'GENERATION', 'startTime': '1',
                'input': {'messages': [
                    {'role': 'system', 'parts': [{'type': 'text', 'content': 'instructions'}]},
                    {'role': 'user', 'parts': [{'type': 'text', 'content': f'question {chr(97+i//26)}{chr(97+i%26)}'}]},
                    {'role': 'assistant', 'parts': [{'type': 'tool_call', 'name': 'get_policy', 'arguments': {'policy_id': 'cw-refunds'}, 'id': 'call-1'}]},
                    {'role': 'tool', 'parts': [{'type': 'tool_call_response', 'id': 'call-1', 'response': 'policy evidence'}]},
                ]},
                'output': [{'role': 'assistant', 'parts': [{'type': 'text', 'content': 'answer'}]}],
            }],
        })
    labels_path = state / 'hw5_labels/unnecessary_response_content.jsonl'
    labels_path.write_text('\n'.join(map(json.dumps, labels)))
    source = tmp_path / 'traces.json'
    source.write_text(json.dumps({'traces': traces}))
    return state, source, traces


def test_preserves_history_tools_and_labels_but_excludes_metadata_and_related_runs(tmp_path, monkeypatch):
    state, source, traces = make_export(tmp_path, monkeypatch)
    # A second labeled run of the same scenario must not cross splits.
    traces.append({**traces[0], 'id': 'related-run', 'timestamp': '2026-11-16'})
    with (state / 'hw5_labels/unnecessary_response_content.jsonl').open('a') as handle:
        handle.write('\n' + json.dumps({'trace_id': 'related-run', 'label': 0}))
    # Latest generation input holds earlier turns; only its output is appended.
    traces[2]['observations'].insert(0, {'type': 'GENERATION', 'startTime': '0',
        'input': {'messages': []}, 'output': [{'role': 'assistant', 'parts': [{'type': 'text', 'content': 'earlier output'}]}]})
    source.write_text(json.dumps({'traces': traces}))
    labels_path = state / 'hw5_labels/unnecessary_response_content.jsonl'
    original = labels_path.read_bytes()
    records = prepare_inputs('unnecessary_response_content', source)
    assert len(records) == 60
    assert {r['trace_id'] for r in records}.isdisjoint({'related-run'})
    assert all(set(r) == {'trace_id', 'trace'} for r in records)
    messages = next(r['trace'] for r in records if r['trace_id'] == 'trace-02')
    assert [m['role'] for m in messages] == ['user', 'tool_call', 'tool_result', 'assistant']
    assert messages[2]['content'] == 'policy evidence'
    assert 'SECRET' not in json.dumps(records)
    assert 'instructions' not in json.dumps(records)
    assert labels_path.read_bytes() == original
    before = (state / 'hw5_trace_inputs.json').read_bytes()
    prepare_inputs('unnecessary_response_content', source)
    assert (state / 'hw5_trace_inputs.json').read_bytes() == before
    traces[2]['observations'][-1]['output'][0]['parts'][0]['content'] = 'changed'
    source.write_text(json.dumps({'traces': traces}))
    with pytest.raises(ValueError, match='preserv'):
        prepare_inputs('unnecessary_response_content', source)


def test_split_reuses_saved_assignment_and_preserves_other_modes(tmp_path, monkeypatch):
    state, source, _ = make_export(tmp_path, monkeypatch)
    (state / 'splits.json').write_text(json.dumps({'demo': {'test': ['keep-me']}}))
    prepare_inputs('unnecessary_response_content', source)
    result = split_data('unnecessary_response_content')
    assert [len(result[k]) for k in ('train', 'dev', 'test')] == [12, 24, 24]
    assert len(set().union(*(set(v) for v in result.values()))) == 60
    labels = {f'trace-{i:02}': i % 2 for i in range(60)}
    for name, n in [('train', 6), ('dev', 12), ('test', 12)]:
        assert sum(labels[t] for t in result[name]) == n
    before = (state / 'splits.json').read_bytes()
    assert split_data('unnecessary_response_content') == result
    assert (state / 'splits.json').read_bytes() == before
    assert json.loads(before)['demo']['test'] == ['keep-me']
    records = json.loads((state / 'hw5_trace_inputs.json').read_text())
    records.pop()
    (state / 'hw5_trace_inputs.json').write_text(json.dumps(records))
    with pytest.raises(ValueError, match='saved split'):
        split_data('unnecessary_response_content')
