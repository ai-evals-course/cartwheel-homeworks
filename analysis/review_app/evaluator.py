"""Read-only projections of saved HW5 evaluator artifacts for the review UI."""
from pathlib import Path

from analysis.helpers._state import read_json, read_jsonl

METRIC_FIELDS = ('judge_id', 'split', 'n', 'tp', 'fn', 'tn', 'fp', 'tpr', 'tnr',
                 'tpr_interval', 'tnr_interval', 'class_counts')


def evaluator_summary(root: Path) -> dict:
    """Show HW5 modes only; never expose test results until their judge is frozen."""
    patterns = read_json(root / 'patterns.json', {}).get('modes', [])
    reviewed = read_json(root / 'review_app.json', {}).get('modes', [])
    definitions = {m['id']: m for m in patterns + reviewed if m.get('id')}
    splits = read_json(root / 'splits.json', {})
    modes = []
    for path in sorted((root / 'hw5_labels').glob('*.jsonl')):
        mode_id = path.stem
        labels = {r['trace_id']: r['label'] for r in read_jsonl(path)
                  if not r.get('superseded_by') and r.get('label') in (0, 1)}
        definition = definitions.get(mode_id, {})
        assignment = splits.get(mode_id, {})
        partition = {}
        for i, name in enumerate(('train', 'dev', 'test')):
            ids = assignment.get(name, [])
            fractions = assignment.get('fractions', [])
            partition[name] = {
                'ids': ids, 'total': len(ids),
                'pass': sum(labels.get(tid) == 1 for tid in ids),
                'fail': sum(labels.get(tid) == 0 for tid in ids),
                'unlabeled': sum(tid not in labels for tid in ids),
                'fraction': fractions[i] if len(fractions) == 3 else None,
            }
        judges = []
        for judge_path in (root / 'judges').glob('*.json'):
            judge = read_json(judge_path, {})
            if judge.get('mode') != mode_id or not judge.get('judge_id'):
                continue
            # Derive report filenames from the existing file, never from a URL.
            row = {key: judge.get(key) for key in ('judge_id', 'version', 'model', 'status', 'prompt_text')}
            for split in ('dev', 'test'):
                metrics = None
                if split != 'test' or judge.get('status') == 'frozen':
                    saved = read_json(root.parent / 'report' / f'{split}-{judge_path.name}', {})
                    if saved.get('judge_id') == judge['judge_id'] and saved.get('split') == split:
                        metrics = {key: saved[key] for key in METRIC_FIELDS if key in saved}
                row[split] = metrics
            judges.append(row)
        modes.append({
            'id': mode_id, 'name': definition.get('name', mode_id.replace('_', ' ')),
            'definition': definition.get('definition', ''), 'boundaries': definition.get('boundaries', ''),
            'requirement': definition.get('requirement', ''), 'label_count': len(labels),
            'seed': assignment.get('seed'), 'splits': partition,
            'judges': sorted(judges, key=lambda j: j.get('version', 0), reverse=True),
        })
    return {'modes': modes}
