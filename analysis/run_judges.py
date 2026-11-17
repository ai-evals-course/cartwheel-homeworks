"""Homework 5: save judge evidence and create a fixed, stratified split.

Run from the repository root: python -m analysis.run_judges prepare
No model calls are made by preparation or splitting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from analysis.helpers import split_labels
from analysis.helpers._state import read_json, read_jsonl, state_path, write_json

MODE = 'unnecessary_response_content'


def _messages(messages: list[dict]) -> list[dict]:
    """Allow only conversation text and actual tool calls/results into inputs."""
    result = []
    for message in messages:
        role = message.get('role')
        if role not in {'user', 'assistant', 'tool'}:
            continue
        for part in message.get('parts', []):
            kind = part.get('type')
            if kind == 'text' and part.get('content'):
                result.append({'role': role, 'text': part['content']})
            elif kind == 'tool_call':
                result.append({'role': 'tool_call', 'name': part['name'],
                               'arguments': part['arguments'], 'call_id': part.get('id')})
            elif kind == 'tool_call_response':
                result.append({'role': 'tool_result', 'content': part['response'],
                               'call_id': part.get('id')})
    return result


def _conversation(record: dict) -> list[dict]:
    generations = sorted(
        (o for o in record.get('observations', []) if o.get('type') == 'GENERATION'),
        key=lambda o: o.get('startTime') or o.get('start_time') or '',
    )
    if not generations:
        raise ValueError(f"Trace {record['id']} has no generation evidence")
    # The final generation's input contains the actual history seen by the model,
    # including earlier requests, replies, tool calls and retrieved policy text.
    last = generations[-1]
    payload = last.get('input')
    output = last.get('output')
    if not isinstance(payload, dict) or not isinstance(output, list):
        raise ValueError(f"Trace {record['id']} has incomplete generation evidence")
    history = _messages(payload.get('messages', []))
    reply = _messages(output)
    if not any(m['role'] == 'user' for m in history) or not any(m['role'] == 'assistant' for m in reply):
        raise ValueError(f"Trace {record['id']} needs a user request and final reply")
    return history + reply


def _labels(mode: str) -> dict[str, dict]:
    current = {}
    for row in read_jsonl(state_path('hw5_labels', f'{mode}.jsonl')):
        if not row.get('superseded_by'):
            if row.get('label') not in (0, 1):
                raise ValueError('HW5 labels must use Pass=1 and Fail=0')
            current[row['trace_id']] = row
    if not current:
        raise ValueError(f'No HW5 labels for {mode}')
    return current


def prepare_inputs(mode: str = MODE, source: str | Path = 'traces/support_traces.json') -> list[dict]:
    """Save one eligible record per related conversation, without human labels.

    Related runs share a scenario ID, session ID, or the same sequence of user
    requests after normalizing case, whitespace and numeric identifiers. Choose
    the latest labeled trace in each connected group, without using its label.
    Missing and incomplete evidence is documented separately, never invented.
    Existing saved inputs are immutable: a changed export raises an error.
    """
    source = Path(source)
    payload = json.loads(source.read_text())
    traces = payload['traces'] if isinstance(payload, dict) else payload
    ids = [r['id'] for r in traces]
    if len(set(ids)) != len(ids):
        raise ValueError('Source contains duplicate trace IDs')
    labels = _labels(mode)
    available = {r['id']: r for r in traces if r['id'] in labels}
    excluded = {tid: 'missing from local export' for tid in labels.keys() - available.keys()}
    evidence = {}
    for tid, record in available.items():
        try:
            evidence[tid] = _conversation(record)
        except ValueError as exc:
            excluded[tid] = str(exc)
    # Union all relationship keys so a shared session still groups records whose
    # scenario IDs differ. Scenario/session metadata stays outside judge inputs.
    parent = {tid: tid for tid in evidence}

    def root(tid):
        while parent[tid] != tid:
            parent[tid] = parent[parent[tid]]
            tid = parent[tid]
        return tid

    owners = {}
    for tid, messages in evidence.items():
        record = available[tid]
        metadata = record.get('metadata') or {}
        attrs = metadata.get('attributes') or {}
        if isinstance(attrs, str):
            attrs = json.loads(attrs)
        scenario = record.get('cartwheel_scenario_id') or attrs.get('cartwheel.scenario_id')
        session = record.get('sessionId') or attrs.get('cartwheel.session_id')
        requests = '\n'.join(m['text'] for m in messages if m['role'] == 'user')
        signature = re.sub(r'\d+(?:[.,]\d+)*', '<number>', ' '.join(requests.lower().split()))
        keys = [('requests', signature)]
        if scenario:
            keys.append(('scenario', scenario))
        if session:
            keys.append(('session', session))
        for key in keys:
            if key in owners:
                parent[root(tid)] = root(owners[key])
            owners[key] = tid
    groups = {}
    for tid in evidence:
        groups.setdefault(root(tid), []).append(tid)
    selected = []
    for members in groups.values():
        representative = max(members, key=lambda t: (available[t].get('timestamp') or '', t))
        selected.append(representative)
        for tid in members:
            if tid != representative:
                excluded[tid] = f'related run; representative {representative}'
    records = [{'trace_id': tid, 'trace': evidence[tid]} for tid in sorted(selected)]
    counts = Counter(labels[tid]['label'] for tid in selected)
    if min(counts[0], counts[1]) < 30:
        raise ValueError(f'After exclusions, fewer than 30 in each class: {dict(counts)}')
    path = state_path('hw5_trace_inputs.json')
    if path.exists() and read_json(path) != records:
        raise ValueError('Saved judge inputs differ; preserving the existing input export')
    if not path.exists():
        write_json(path, records)
    report = {
        'mode': mode, 'source': str(source),
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'confirmed_labels': len(labels), 'eligible_conversations': len(records),
        'class_counts': {'Pass': counts[1], 'Fail': counts[0]},
        'grouping': 'Scenario ID, session ID, or identical user history after case/whitespace/numeric normalization; latest labeled record per connected group.',
        'limitation': 'Paraphrases with different wording and no shared scenario/session ID are not automatically identified.',
        'excluded': dict(sorted(excluded.items())),
    }
    report_path = state_path('..', 'report', f'hw5-preparation-{mode}.json')
    if not report_path.exists():
        write_json(report_path, report)
    os.environ['CARTWHEEL_JUDGE_TRACE_SOURCE'] = str(path.resolve())
    return records


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Create the HW5 split once, or validate and reuse the saved assignment."""
    records = read_json(state_path('hw5_trace_inputs.json'))
    if not records:
        raise ValueError('Run prepare_inputs() first')
    ids = [r['trace_id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate input trace IDs')
    labels = _labels(mode)
    if set(ids) - labels.keys():
        raise ValueError('Input records have no HW5 label')
    saved = read_json(state_path('splits.json'), {}).get(mode)
    if saved:
        assignment = {key: saved[key] for key in ('train', 'dev', 'test')}
        assigned = [tid for rows in assignment.values() for tid in rows]
        if len(assigned) != len(set(assigned)) or set(assigned) != set(ids):
            raise ValueError('Inputs differ from saved split; preserving the saved split')
        if saved.get('fractions') != [0.2, 0.4, 0.4] or saved.get('seed') != 7:
            raise ValueError('Existing saved split uses different parameters; preserving it')
        return assignment
    return split_labels(mode, fractions=(0.20, 0.40, 0.40), seed=7,
                        min_per_class=10, eligible_trace_ids=ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'split'])
    parser.add_argument('--mode', default=MODE)
    parser.add_argument('--source', default='traces/support_traces.json')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare_inputs(args.mode, args.source)
    assignment = split_data(args.mode)
    labels = _labels(args.mode)
    for name, ids in assignment.items():
        print(name, dict(Counter('Pass' if labels[tid]['label'] else 'Fail' for tid in ids)))
    print('CARTWHEEL_JUDGE_TRACE_SOURCE=' + str(state_path('hw5_trace_inputs.json').resolve()))


if __name__ == '__main__':
    main()
