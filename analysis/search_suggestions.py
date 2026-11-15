"""Retrieve review candidates from captured traces; never assign failure labels.

Run from the repository root. Draft modes require --include-provisional.
The rules deliberately retrieve ambiguous cases for explicit human review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from analysis.helpers._state import read_json, write_json
from analysis.review_app.data import ReviewStore, build_turn, group_sessions


def match(pattern, text):
    return re.search(pattern, text, re.I | re.S)


def retrieve(mode, final, user, tools, prior_tools, role):
    """Return an exact reply excerpt and retrieval rationale, not a judgment."""
    text = final['text']
    names = {t['name'] for t in tools}
    history_names = {t['name'] for t in prior_tools + tools}
    orders = [t['result']['order'] for t in prior_tools + tools
              if isinstance(t.get('result'), dict) and isinstance(t['result'].get('order'), dict)]
    order = orders[-1] if orders else {}
    grounded = bool(history_names & {'get_policy', 'search_help_center'})
    writes = [t for t in prior_tools + tools if t['name'] in {'issue_refund', 'cancel_order'}]
    queued = any(isinstance(t.get('result'), dict)
                 and t['result'].get('status') == 'queued_for_approval' for t in writes)
    signal = None
    reason = ''
    if mode == 'unsupported_policy_answer':
        signal = match(r'[^\n.!?]*(?:business days|return window|restocking fee|shipping|disput\w*|escalat\w*)[^\n.!?]*[.!?]?', text) if not grounded else None
        reason = 'Policy-like advice appears without a captured policy lookup in this or earlier turns. Check the complete session and whether the claim actually requires policy evidence.'
    elif mode == 'unnecessary_response_content':
        signal = match(r'(?:If you (?:have|need|want)|If there(?:\x27s| is) anything|Let me know if)[^\n]*', text)
        reason = 'A generic closing resembles the human examples. Check whether it supplies a necessary next step rather than redundant content; the style requirement remains provisional.'
    elif mode == 'avoidable_clarification':
        if match(r'full refund|entire (?:amount|order)|refund (?:the )?(?:full|total) amount', user) and order.get('total_usd'):
            signal = match(r'[^\n.!?]*(?:specify|confirm|provide|let me know)[^\n.!?]*(?:amount|how much)[^\n.!?]*[.!?]?', text)
        reason = 'The user mentions a full refund and a captured order contains a total, yet the reply asks for an amount. Verify scope and authorization; a known total alone is not enough.'
    elif mode == 'omitted_requested_action':
        if match(r'listing|catalog|inventory|product|pull up|look up', user) and 'search_products' not in names:
            signal = match(r'[^\n.!?]*(?:don.t have|cannot|can.t|unable|dashboard)[^\n.!?]*[.!?]?', text)
        elif match(r'cancel', user) and order.get('status') == 'placed' and 'cancel_order' not in history_names:
            signal = match(r'.+', text)
        elif (match(r'full refund|refund (?:the )?(?:full|total) amount', user)
              and order.get('refund_eligible') is True and 'issue_refund' not in history_names):
            signal = match(r'.+', text)
        reason = 'An available requested action may have been left unattempted. Check missing information, authorization, earlier actions, and legitimate reasons to defer.'
    elif mode == 'missing_human_escalation':
        trigger = match(r'(?:disput\w*|change[^\n]*(?:account|email|address))', user)
        if trigger and 'escalate_to_human' not in history_names and not queued:
            signal = match(r'.+', text)
        reason = 'A possible dispute/account-change trigger appears without a captured escalation or approval queue. General policy questions may be close negatives; review the actual request under ESC-1–ESC-4.'
    elif mode == 'misstated_action_status':
        latest = writes[-1].get('result', {}) if writes else {}
        confirmed = latest.get('ok') is True and latest.get('status') in {'auto_approved', 'cancelled'}
        if not confirmed:
            signal = match(r'[^\n.!?]*(?:refund|cancel\w*)[^\n.!?]*(?:successfully|processed|completed|issued)[^\n.!?]*[.!?]?', text)
        reason = 'Completion-like wording lacks a matching confirmed write in captured history. Check whether the reply merely describes initiation and clearly states pending approval; that wording is a disputed boundary.'
    elif mode == 'incorrect_tool_arguments':
        bad = [t for t in tools if t['name'] == 'search_products'
               and isinstance(t.get('arguments'), dict)
               and str(t['arguments'].get('store', '')).isdigit()
               and isinstance(t.get('result'), dict) and t['result'].get('error') == 'not_found']
        if bad:
            signal = match(r'.+', text)
        reason = 'A captured search_products call uses a numeric store string and returns not_found. The contract expects a store name/slug. Review recovery and the provisional acceptance rule for avoidable read errors.'
    elif mode == 'unexplained_refund_refusal':
        if order.get('refund_eligible') is False and not match(r'because|due to|reason|outside|window|don.t know|not (?:provided|available|explain)', text):
            signal = match(r'[^\n.!?]*(?:not eligible|ineligible|cannot[^\n]*refund|can.t[^\n]*refund)[^\n.!?]*[.!?]?', text)
        reason = 'The reply may repeat an ineligible flag without its basis. The tool may expose no reason; an explicit acknowledgment of missing information is a close negative. Never infer ineligibility from delivery alone.'
    elif mode == 'policy_link_missing':
        if not match(r'https?://|\]\(', text):
            signal = match(r'[^\n]*(?:cw-|store-[a-z-]+-policy)[^\n]*', text)
        reason = 'An identifier-only citation resembles the link preference. RESP-1 currently permits identifiers without hyperlinks; this is a requirement-decision candidate, not a confirmed failure.'
    elif mode == 'merchant_refund_handling':
        if role == 'merchant':
            signal = match(r'[^\n.!?]*refund[^\n.!?]*[.!?]?', text)
        reason = 'Merchant-facing refund wording matches the human concern. AUTH-1 permits refunds for the merchant own store; review the requirement question rather than infer an authorization violation.'
    elif mode == 'partial_refund_amount_prompt':
        signal = match(r'[^\n.!?]*(?:amount[^\n]*refund|refund amount|how much)[^\n.!?]*[.!?]?', text)
        reason = 'A refund-amount prompt resembles the partial-refund concern. TOOL-7 allows positive amounts up to the total, so clarification can be appropriate; the requirement question remains open.'
    elif mode == 'internal_identifier_in_reply':
        signal = match(r'[^\n.!?]*store (?:ID|identifier)[^\n.!?]*[.!?]?', text)
        reason = 'The reply exposes a store identifier. Check whether it was requested or useful; the current specification has no blanket prohibition and this is not evidence of unauthorized access.'
    elif mode == 'public_policy_audience_concern':
        if role == 'shopper':
            signal = match(r'[^\n.!?]*payout[^\n.!?]*[.!?]?', text)
        reason = 'Payout-policy wording is addressed to a shopper. AUTH-1 permits public policy searches for every role; review as an audience-requirement question, not a confirmed disclosure failure.'
    if signal:
        return signal.group().strip(), reason
    return None


def search(records, state, modes, existing, limit):
    records_by_id = {record['id']: record for record in records}
    notes = {n['id']: n for n in state['annotations']}
    seen = {(s.get('mode'), s.get('trace_id')) for s in existing}
    supporting = {(m['id'], notes[aid]['trace_id']) for m in modes
                  for aid in m.get('annotation_ids', []) if aid in notes}
    candidates = {m['id']: [] for m in modes}
    for session in group_sessions(records):
        prior_tools = []
        for trace in session['traces']:
            raw = records_by_id[trace['id']]
            turn = build_turn(raw)
            blocks = turn['blocks']
            finals = [b for b in blocks if b['role'] == 'assistant']
            tools = [b for b in blocks if b['role'] == 'tool']
            if finals:
                final = finals[-1]
                user = '\n'.join(b['text'] for b in blocks if b['role'] == 'user')
                for mode in modes:
                    key = mode['id'], trace['id']
                    if key in supporting or key in seen:
                        continue
                    hit = retrieve(mode['id'], final, user, tools, prior_tools,
                                   turn['meta'].get('cartwheel.user_role'))
                    if not hit:
                        continue
                    quote, rationale = hit
                    start = final['text'].index(quote)
                    anchor = {'block_id': final['id'], 'field': final['field'],
                              'quote': quote, 'start': start, 'end': start + len(quote)}
                    signature = json.dumps([mode['id'], trace['id'], anchor], sort_keys=True)
                    sid = 'retrieval:' + hashlib.sha256(signature.encode()).hexdigest()[:24]
                    candidates[mode['id']].append({
                        'id': sid, 'trace_id': trace['id'], 'mode': mode['id'],
                        'anchor': anchor, 'note': rationale,
                        'source': 'deterministic_retrieval', 'status': 'pending',
                        'mode_status': 'confirmed' if mode.get('final') else 'provisional',
                        'requirement_decision_pending': mode.get('status') == 'requirement_decision_pending',
                        'retrieval': {'method': 'structural_text_filter_v1',
                                      'signal_is_label': False, 'session_id': session['id'],
                                      'scenario_id': trace.get('scenario'),
                                      'definition': mode['definition']},
                    })
            prior_tools.extend(tools)
    selected, counts = [], {}
    for mid, hits in candidates.items():
        # Select different sessions first; never describe these as prevalence samples.
        diverse, deferred, sessions = [], [], set()
        for hit in sorted(hits, key=lambda item: item['trace_id']):
            sid = hit['retrieval']['session_id']
            if sid in sessions:
                deferred.append(hit)
            else:
                diverse.append(hit)
                sessions.add(sid)
        chosen = (diverse + deferred)[:limit]
        selected.extend(chosen)
        counts[mid] = {'retrieved': len(hits), 'queued': len(chosen)}
    return selected, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, default=Path('traces/support_traces.json'))
    parser.add_argument('--state-dir', type=Path, default=Path('analysis/state'))
    parser.add_argument('--mode', action='append', help='Mode ID; repeat for multiple modes.')
    parser.add_argument('--include-provisional', action='store_true')
    parser.add_argument('--limit-per-mode', type=int, default=5)
    parser.add_argument('--all-matches', action='store_true',
                        help='Queue every additional retrieval match, without a per-mode cap.')
    parser.add_argument('--source-note', default='Saved export only; live-project coverage has not been verified.')
    args = parser.parse_args()
    if args.limit_per_mode < 1:
        parser.error('--limit-per-mode must be positive')
    bundle = read_json(args.export)
    records = bundle['traces'] if isinstance(bundle, dict) else bundle
    store = ReviewStore(args.state_dir, {r['id'] for r in records}, sync=lambda *_: None)
    state = store.read()
    modes = [m for m in state['modes'] if (not args.mode or m['id'] in args.mode)
             and (m.get('final') or args.include_provisional)]
    if not modes:
        parser.error('No confirmed modes selected. Confirm a mode or explicitly use --include-provisional.')
    if args.mode and set(args.mode) != {m['id'] for m in modes}:
        parser.error('An unknown or unconfirmed mode was requested.')
    path = args.state_dir / 'suggestions.json'
    before = path.read_bytes() if path.exists() else None
    payload = json.loads(before) if before is not None else []
    existing = payload if isinstance(payload, list) else payload.get('suggestions', [])
    added, counts = search(records, state, modes, existing,
                           None if args.all_matches else args.limit_per_mode)
    if (path.read_bytes() if path.exists() else None) != before:
        raise RuntimeError('Suggestions changed during search; rerun without overwriting them.')
    if added:
        if isinstance(payload, list):
            payload = existing + added
        else:
            payload['suggestions'] = existing + added
        write_json(path, payload)
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'source': str(args.export), 'exported_at': bundle.get('exported_at') if isinstance(bundle, dict) else None,
              'traces_scanned': len(records), 'modes': counts, 'suggestions_added': len(added),
              'trace_ids_scanned': sorted(record['id'] for record in records),
              'all_matches_queued': args.all_matches,
              'confirmed_modes': [m['id'] for m in modes if m.get('final')],
              'scope': args.source_note,
              'human_validation': 'Pending. Matches are retrieval signals, not labels or accept/reject decisions.'}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_json(args.state_dir.parent / 'report' / f'suggestion_search_{stamp}.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'trace_ids_scanned'}, indent=2))


if __name__ == '__main__':
    main()
