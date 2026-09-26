# Interface comparison

## Retained from the reference

The overall Gestalt encoding and annotation mechanics: color hue per message
role, opacity for boilerplate, a shared bordered container grouping a tool
call with its result, the select-text popover with a pending-highlight span,
and margin notes with hover-linking instead of tooltips. These already match
what the traces need and there was no reason to redo them. The server API
contract (`analysis/server.py`'s file-backed routes) was also kept unchanged
— it's generic enough that nothing about our specific trace shape required
touching it.

## Changed after inspecting our traces

1. **Turn dividers.** `normalize_traces` already merges same-`scenario_id`
   traces into one flat message list, but the reference rendered that list
   with no indication of where one API turn ends and the next begins. A
   real reviewer scrolling a merged multi-turn trace could not tell it
   apart from one long single turn. Since every original API call begins
   with exactly one `user` message, we use that as a natural turn boundary
   and render a labeled "Turn N" divider before each one.
2. **"No failure observed" control.** Open coding needs a way to mark a
   trace reviewed-and-clean, distinct from not-yet-reviewed. The reference
   only supported inline span annotation, which has nothing to attach to
   when there's no failure to highlight. Added a header button that writes
   a `no_failure: true` annotation instead.
3. **Real extra-metadata panel.** The reference read `exp.order`,
   `exp.store_override`, and `exp.data_error` — fields that don't exist
   anywhere in our actual scenario schema (`tuple`, `expected`,
   `data_quality_case_id`); dead code from an earlier trace shape. We
   precompute a `scenario_id -> {tuple, expected}` lookup from our own
   `scenarios/*.jsonl` files and join it in, so the reviewer actually sees
   the grounding (order id, applicable policy, difficulty, the expected
   outcome text and its source) for scenario-linked traces.

## Remaining limitation

Turn/session grouping relies on `cartwheel.scenario_id` (via the shared
`normalize_traces` helper), not `cartwheel.session_id` as the handout
literally names. For every HW3 scenario trace these are equivalent — one
session per scenario run — so the 250-scenario review population is
unaffected. But any multi-turn conversation *without* a `scenario_id` (e.g.
ad-hoc manual CLI testing from HW1/HW2) would not be merged by this
pipeline, since it only groups on `scenario_id`. Fixing this properly would
mean either patching the shared `normalize_traces` helper to also merge on
`cartwheel.session_id` when `scenario_id` is absent, or writing a second,
separate merge pass in our own server before samples reach the UI — we
chose not to do either, since it's out of scope for the traces this
homework's review population actually consists of.
