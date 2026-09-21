# Cartwheel trace review app (HW4)

A single-page review interface for open coding, taxonomy building, and structured labeling of the Module 1 Cartwheel traces. Built new for HW4; `analysis/server.py` and `analysis/ui/index.html` were read as references but not reused.

## Run

From the repository root, with Langfuse running and `LANGFUSE_*` set in `.env`:

```bash
uv run python -m analysis.review_app.server            # http://127.0.0.1:8030/
uv run python -m analysis.review_app.server --offline  # read traces/support_traces.json instead
uv run python -m analysis.review_app.server --refresh  # re-fetch from Langfuse, ignore the cache
```

The first live run fetches the 313 traces listed in `traces/support_traces.json` from Langfuse and caches them under `analysis/review_app/.cache/` (git-ignored). Later runs start instantly from the cache.

## What it shows

- One conversation per screen. Traces are grouped by `cartwheel.scenario_id` and ordered by timestamp, because no trace carries `cartwheel.session_id` (the HW3 runner opened one session per scenario). Every trace id is preserved, so a judgment lands on the exact trace.
- Sticky header: scenario id, role, coverage/challenge group, tuple fields, and the scenario's expected outcome or criterion with its source. Always visible.
- Timeline: user message, then one box per model step (reasoning text, each tool call paired with its result, latency, `permission_denied`), then the reply. Write tools (`issue_refund`, `cancel_order`, `escalate_to_human`) show their status field in bold; failed tool results are marked red. Long results collapse to a summary line.
- Right margin: annotations aligned to the text they quote. Agent suggestions appear separately in purple with accept / reject controls.

## Views

| Tab | Purpose | State file |
| --- | --- | --- |
| Review | open coding: select text to annotate, or write a conversation-level note; "no failure observed" button | `analysis/state/annotations.json` |
| Taxonomy | modes with definition, boundary, SPEC source, evaluator, originating annotations, revision history | `analysis/state/patterns.json` |
| Labeling | one Fail / Pass per (trace, mode) for the final modes; each judgment writes a Langfuse score and a line in `labels/<mode>.jsonl` | `analysis/state/labels/` |
| Progress | reviewed counts per batch, role, group, intent; label completeness per mode | reads the above |
| Suggestions | pending / accepted / rejected agent suggestions with the rejection reason | `analysis/state/suggestions.json` |

Batches come from `analysis/state/sample_manifest.json` (`batches: [{name, method, reason, scenario_ids}]`) and drive the review queue.

## Deep links

`?batch=<batch name>&conv=<scenario id>&view=<tab>` opens a batch queue, a conversation, and a tab directly, e.g. `http://localhost:8030/?batch=batch4_uniform&conv=support-0097&view=review`.

## Keys

`j` / `k` next / previous, `n` no failure observed and advance, `r` reviewed and advance, `a` focus the note box, `e` expand all tool results, `s` system prompt, `1`..`9`, `0` toggle mode N (0 = mode 10) in the Labeling view, `c` confirm all pairs on the conversation and advance, `Tab` next trace in Labeling, `?` key list.

## Annotation record

```json
{"id": "...", "scenario_id": "support-0011", "trace_id": "b4378...", "turn": 1, "step": 1,
 "seg": "result0", "quote": "status=auto_approved", "note": "plain-words observation",
 "kind": "open_code | no_failure | accepted_suggestion", "source": "human | agent_suggestion",
 "batch": "batch1_uniform", "created_at": "2026-09-18T23:00:00Z"}
```

`seg` locates the quoted span: `user`, `reasoning<i>`, `call<i>`, `result<i>`, or `reply`, with `step` for the step index inside the turn.
