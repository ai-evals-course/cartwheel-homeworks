"""Read-only evaluator summaries use isolated homework artifacts."""
import json

from analysis.review_app.evaluator import evaluator_summary


def put(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def artifacts(tmp_path):
    root = tmp_path / 'state'
    put(root / 'patterns.json', {'modes': [{'id': 'content', 'name': 'Unnecessary content', 'definition': 'Irrelevant final content.', 'boundaries': 'Useful next steps pass.'}]})
    put(root / 'splits.json', {'content': {'train': ['a'], 'dev': ['b'], 'test': ['c'], 'seed': 7, 'fractions': [.2, .4, .4]}})
    (root / 'hw5_labels').mkdir()
    (root / 'hw5_labels/content.jsonl').write_text('\n'.join(json.dumps(r) for r in [
        {'trace_id': 'a', 'label': 1}, {'trace_id': 'b', 'label': 0}, {'trace_id': 'c', 'label': 1},
        {'trace_id': 'a', 'label': 0},  # Most recent decision wins.
    ]))
    put(root / 'judges/content-v0.json', {'judge_id': 'content-v0', 'mode': 'content', 'version': 0,
        'model': 'gpt-4o-mini', 'status': 'draft', 'prompt_text': 'Rubric', 'predictions': {'private': {'c': 0}}})
    metrics = {'judge_id': 'content-v0', 'split': 'dev', 'n': 1, 'tp': 0, 'fn': 0, 'tn': 1, 'fp': 0,
               'tpr': 0, 'tnr': 1, 'tpr_interval': [None, None], 'tnr_interval': [.2, 1],
               'disagreements': ['PRIVATE'], 'extra': 'PRIVATE'}
    put(tmp_path / 'report/dev-content-v0.json', metrics)
    put(tmp_path / 'report/test-content-v0.json', {**metrics, 'split': 'test'})
    return root


def test_summary_counts_latest_hw5_labels_and_does_not_leak_unfrozen_test_results(tmp_path):
    root = artifacts(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    data = evaluator_summary(root)
    mode = data['modes'][0]
    assert mode['definition'] == 'Irrelevant final content.'
    assert mode['splits']['train'] == {'ids': ['a'], 'total': 1, 'pass': 0, 'fail': 1, 'unlabeled': 0, 'fraction': .2}
    judge = mode['judges'][0]
    assert judge['dev']['tnr'] == 1
    assert judge['test'] is None
    assert 'predictions' not in judge
    assert 'PRIVATE' not in json.dumps(data)
    assert all(p.read_bytes() == contents for p, contents in before.items())


def test_frozen_results_appear_and_missing_results_are_pending(tmp_path):
    root = artifacts(tmp_path)
    path = root / 'judges/content-v0.json'
    judge = json.loads(path.read_text()); judge['status'] = 'frozen'; put(path, judge)
    assert evaluator_summary(root)['modes'][0]['judges'][0]['test']['n'] == 1
    (tmp_path / 'report/dev-content-v0.json').unlink()
    assert evaluator_summary(root)['modes'][0]['judges'][0]['dev'] is None
    assert evaluator_summary(tmp_path / 'missing') == {'modes': []}


def test_evaluator_http_endpoint_uses_server_state_directory(tmp_path):
    import threading
    import urllib.request
    from analysis.review_app.server import ReviewServer
    root = artifacts(tmp_path)
    server = ReviewServer(('127.0.0.1', 0), [], root, 'Test export', sync=lambda *_: None)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/evaluator') as response:
            assert json.load(response)['modes'][0]['id'] == 'content'
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/evaluator.js') as response:
            assert 'javascript' in response.headers['Content-Type']
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_evaluator_get_handler_returns_saved_artifacts_without_a_socket(tmp_path):
    from types import SimpleNamespace
    from analysis.review_app.server import ReviewHandler
    root = artifacts(tmp_path)
    handler = ReviewHandler.__new__(ReviewHandler)
    handler.path = '/api/evaluator'
    handler.local_request = lambda: True
    handler.server = SimpleNamespace(store=SimpleNamespace(root=root))
    replies = []
    handler.respond = lambda payload, *args, **kwargs: replies.append(payload)
    handler.do_GET()
    assert replies[0]['modes'][0]['judges'][0]['dev']['tnr'] == 1
    assert replies[0]['modes'][0]['judges'][0]['test'] is None
