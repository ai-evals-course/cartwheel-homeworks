# Cartwheel trace review

Run from the repository root:

```bash
uv run python -m analysis.review_app.server
```

Open **http://127.0.0.1:8021**. The server reads `LANGFUSE_HOST`,
`LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` from the existing `.env`.
Credentials stay on the server. No model calls are made by this application.

Live trace reads allow 30 seconds per request and retry network failures up to
three attempts. For a slow Langfuse instance, increase the timeout:

```bash
uv run python -m analysis.review_app.server --langfuse-timeout 60
```

If reads still fail, check that the configured `LANGFUSE_HOST` is reachable and
Langfuse is running. An existing full trace export can be opened explicitly with
`--source` as described below; the app never silently switches to offline data.

At startup it paginates the live project and loads complete records carrying
`cartwheel.scenario_id`. It groups them by `cartwheel.session_id`, rather than
the nullable Langfuse `sessionId` or a scenario ID reused across runs. Restart
the server to include newly recorded traces. Missing session IDs remain separate.

## Review workflow

The compact search beside **Conversations** matches full or partial run/trace,
session, or scenario IDs (for example `support-0140`), ignoring case. It searches
all turns of each conversation within the current sampling filters and keeps
the full conversation available. Clear the field or press Escape to reset it.

1. Choose a conversation from the sidebar. Read its messages in chronological
   order without numbered turn headings or action bars interrupting the content.
   Each message group retains its own trace identity for annotations and scores.
   Sidebar entries show the scenario, role, trace count and review status without
   repeating the user's request. Each conversation has its own bordered cell;
   shopper, merchant and support roles use distinct labeled color badges.
   The prominent top navigation provides Review, Taxonomy, Label, Evaluator and Progress.
   The palette pairs black navigation with terracotta controls, warm neutral surfaces,
   taupe agent accents and muted bronze tools; role colors retain their distinct meanings.
   Navigation and the conversation header stay fixed while the reading pane
   scrolls from the system instructions downward. The sidebar scrolls separately;
   on small screens its cells form a horizontal strip. Body text uses 16px and
   secondary labels use a consistent 14px.
   The compact header places the role beside the scenario name, with session
   and model details below. User messages use terracotta outer bubbles, agent messages
   taupe, and tool calls brown. All three contain matching white inner bubbles.
   Intermediate
   agent text is italic and labeled **Agent (In-between)**; the final response
   to each user request is labeled **Agent (Final)**.
2. Select text to write an evidence note. A temporary highlight remains visible
   while a compact pop-up appears beneath the selection, showing the quote and
   a text box. Enter saves, Shift+Enter adds a line, and Escape closes without
   saving. Unsaved drafts are backed up
   in this browser and offered on reload.
3. Use **For review** beneath the role legend to mark the conversation's traces
   **Reviewed**. This saves completion locally and preserves existing assessments.
   Saving a comment automatically marks its trace reviewed, and a conversation
   containing a comment shows **Reviewed** beneath the legend. Existing saved
   comments receive the same completion status when the server starts; other
   uncommented turns are counted individually in Progress.
   Press **Space** in the reading view to toggle **For review / Reviewed**.
   Conversations with comments stay reviewed. The shortcut is inactive while
   editing a comment or using an input, button, or other interactive control.
   Use **Reopen** in Progress to reset an individual trace. For HW4's explicit
   outcome record, stop initial reading at the first failure, then open **Progress** and choose
   **First failure noted** for the relevant trace in **Current conversation
   review**. If you find none, choose **No failure observed**. Saving a note
   alone does not mark a trace reviewed. **Reopen** resets that review status.
4. After open coding, use **Taxonomy** to record binary definitions, requirement
   references, boundaries, examples and supporting human observations. Explicitly
   confirm final modes before using **Label**.
5. In **Label**, record Present (1) or Absent (0) for each trace and final mode.
   Unreviewed cells are not interpreted as Absent. Each explicit decision is
   saved locally before a synchronous Langfuse score write and readback.
6. Open **Evaluator** between Label and Progress to inspect saved HW5 artifacts.
   This full-width view hides the conversation sidebar and header. Each failure
   mode has its own card with a brief definition, training/validation/test
   split table, and validation/test results table. The judge prompt is visible
   in the left column; the split table sits above the results in the right
   column. The columns stack on narrower screens. The split table shows
   Pass and Fail counts and planned shares.
   Select a judge version to see separate validation and test confusion
   matrices (judge verdicts on rows, human labels on columns), with TPR and TNR
   in a results table below. The saved prompt stays alongside these results,
   with its version and last seven SHA-256 characters in the heading. Results are
   read from `analysis/state/judges/` and `analysis/report/`; labels and splits
   come from `hw5_labels/` and `splits.json`. The `--state-dir` override applies
   to these artifacts too, with reports read from its sibling `report/` folder.
   Opening **Evaluator** rereads saved artifacts without running a judge or changing
   labels. Missing runs show Pending, and test results stay locked until their
   judge is frozen. The original HW4 labeling view remains separate from the
   confirmed HW5 export (HW5 uses 1 = Pass and 0 = Fail).
   **Show traces** beside the Validation confusion matrix opens a modal trace
   browser. It starts with validation disagreements and can switch to all
   validation traces. Browse one run at a time with **Previous / Next** or
   Left/Right arrow keys. The run ID has Judge and Human verdict badges beside
   it; the saved critique, conversation history, tool evidence, and highlighted
   final reply appear below. **Close** or Escape returns focus to the button.
   Under **Judge critique**, use **Comment on judge critique** and **Save comment**
   to record your assessment. Comments persist per judge version and trace in
   `analysis/report/dev-<judge_id>.json` under `critique_comments`, keyed by trace
   ID (the report folder beside `--state-dir` when provided). Existing comments
   in the earlier `evaluator_comments.json` are preserved and imported on save.
   Edits preserve prior comments in history, and stale saves from another tab
   are rejected. Unsaved drafts are retained in browser storage while navigating
   or reopening the popup. Comments do not change your human labels or the
   judge's critique. This view reads fixed HW5 inputs and cached predictions;
   it never calls a model or serves test traces through its data endpoint.
7. Use **Progress** to see distinct traces reviewed, missing judgments, pending
   synchronization, and AI suggestions. Accepting a suggestion creates a
   human-confirmed note with AI provenance; it never silently creates a label.

This is a project inventory, not the four homework sampling batches. The student
still chooses the review batches and makes all assessments and taxonomy decisions.

In **Sampling → Dimension**, the arrow beside each dimension opens its values.
Select one or more values; selected values appear beneath the dimension.
Values come from the matching `scenarios/support_scenarios.jsonl` tuple, with
authenticated role taken from trace metadata when available. Unknown values
are not inferred. With no values selected, a checked dimension includes all its
known values. Multiple values within a dimension are alternatives; multiple
dimensions must all match. Dimension filters search the full trace inventory,
including traces in Uniform or Clustered batches and traces outside the saved
sample manifest. Uniform and Clustered add their saved batches independently. A matching
trace displays its entire session for context. Filtering does not change the
sample manifest or saved judgments. On narrow screens, value choices expand
inline to stay within the viewport. Restart the server and refresh the page
after updating to load the dimension metadata and controls.

Expand **Dimensions** beneath the conversation heading to inspect its role,
intent, record, policy, difficulty and other scenario values. If values differ
across traces in a session, all distinct values appear. Missing metadata is
shown as **Not available**. While sampling is enabled, the queue count reports
matching traces and conversations. Dimension matches are included regardless
of their sampling batch; each matching conversation appears only once.

## Evidence and storage

Generation outputs supply intermediate assistant messages. Structured `TOOL`
observations supply arguments and results. Accumulated model inputs and repeated
root output are not replayed as additional turns. Raw payloads remain available.
Tool calls match by explicit call ID where captured, or unique name and arguments;
ambiguous matches are flagged. Identity-specific system instructions are expandable.
One system-instructions disclosure at the start includes each distinct captured
version across the conversation. Raw traces, IDs, timing, costs, prompt versions
and Langfuse links are available in Progress under each trace's details.
Tool calls start collapsed with the tool name and any error or action status visible;
successful `ok` flags are not repeated beside the name. Expand
the call to reveal Arguments and Complete result in full, with no additional
expansion needed.
The interface calls assistant messages **Agent**. A tool call sits inside a
**Tool** bubble with pale brown styling; the nested tool bubble is white,
including the tool name, arguments and complete result, with a brown accent.
The complete result includes retrieval evidence and all original fields.
Execution metadata stays in Progress's raw trace details. Disclosure choices
survive note saves.

The separate `analysis/state/review_app.json` holds human notes, review completion,
taxonomy decisions, suggestion decisions and binary judgments. Prior label edits
remain in each judgment's history. `patterns.json` and `suggestions.json` are read
as helper output; imported modes start provisional. Existing `annotations.json`
records are shown read-only beside matching traces. Existing files are not rewritten.

Langfuse is canonical for accepted binary scores. The score name is the mode ID;
one stable score ID per trace and mode makes retries idempotent. A failed write or
readback remains **sync pending** locally. **Retry sync** resends pending decisions.
The SDK client and trace-ID helpers come from `analysis/helpers/langfuse_io.py`.

The server is for a single local reviewer. It binds to loopback, checks Host and
Origin, restricts JSON writes, and serves scripts/styles locally. Trace text is
rendered as text, never interpreted as HTML. It does not execute agent tools.

## Offline demonstration and testing

Use an existing full trace export only when live Langfuse is unavailable. Record
the reason in your interface comparison. Offline mode is always explicit:

```bash
uv run python -m analysis.review_app.server \
  --source traces/support_traces.json \
  --state-dir /tmp/cartwheel-review-demo --port 8022
```

Offline labels remain pending and are never sent to Langfuse. To synchronize
later, restart in live mode with the same `--state-dir` and choose **Retry sync**.
Stable trace IDs must exist in the configured project. Do not run multiple server
processes against the same state directory. Tabs in one process use revision
checks to prevent overwriting each other's changes.

```bash
uv run pytest tests/test_review_app.py tests/test_review_evaluator.py tests/test_normalization_metadata.py -q
node --check analysis/review_app/app.js
node --check analysis/review_app/evaluator.js
```

Browser checks should use a temporary `--state-dir`, so synthetic test notes and
labels never become student assessments or project scores.

## Additional-instance retrieval

The Agent suggestions tab reads `analysis/state/suggestions.json`. It supports
group filtering, row selection, select all within the visible group, and bulk
accept/reject. Retrieval matches remain suggestions until a human reviews them.
Accepting creates an evidence note; it does not assign a binary failure label.
There is no mock-data fallback when the queue is empty.

Search an existing full trace export with:

```bash
uv run python -m analysis.search_suggestions --mode unsupported_policy_answer
```

This requires a confirmed mode by default. To search draft definitions with the
student's agreement, add `--include-provisional`; omit `--mode` to search all
eligible modes. Searches exclude each mode's originating traces and previous
suggestions, preserve existing suggestions and decisions, and queue at most
five additional candidates per mode. Each candidate records its exact evidence
anchor and retrieval rationale. Counts are retrieval results, not failure
counts or prevalence estimates. Human annotations, labels, and final-mode
settings are not changed. Read the generated search report under
`analysis/report/` for the source snapshot and search coverage.

Use `--all-matches` to remove the five-per-mode cap and queue every additional
match from the full supplied export. The search report records the exact trace
IDs scanned. This does not establish coverage of newer live-project traces.

For a fully offline run of the repository suite, prevent the existing `.env`
loader from enabling the live trace source:

```bash
LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= LANGFUSE_HOST= uv run pytest -q
```

Observed result during implementation: 175 passed, 4 skipped, 18 xfailed and
9 xpassed. With live credentials enabled, one existing demo-count assertion
expected 500 records but received the 364 live scenario traces instead.
