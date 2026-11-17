"""Offline Part D lifecycle tests with synthetic labels in temporary state."""
import json
from pathlib import Path

import pytest

from analysis.helpers import register_judge
from analysis.helpers.scale import JudgeBatch
from analysis.run_judges import run_test


def setup_judge(tmp_path, monkeypatch):
    monkeypatch.setenv('CARTWHEEL_ANALYSIS_STATE', str(tmp_path / 'state'))
    state = tmp_path / 'state'
    (state / 'hw5_labels').mkdir(parents=True)
    mode = 'unnecessary_response_content'
    labels = [{'trace_id': tid, 'label': label} for tid, label in [('d1', 1), ('d0', 0), ('t1', 1), ('t0', 0)]]
    (state / 'hw5_labels' / f'{mode}.jsonl').write_text('\n'.join(map(json.dumps, labels)))
    (state / 'splits.json').write_text(json.dumps({mode: {'train': [], 'dev': ['d1', 'd0'], 'test': ['t1', 't0']}}))
    (state / 'hw5_trace_inputs.json').write_text(json.dumps([{'trace_id': r['trace_id'], 'trace': [{'role': 'user', 'text': 'request'}, {'role': 'assistant', 'text': 'reply'}]} for r in labels]))
    judge_id = register_judge(mode, 'test rubric', 'gpt-4o-mini')['judge_id']
    return state, judge_id


def save_dev_result(state, judge_id):
    from analysis.helpers import judge_alignment, run_judge
    run_judge(judge_id, split='dev', classify=lambda prompt, ids: {'d1': 1, 'd0': 0})
    report = state.parent / 'report'
    report.mkdir()
    (report / f'dev-{judge_id}.json').write_text(json.dumps(judge_alignment(judge_id, 'dev')))


def test_no_freeze_or_paid_calls_without_approval_or_development(tmp_path, monkeypatch):
    state, judge_id = setup_judge(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('No model call should occur')
    monkeypatch.setattr('analysis.helpers.scale.classify_store', forbidden)
    with pytest.raises(ValueError, match='approval'):
        run_test(judge_id)
    with pytest.raises(ValueError, match='development'):
        run_test(judge_id, approved=True)
    judge = json.loads((state / 'judges' / f'{judge_id}.json').read_text())
    assert judge['status'] == 'draft'


def test_freezes_once_resumes_cached_batches_and_saves_real_helper_metrics(tmp_path, monkeypatch):
    state, judge_id = setup_judge(tmp_path, monkeypatch)
    save_dev_result(state, judge_id)
    calls = []
    def classify(prompt, model, ids):
        judge = json.loads((state / 'judges' / f'{judge_id}.json').read_text())
        assert judge['status'] == 'frozen'
        assert model == 'gpt-4o-mini'
        calls.extend(ids)
        result = JudgeBatch()
        for tid in ids:
            result[tid] = 1 if tid == 't1' else 0
            result.critiques[tid] = 'Synthetic evidence for offline lifecycle check.'
        return result
    monkeypatch.setattr('analysis.helpers.scale.classify_store', classify)
    result = run_test(judge_id, approved=True)
    assert (result['tp'], result['tn'], result['fp'], result['fn']) == (1, 1, 0, 0)
    assert result['tpr'] == result['tnr'] == 1
    assert result['tpr_interval'][0] < 1
    assert result['tnr_interval'][0] < 1
    path = state / 'judges' / f'{judge_id}.json'
    frozen_at = json.loads(path.read_text())['frozen_at']
    assert run_test(judge_id, approved=True) == result
    assert calls == ['t1', 't0']
    assert json.loads(path.read_text())['frozen_at'] == frozen_at
    saved = json.loads((state.parent / 'report' / f'test-{judge_id}.json').read_text())
    assert saved['class_counts'] == {'Pass': 1, 'Fail': 1}
    assert saved['judge_id'] == judge_id


def test_development_reuses_registered_judge_and_never_calls_test(tmp_path, monkeypatch):
    from analysis.run_judges import run_development
    import hashlib
    state, judge_id = setup_judge(tmp_path, monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-placeholder')
    prompt = tmp_path / 'judge-v0.txt'
    prompt.write_text('test rubric')
    manifest = {
        'mode': 'unnecessary_response_content', 'examples': [],
        'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest(),
        'input_sha256': hashlib.sha256((state / 'hw5_trace_inputs.json').read_bytes()).hexdigest(),
        'splits_sha256': hashlib.sha256((state / 'splits.json').read_bytes()).hexdigest(),
    }
    prompt.with_suffix('.examples.json').write_text(json.dumps(manifest))
    calls = []
    def classify(prompt_text, model, ids):
        assert set(ids) <= {'d1', 'd0'}
        assert model == 'gpt-4o-mini'
        calls.extend(ids)
        result = JudgeBatch()
        for tid in ids:
            result[tid] = 1  # Always Pass: real helper must report TNR=0.
            result.critiques[tid] = 'Offline classifier evidence.'
        return result
    monkeypatch.setattr('analysis.helpers.scale.classify_store', classify)
    with pytest.raises(ValueError, match='approval'):
        run_development('unnecessary_response_content', prompt)
    result = run_development('unnecessary_response_content', prompt, approved=True)
    assert result['judge_id'] == judge_id
    assert result['tpr'] == 1 and result['tnr'] == 0
    assert result['disagreements'] == ['d0']
    assert result['class_counts'] == {'Pass': 1, 'Fail': 1}
    report_path = state.parent / 'report' / f'dev-{judge_id}.json'
    saved = json.loads(report_path.read_text())
    saved['critique_comments'] = {'d0': {'comment': 'Keep my review note.', 'revision': 1}}
    report_path.write_text(json.dumps(saved))
    resumed = run_development('unnecessary_response_content', prompt, approved=True)
    assert resumed['critique_comments'] == saved['critique_comments']
    assert calls == ['d1', 'd0']
    history = json.loads((state / 'judges/_history_unnecessary_response_content.json').read_text())
    assert len(history['versions']) == 1
    judge = json.loads((state / 'judges' / f'{judge_id}.json').read_text())
    assert judge['status'] == 'draft'
    assert not set(judge['predictions'][judge['prompt_hash']]) & {'t1', 't0'}
    assert (state.parent / 'report' / f'dev-{judge_id}.json').exists()
    manifest['examples'] = [{'trace_id': 't1'}]
    prompt.with_suffix('.examples.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='training'):
        run_development('unnecessary_response_content', prompt, approved=True)


def test_test_runner_loads_local_env_before_backend_selection(tmp_path, monkeypatch):
    """Regression: a key stored only in .env must enable the DocETL backend."""
    import os
    state, judge_id = setup_judge(tmp_path, monkeypatch)
    save_dev_result(state, judge_id)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    env_path = tmp_path / '.env'
    env_path.write_text('OPENAI_API_KEY=offline-env-key\n')
    monkeypatch.setattr('dotenv.main.find_dotenv', lambda: str(env_path))
    def classify(prompt, model, ids):
        assert os.environ.get('OPENAI_API_KEY') == 'offline-env-key'
        result = JudgeBatch()
        for tid in ids:
            result[tid] = int(tid == 't1')
            result.critiques[tid] = 'Synthetic offline evidence.'
        return result
    monkeypatch.setattr('analysis.helpers.scale.classify_store', classify)
    run_test(judge_id, approved=True)
