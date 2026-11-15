# Review interface comparison

The student approved the session-based proposal after inspection of ten full
live traces across seven sessions in the Cartwheel Dev project. The sample
included shopper, merchant and support roles; multi-turn clarification and
cancellation conversations; policy retrieval; an above-threshold refund;
a missing product title; an authorization refusal; and an out-of-scope request.
These inspections established the display structure, not human failure labels.

**Retained from the reference:** tool calls and their structured results share a
container, and selected evidence connects to readable margin notes. Role labels
and color distinguish user, assistant and tool content. AI suggestions remain
separate until explicitly accepted or rejected.

**Changed after inspecting live traces:** navigation groups traces by
`metadata.attributes["cartwheel.session_id"]`, because the top-level Langfuse
`sessionId` was null in the sample. Turns retain individual trace IDs and appear
chronologically. Generation outputs supply intermediate messages; accumulated
model inputs and duplicate final output are not repeated. Matching uses call
identity when captured, otherwise unique tool name and arguments, rather than
the reference UI's adjacency-only pairing. Collapsed tool summaries retain the
tool name and result status; expanding reveals Arguments and Complete result
in full, without nested disclosure controls. Retrieval evidence remains inside the complete result,
and execution metadata remains in Progress's raw trace details. Complete typed JSON
and raw execution remain available. Following the student's visual reference,
selected evidence opens a compact nonmodal pop-up with a quoted excerpt, a text
box, and keyboard save/cancel controls. The evidence stays highlighted while editing.
The reading view now flows without numbered turn headings, trace metadata, or
review controls between messages. A single system-instructions disclosure at
the start contains the distinct captured versions. Review controls and raw
trace details live in Progress. The sidebar lists scenario, role, trace count and
review status without filters or request previews,
and larger proportional text improves readability.
Each sidebar conversation is a bordered cell. Shopper, merchant and support have
distinct labeled color badges, and a dark top bar emphasizes Review, Label,
Taxonomy and Progress. Successful `ok` flags are omitted from tool headings.
The navigation, conversation metadata and role legend remain fixed
above the independently scrolling reading pane, which begins with system
instructions. Body text and secondary labels use a consistent 16px/14px scale.
The compact header puts the role beside the scenario name and omits review
instructions. User, agent and tool messages have terracotta, taupe and brown outer
bubbles respectively, each with a matching white inner bubble. Intermediate agent messages are
italic and labeled Agent (In-between); the final response to each request is
labeled Agent (Final).

The new interface also separates free-text open coding from a later binary
labeling view. Explicit completion distinguishes no failure observed from
unreviewed. Final taxonomy definitions link to human-selected supporting notes.
Progress counts individual traces and missing trace/mode judgments. Accepted
binary decisions have resumable, idempotent Langfuse synchronization and a
separate local mirror under `analysis/state/review_app.json`.

**Remaining limitation:** only captured evidence can be displayed. Uncaptured
content and ambiguous tool matches are flagged; the interface cannot reconstruct
them reliably. Overlapping highlights retain both notes but display one highlight
at a time. The inventory is a startup snapshot; restart to load new traces.

**Observed verification:** the live project loaded 364 scenario-bearing traces
in 280 conversations from 373 total project records. Browser checks exercised
three-turn grouping, anchored notes, escaped trace content, supporting taxonomy
notes, absent labels, pending synchronization, reload persistence, suggestion
accept/reject controls, progress and mobile layout. All synthetic mutations used
temporary offline state; live verification performed reads only. No new model
calls or student assessments were generated. The student's standard Langfuse
view comparison, human review, final taxonomy and video remain pending.
