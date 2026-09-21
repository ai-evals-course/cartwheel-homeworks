# HW4 progress

Working notes for `hw4.md`. Checklist follows the handout order. Decisions are short; the reasoning lives in the report files under `analysis/report/`.

## Checklist

### Preparation
- [x] Confirm Langfuse is running and holds the Module 1 traces (2026-09-18)
- [x] Skip `hw3-reference.patch` (own HW3 traces exist)
- [x] Add `cartwheel.session_id` to the root span in `server/app.py` (future runs only)

### Part A, review interface
- [x] Review 5 to 10 traces in the standard Langfuse view, note friction (2026-09-18)
  - [x] tool calls and results require a bunch of clicking, so it's hard to view what happens in one view from user input through to tool calls / other steps to the result.
  - [x] Can't annotate inline by highlighting text
  - [x] Need to click into tool calls to see the inot and output - outout also often requires extra clicks
  - [x] No metadata showing about expected results when opening a trace, need to scroll a lot to find metadata like the user_role and summary of the source tuple/inspiration for the scenario, and challenge scenarios aren't visually obvious
  - [x] annotations - I can't even figure out how to annotate, and it requires popping up another screen, closing it, selecting a nother trace. Efficienty and hoteksy to go to the next trace would be great.
- [x] Coding agent inspects 5 to 10 traces and proposes a visual organization
- [x] Approve the proposal
- [x] Build `analysis/review_app/` (server + single-page UI, smoke-tested, visually checked, revised after feedback)
- [x] Write `analysis/report/interface_comparison.md` (retained, changed, limitation)

### Part B, review 100+ traces (open coding, then axial coding after each batch)
- [x] Batch 1: 15 uniform + 15 cluster representatives
  - [x] `batch1_uniform` (15) reviewed 2026-09-18: 30 open codes, 1 no-failure
  - [x] `batch1_clusters` (15) drawn (k-means on tool calls, turns, log reply length, intent); reviewed; its 18 annotations folded into the taxonomy 2026-09-20 (missed in axial passes 2 and 3)
  - [x] Axial pass 1 decisions resolved 2026-09-19: RESP-1 revised (cite by title + link), RESP-6 added (confirm order before writes when no id given), SCOPE-1 revised (shopping goes to the app), verbose split into restates_itself + verbose_reply. Reasoning-block notes kept as cost observations (Thinking blocks are not user-visible).
- [x] Batch 2: pick one product dimension before looking at outcomes, 30 traces across its values
  - [x] Dimension: **intent**. `batch2_intent` (30 conv / 32 traces) drawn, equal-ish quotas across the nine intents
  - [x] Reviewed 2026-09-19: 36 annotations, 7 no-failure
  - [x] Axial pass 2 over 45 conversations: 10 candidate modes + 1 held written to `patterns.json`; widgets, tool design and singletons parked
- [x] Batch 3: 25 traces from depth searches for candidate modes and close negatives
  - [x] `batch3_depth` (25 conv) drawn from deterministic signals on tool results and reply text; positives and close negatives for modes 1, 3b, 4, 5, 7. No `7_neg` hits: every platform-policy fetch in the pool went through a search first
  - [x] Reviewed 2026-09-20: 85 conversations total, 119 annotations
  - [x] Axial pass 3: taxonomy finalized at 8 modes (see decisions)
- [x] Batch 4: 15 uniform after drafting the taxonomy (stability check)
  - [x] `batch4_uniform` (15) drawn 2026-09-20 with the 8-mode draft recorded in the manifest; Part C and D follow Batch 4, per the handout order
  - [x] Reviewed 2026-09-20: 22 annotations, 5 no-failure. **1 previously unseen consequential mode** (`incomplete_write_outcome`, 0097, foreshadowed by 0140); taxonomy stable, no fifth batch. Review set: **100 conversations / 142 traces**.
- [x] Every reviewed trace has an open code or "no failure observed"
- [x] `analysis/state/sample_manifest.json` records which batch each trace belongs to (no trace in two batches)

### Part C, Raindrop Workshop
- [ ] Install Workshop, run `/instrument-agent` (keep OTel and Langfuse instrumentation)
- [ ] Inspect 5 to 10 runs across roles and tools
- [ ] Write `analysis/report/workshop_notes.md` (run ids, candidate failures, one uncertain case)
- [ ] Record accept / revise / reject for every Workshop suggestion used in the taxonomy

### Part D, taxonomy
- [x] 5 to 8 binary modes, each with: snake_case name, definition, 3+ positives, 3+ close negatives, originating annotations, boundary to nearest mode, evaluator type, requirement source (SPEC id or SPEC revision)
  - Final 8 (2026-09-20): write_without_confirmation, assumes_instead_of_asking, unwarranted_escalation, redundant_policy_lookup, irrelevant_policy_nuance, unsolicited_next_steps, verbose_reply, first_person_framing
  - Short on close negatives: redundant_policy_lookup, unsolicited_next_steps, verbose_reply, first_person_framing (0 each); first_person_framing has 2 positives. Batch 4 and the search step should supply these.
- [x] Merge / split by "would one product change fix both?" (restates_itself folded into verbose_reply; unnecessary + premature escalation merged as unwarranted_escalation; redundant lookups split from tool-design backlog)
- [ ] Compare with the AgentDebug taxonomy
- [ ] Agent-assisted search for one mode; review every hit; at least one rejected suggestion saved
- [x] Document one taxonomy revision (candidates: the unwarranted_escalation merge, or the support-role boundary on irrelevant_policy_nuance from 0204)
- [ ] Any `SPEC.md` revision, with the motivating annotation named in the review summary
  - [x] SPEC revised 2026-09-19: SCOPE-1 (shopping to app), RESP-1 (cite by title + link), RESP-6 new (confirm order before write); annotation ids recorded inline in SPEC.md, still to be named in review_summary.md

### Part E, apply the taxonomy
- [ ] One present / absent judgment per (trace, mode) pair
- [ ] Write accepted judgments to Langfuse as scores
- [ ] One label file per mode under `analysis/state/labels/`
- [ ] `analysis/report/review_summary.md` (sample size and composition, sample fractions per mode, new modes in the final 15, one taxonomy revision)
- [ ] Check HW5 readiness: 30 Pass and 30 Fail per mode, or plan synthetic scenarios

### Video (mine)
- [ ] Under 5 minutes, drive the interface and repo, cover the seven points in the handout

## Decisions

- **2026-09-18, review population.** Langfuse holds 361 `cartwheel.session_message` traces; the HW3 export holds 313 (all from the 2026-09-15 final run). The extra 48 are pilot and dev runs from 09-12 and 09-14, 9 of them with no scenario id. Review population = the 313 trace ids in `traces/support_traces.json`. Langfuse remains the annotation store.
- **2026-09-18, session grouping.** No trace carries `cartwheel.session_id` (HW2 never required it). Group by `cartwheel.scenario_id`, then order turns by timestamp. The HW3 runner opens one session per scenario, so this is faithful within the final run. Added `cartwheel.session_id` to the root span in `server/app.py` so future runs carry it; existing traces are unchanged. This is the "design changed after inspecting traces" item for `interface_comparison.md`.
- **2026-09-18, when to consult SPEC.md.** Open coding stays in plain words; no SPEC lookup during the first read. SPEC ids get attached during axial coding and taxonomy construction. A behavior with no requirement behind it gets a SPEC revision before it gets a label.
- **2026-09-18, interface.** Build a new UI rather than reusing `analysis/ui/index.html`. Keep the file-backed JSON API shape and the "only mode + 0/1 label becomes a Langfuse score" rule from the reference. Expected outcome / criterion is always visible in the header (chosen over a collapsed toggle; the speed matters more than the anchoring risk for this review). Open-coding efficiency: single-column timeline with tool call and result paired, select-to-annotate, hotkeys (`j`/`k`/`n`/`r`), progress strip.
- **2026-09-18, tool pairing.** TOOL observations carry no call id and results return out of order after parallel calls. Pair by (tool name, arguments); no trace in the set repeats an identical call, so this is exact here. Fallback: first unmatched call of the same name. Recorded as a limitation candidate for `interface_comparison.md`.
- **2026-09-18, get_store_policy.** The agent calls `get_store_policy` (HW1 addition) 78 times but SPEC.md's tool table stops at TOOL-9. Possible SPEC gap to revisit during axial coding.
- **2026-09-20, axial pass 3 decisions.** (a) `irrelevant_policy_nuance` applies to shopper and merchant callers only; support staff may see internal terms (`support-0204` becomes a close negative). (b) `restates_itself` folded back into `verbose_reply` to respect the 8-mode cap. (c) `find_order` fan-out (agent calls `get_order` on every match to learn titles) is a tool-design backlog item, not a mode. (d) Tone narrowed to `first_person_framing` and added as the 8th mode; `product_search_in_chat` dropped from the judged set and kept as the SCOPE-1 revision. `raw_policy_id_in_prose` recorded as systematic (fixed by the RESP-1 revision), not judged.
- **2026-09-20, Batch 4 decisions.** RESP-6 widened: confirm the order and the action before any `issue_refund`/`cancel_order`, every role, id supplied or not (`0167`, `0176`); former id-supplied close negatives (`0155`, `0243`, `0078`, `0140`, `0097`) become positives in Part E. `incomplete_write_outcome` (post-write reply omits status/timing; `0140`, `0097`) recorded as a backup mode, taxonomy stays at 8. `0152` is a close negative for `unwarranted_escalation`: reversed dates are an inconsistent record and ESC-3 requires the escalation.
