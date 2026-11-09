# Cartwheel trace review

Run from the repository root:

```bash
uv run python -m analysis.review_app.server
```

Open **http://127.0.0.1:8021**. The server reads `LANGFUSE_HOST`,
`LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` from the existing `.env`.
Credentials stay on the server. No model calls are made by this application.

At startup it paginates the live project and loads complete records carrying
`cartwheel.scenario_id`. It groups them by `cartwheel.session_id`, rather than
the nullable Langfuse `sessionId` or a scenario ID reused across runs. Restart
the server to include newly recorded traces. Missing session IDs remain separate.

## Review workflow

1. Choose a conversation from the sidebar. Read its messages in chronological
   order without numbered turn headings or action bars interrupting the content.
   Each message group retains its own trace identity for annotations and scores.
   Sidebar entries show the scenario, role, trace count and review status without
   repeating the user's request. Each conversation has its own bordered cell;
   shopper, merchant and support roles use distinct labeled color badges.
   The prominent top navigation provides Review, Label, Taxonomy and Progress.
   The palette pairs black navigation with slate blue controls, cool gray surfaces,
   teal agent accents and muted bronze tools; role colors retain their distinct meanings.
   Navigation and the conversation header stay fixed while the reading pane
   scrolls from the system instructions downward. The sidebar scrolls separately;
   on small screens its cells form a horizontal strip. Body text uses 16px and
   secondary labels use a consistent 14px.
   The compact header places the role beside the scenario name, with session
   and model details below. User messages use blue outer bubbles, agent messages
   green, and tool calls brown. All three contain matching white inner bubbles.
   Intermediate
   agent text is italic and labeled **Agent (In-between)**; the final response
   to each user request is labeled **Agent (Final)**.
2. Select text to write an evidence note. A temporary highlight remains visible
   while a compact pop-up appears beneath the selection, showing the quote and
   a text box. Enter saves, Shift+Enter adds a line, and Escape closes without
   saving. Unsaved drafts are backed up
   in this browser and offered on reload.
3. Stop initial reading at the first failure, then open **Progress** and choose
   **First failure noted** for the relevant trace in **Current conversation
   review**. If you find none, choose **No failure observed**. Saving a note
   alone does not mark a trace reviewed. **Reopen** resets that review status.
4. After open coding, use **Taxonomy** to record binary definitions, requirement
   references, boundaries, examples and supporting human observations. Explicitly
   confirm final modes before using **Label**.
5. In **Label**, record Present (1) or Absent (0) for each trace and final mode.
   Unreviewed cells are not interpreted as Absent. Each explicit decision is
   saved locally before a synchronous Langfuse score write and readback.
6. Use **Progress** to see distinct traces reviewed, missing judgments, pending
   synchronization, and AI suggestions. Accepting a suggestion creates a
   human-confirmed note with AI provenance; it never silently creates a label.

This is a project inventory, not the four homework sampling batches. The student
still chooses the review batches and makes all assessments and taxonomy decisions.

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
uv run pytest tests/test_review_app.py tests/test_normalization_metadata.py -q
node --check analysis/review_app/app.js
```

Browser checks should use a temporary `--state-dir`, so synthetic test notes and
labels never become student assessments or project scores.

For a fully offline run of the repository suite, prevent the existing `.env`
loader from enabling the live trace source:

```bash
LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= LANGFUSE_HOST= uv run pytest -q
```

Observed result during implementation: 175 passed, 4 skipped, 18 xfailed and
9 xpassed. With live credentials enabled, one existing demo-count assertion
expected 500 records but received the 364 live scenario traces instead.
