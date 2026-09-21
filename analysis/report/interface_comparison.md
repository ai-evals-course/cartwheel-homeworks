# Interface comparison

My review interface lives in `analysis/review_app/`. The reference (`analysis/server.py`, `analysis/ui/index.html`) was read for ideas, not reused.

## Friction in the standard Langfuse view

Notes from reviewing 5 to 10 traces in Langfuse before designing anything:

- Tool calls and results require a bunch of clicking, so it's hard to view what happens in one view from user input through to tool calls / other steps to the result.
- Can't annotate inline by highlighting text.
- Need to click into tool calls to see the input and output. Output also often requires extra clicks.
- No metadata about expected results when opening a trace. Need to scroll a lot to find metadata like the user_role and summary of the source tuple / inspiration for the scenario, and challenge scenarios aren't visually obvious.
- Annotations: I can't even figure out how to annotate, and it requires popping up another screen, closing it, selecting another trace. Efficiency and hotkeys to go to the next trace would be great.

## Retained from the reference

- The file-backed JSON API shape (`/api/annotations`, `/api/patterns`, `/api/suggestions` mirrored to `analysis/state/`), and the rule that only a mode plus a 0/1 label becomes a Langfuse score. Free-text open codes stay local.
- The design of the reasoning blocks is similar.
- Highlighting of outliers (this trace is top 5% of tool calls, etc).

## Changed after inspecting my traces

- One view from user input through tool calls to the reply, no clicking.
- Annotate inline by highlighting text.
- Tool input and output on one row, expand only if I want more.
- Scenario metadata and expected result always visible in the header. Challenge scenarios get a badge.
- Annotations happen in the same screen, hotkeys to go to the next trace.

Also: traces are grouped by `cartwheel.scenario_id` with every trace id kept, because no trace carries `cartwheel.session_id` (see `homework/module-2/hw4-progress.md`).

## Remaining limitation

- The UI is a little busy for my taste. I may simplify it further as I use this thing.
- Pairing a tool call to its result relies on (tool name, arguments) being unique within a trace. True for this dataset, not in general.
