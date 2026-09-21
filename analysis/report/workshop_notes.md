# Workshop notes (HW4 Part C)

Raindrop Workshop inspection of replayed Cartwheel runs. Written by the coding agent on 2026-09-20 from the Workshop trace store; every claim below points at a run id and a span that can be reopened in Workshop. These are hypotheses, not labels. The decision column at the end is for the human reviewer.

## Setup

- Instrumentation: `observability/instrument.py::setup_workshop()` adds one OTLP/HTTP span processor to the tracer provider that Langfuse already registers, pointed at Workshop's `/v1/traces`. Langfuse and OpenLLMetry are untouched; Workshop receives the same span tree Langfuse does. Opt in with `RAINDROP_LOCAL_DEBUGGER=http://localhost:5899/v1/` in `.env`.
- Why not the Raindrop SDK integration: `raindrop-openai-agents` 0.0.11 on `raindrop-ai` 0.0.68 was wired first and produced a run, but in local-only mode (no cloud write key) its `track_tool` path is disabled, so every tool span is dropped. It was removed again.
- Known Workshop limitation: tool input/output previews are blank in the UI because Workshop reads `traceloop.entity.input/output` while OpenLLMetry writes `gen_ai.tool.call.arguments/result`. The values are in span attributes and `search_run` finds them.
- Replay method: the ten batch 4 conversations that carried an open code (the five "no failure observed" ones were skipped) were replayed with `scenarios.runner --ids ...` against a server on port 8012 using a freshly seeded scratch database (`seed.generate --db <scratch>/replay.db`), model `gpt-5.5`, the same model as the HW3 final run. Transcripts: `analysis/report/workshop_replay_results.jsonl`. Replays are not part of the review population; the review app fetches only the trace ids in `traces/support_traces.json`.
- A Workshop run id is the OpenTelemetry trace id, so the same id also opens the replay trace in Langfuse.
- Coverage: 8 shopper and 2 support conversations; intents refund, return deadline, product search, order status, cancellation; tools `find_order`, `get_order`, `list_my_orders`, `search_products`, `search_help_center`, `get_policy`, `get_store_policy`, `issue_refund`, `cancel_order`, `escalate_to_human`. No merchant scenario fell into this set.

## Inspected runs

One Workshop run per user turn. The original HW3 trace id is the one the review interface shows.

| Scenario | Turn | Workshop run id (replay) | Original trace id | Role | Tool sequence in replay |
|---|---|---|---|---|---|
| support-0011 | 0 | `b1b0d514dd889493fe13a8fa82203047` | `d63587734a8ed48b3fcec20764296e3c` | shopper | find_order, get_order x2, search_help_center, get_policy, search_help_center, get_policy, get_store_policy |
| support-0011 | 1 | `f7a70447372163078792d4baf86f1014` | `b437803d98806f0766484854007212f2` | shopper | find_order, search_products, issue_refund (auto_approved) |
| support-0052 | 0 | `b0b2ef1ce261364b975275ccd904312b` | `df4706f3e65f2e33e7266254d9d11517` | shopper | get_order, get_store_policy, search_help_center, get_policy |
| support-0052 | 1 | `94b7ec1a0698da98cf8f7cea164a76fb` | `ae4dd475b14325494a30f8dcd19307e0` | shopper | escalate_to_human (ticket 151) |
| support-0052 | 2 | `59739e48ec24d95473374e7778894b8c` | `37c8aa38ce99878aeba5f74634b28eed` | shopper | none |
| support-0054 | 0 | `4bda20cceb3817a730fd902e11e01376` | `7c5ce7600c15a075e4ecc586d498785e` | shopper | search_help_center + find_order, get_order + get_policy + get_store_policy |
| support-0097 | 0 | `e9d46b5e05db911241afc7694b52f4d4` | `a92060ed0ad9b9a5a153163471f7deb7` | support | get_order, issue_refund (queued_for_approval) |
| support-0117 | 0 | `b3a224b7f292255b61efc16d34975bf3` | `ffe3857a020e5c55ea953479e7157963` | shopper | search_products |
| support-0152 | 0 | `d857aecea2cca48d4b1744b54d7396bf` | `bbcb26c2f1c272cfcc84223cf45f73ff` | shopper | get_order, get_store_policy, search_help_center, get_policy, search_help_center, get_policy, escalate_to_human |
| support-0169 | 0 | `3b0caec51d98d3f64019fc913a604cf5` | `f241cce1c5036e643899d4dbc5cadcc4` | support | get_order |
| support-0176 | 0 | `fc19856a4d28683e4f78112189f00b4b` | `e197344ac6c0e5f811a4f3492c2b0239` | shopper | get_order, cancel_order |
| support-0230 | 0 | `9645a5df8f4e79ee5d83ebdd3820d133` | `3a50b2ad0f5ab100dd094d375b3d41b6` | shopper | get_order, get_store_policy, search_help_center x2, get_policy |
| support-0245 | 0 | `4535889151197186fd60a6adf02536c5` | `472ce4e000300d855e31b5622bb42c51` | shopper | find_order, get_order x2, escalate_to_human (ticket 153) |
| support-0245 | 1 | `760e740dcf28c4628457791f17c33b56` | `fe28adae055380767589059de73d029e` | shopper | list_my_orders |
| support-0245 | 2 | `a4de77edd8d21aad0b18e496a5fca8e8` | `7d643bcbcfcfee52a1a34620a8f403ef` | shopper | none |

Two setup runs from the instrumentation check are also in Workshop and are not part of this analysis: `a9cb26422387bcbac52f03966faac32f` (merchant probe) and `a4f345de2fa46d31d70cdbd09bb45ab7` (support probe, refund of order 4455).

## Candidate failures and unusual behaviors

### W1. Date reasoning without a reference date (new candidate)

The system prompt (`agent/agent.py::SYSTEM_PROMPT_TEMPLATE`) contains no current date. The seeded world is "as of 2026-07-01" (`seed/generate.py::WORLD_ASOF`, and the refund tool uses `db.world_asof`). The model fills the gap with its own idea of today, and the replies inherit that assumption.

- support-0054, replay run `4bda20cc...`: `get_store_policy` returned a 45 day window for Northwind Books, `get_order` returned `refund_eligible: true` for order 961 delivered 2026-05-28. The final reply computed the deadline as July 12, 2026 and stated the order "is past the normal return window", contradicting the tool. The original trace hedged instead ("the normal return deadline would be July 12 ... the order system is currently showing this order as refund-eligible"), which is the same missing-date problem surfacing as a self-contradiction rather than a wrong claim.
- support-0230, replay run `9645a5df...` and the original trace: deadline July 23, 2026 declared passed, and offered as the reason the order is not refund eligible. From the world date the deadline is three weeks away. The record's `refund_eligible: false` comes from somewhere else (see W6).
- support-0245 turn 1, original trace `fe28adae...`: the shopper says "about six weeks ago"; order 421 was ordered 2026-05-12, which is seven weeks before 2026-07-01. The reply says "That's not about six weeks ago from today" and speculates the order may be under another account. The replay (`760e740d...`) made the same mismatch claim in softer words.

Likely product change: put the world date in the prompt (it is already in the database) and require date claims to be made relative to it. Requirement source: RESP-3 covers inventing a value; a reviewer may prefer a new requirement, since the invented value here is "today".

### W2. Help-center ranking pushes the agent into repeated lookups and guessed identifiers

`search_help_center` often ranks the wrong document first for return-window questions, and the agent compensates with more calls.

- support-0230 (`9645a5df...`): two searches ("returns return window days delivered", then "Cartwheel platform default 30 days returns policy") both returned store override policies (Meridian Cycles, Northwind Books) ahead of `cw-returns`. The agent then called `get_policy("cw-returns")` after saying it would "try fetching the general Cartwheel returns policy directly by its likely policy id". The guess worked because identifiers are predictable, but the path is fragile.
- support-0152 (`d857aece...`) and support-0052 (`b0b2ef1c...`): a query containing "refund eligibility" ranked `cw-refunds` first, so the agent fetched `cw-refunds`, found it did not answer the return-window question, searched again and fetched `cw-returns`. Four policy calls for one rule.
- support-0011 turn 0 (`b1b0d514...`): "no longer needed" ranked `cw-cancellations` first for a delivered item.

Relevance to the taxonomy: `redundant_policy_lookup` currently reads as agent behavior. Several of these repeats are caused by retrieval ranking, and the product change (rank platform policies above store overrides, or return full bodies) is different from a prompt change. Consider stating in the mode's boundary whether retrieval-caused repeats count.

### W3. `find_order` and `list_my_orders` omit titles and store names, so the agent fans out

Confirms the tool-design backlog item from axial pass 3 with span-level evidence.

- support-0011 turn 0 (`b1b0d514...`) and support-0245 turn 0 (`4535889...`): after `find_order` returned two rows, the agent called `get_order` on each. Diffing the payloads, the only new field is `store_name`.
- support-0011 turn 1 (`f7a70447...`): "It's the midnight one" led to `find_order("midnight pitcher")`, which returned three orders (including a cancelled one from another store) with no titles, then `search_products("midnight pitcher", store="Blue Heron Ceramics")` to learn that product 20 is the Midnight Pitcher, then the refund.
- support-0054 (`4bda20cc...`): `get_order` after `find_order` for the same reason.

Not proposed as a mode. Product change is in the tool schema.

### W4. Escalation when the record and policy already resolve the request

- support-0052: the original trace opened ticket 164 in turn 0 ("in case there are special circumstances"); the replay opened ticket 151 in turn 1 after the shopper insisted. Order 28 was delivered 2026-03-23, months outside a 30 day window with no override. ESC-3 covers requests the agent cannot resolve from the help center and the order record; this one is resolved by both. Candidate positive for `unwarranted_escalation`. The turn of escalation moves between runs, the escalation itself is stable.
- support-0245 turn 0 (`4535889...`): ticket 153 opened before the shopper identified which order they meant. Already open-coded by the human reviewer; Workshop adds that the ticket context lists both candidate orders, so the human agent inherits the ambiguity.
- Contrast: support-0097 (`e9d46b5e...`) got `queued_for_approval` from `issue_refund` and did not open a ticket, which matches ESC-1 (the tool queues, the agent explains). The support probe run `a4f345de...` for order 4455 did both: `issue_refund` queued the refund and then `escalate_to_human` opened ticket 206 for the same refund. Suggested Part D search: traces where `issue_refund` returns `queued_for_approval` and `escalate_to_human` follows in the same turn.

### W5. Writes without an explicit yes reproduce exactly

- support-0176 (`fc19856a...`): "I think I need to cancel it" led to `get_order` then `cancel_order` with no question in between, identical to the original.
- support-0011 turn 1 (`f7a70447...`): turn 0 had asked for the literal reply "Yes, refund order #3167"; the shopper answered "It's the midnight one" and the agent treated that as consent.
- support-0097 (`e9d46b5e...`): support role, id supplied, `issue_refund` immediately. Under the widened RESP-6 this is a positive.

No new information beyond confirming the behavior is deterministic enough to be worth a code check on the tool call sequence.

### W6. The same anomalous order is handled two ways

Order 8001 (Harbor Knits) is a seeded inconsistent record: ordered 2025-01-14, shipped 2026-06-25, delivered 2026-06-23.

- support-0152 (`d857aece...`): the agent noticed ("shipped_at is after delivered_at" appears in the escalation context) and escalated under ESC-3.
- support-0230 (`9645a5df...`) and its original: the same record was fetched, the inconsistency was not mentioned, and the reply supplied a different reason for ineligibility (W1).

### W7. Smaller observations

- support-0117 (`b3a224b7...`): `search_products` returned four listings all titled "Heavy-Duty Vase" at $9.00, $134.75, $281.00 and $298.00, and the reply printed internal product ids to a shopper. Same family as the raw-identifier finding behind the RESP-1 revision.
- support-0169 (`3b0caec5...`): a single `get_order` and a field-by-field dump to support staff, then "this may need a human review" without opening a ticket or asking what the customer expected. Nothing beyond the existing open code.
- support-0052 turn 2 and support-0245 turn 2: no tool calls, 292 and 541 output tokens restating the previous turn. Consistent with `verbose_reply`.
- support-0230: the reply opens with a joke about laundry and an emoji. Consistent with the tone note already recorded.

## One case with uncertainty or an alternative explanation

support-0230, original trace `3a50b2ad...`, replay run `9645a5df...`. The reply says the return window "has passed" and that this "lines up with" the order showing as not refund eligible.

- Reading A (failure): the agent asserted a date fact it cannot know, and used it to invent the reason for a tool result. From the world date the window is open, and the real reason is the anomalous record. RESP-3 applies.
- Reading B (not a failure of the agent): the eligibility flag is authoritative and the reply reports it correctly; the sentence about the window is an unsupported gloss, and the shopper asked how returns work, not whether this order is eligible. The record anomaly was not material to the question, so not flagging it (unlike 0152) is defensible.
- What decides it: a specification decision. If the agent should have a reference date (prompt change) and must make date claims relative to it, A holds and W1 becomes a mode. If the agent is only required to report tool results faithfully, B holds and W1 collapses into "do not explain a tool result with a reason the tool did not give", which is closer to the existing RESP-3.

## Decisions on Workshop suggestions

Filled in by the human reviewer during Part D. The five per-trace suggestions are also queued as pending agent suggestions in `analysis/state/suggestions.json` (W1: support-0054, support-0230, support-0245 turn 1; W2: support-0230; W4: support-0052).

| Suggestion | Decision (accept / revise / reject) | Reason |
|---|---|---|
| W1 date reasoning without a reference date | accepted (all three traces, 2026-09-20) | Reviewer accepted the observations on 0054, 0230 and 0245 turn 1. Recorded as candidate mode `no_reference_date` in `patterns.json`; whether it becomes a ninth final mode or stays a SPEC revision (world date in the prompt) is still open because of the 8-mode cap. |
| W2 retrieval-caused repeats, boundary of `redundant_policy_lookup` | rejected (2026-09-20) | Reviewer: "cw-returns was ranked first, it was just retrieved again to get the full text, which is a separate mode." Open follow-up: this reading conflicts with clause 1 of the mode's definition; to be reconciled before Part E labels for that mode. |
| W3 `find_order` fan-out (tool design, not a mode) | no suggestion queued | Consistent with the tool-design backlog decision from axial pass 3; not used in the taxonomy. |
| W4 support-0052 as `unwarranted_escalation` positive; queued-refund-plus-ticket search | accepted for 0052 (2026-09-20) | Added as a positive. The queued-refund-plus-ticket search was not run; noted as a Part D or HW5 candidate. |
| W5 write without confirmation reproduces | no suggestion queued | Confirms the existing mode; the deterministic search that followed found 51 writes and no confirmed exchange. |
| W6 inconsistent handling of the anomalous record | folded into W1 | The 0230 observation carries this; no separate suggestion. |
