# Review interface: what was kept, what was changed, what is still missing

The standard trace view here is Arize Phoenix. Langfuse is what the assignment names, but
it runs in Docker and Docker could not be installed on this machine; Phoenix reads the same
OpenTelemetry spans. See `analysis/report/workshop_notes.md` for the full substitution
record.

The custom interface is `analysis/review_app/` — a stdlib HTTP server and one HTML page,
no dependencies, serving 261 conversations grouped by session.

Before building anything, a batch of traces was reviewed in Phoenix and the friction was
written down first (`.hw4-logs/standard-view-friction.md`). Each design decision below
answers one of those recorded observations rather than a guess about what might help.

## Retained from the standard view

**Spans as the unit of display, in execution order, with their raw arguments and results.**
This is the thing a trace viewer gets right and it was copied directly. Every judgment in
this analysis rests on comparing what a tool returned against what the reply then said,
and that comparison is only possible because the tool result is shown verbatim rather than
summarised. `contradicts_eligibility_flag` exists as a mode because `"refund_eligible":
false` was visible in the raw JSON next to a reply granting a refund. A view that
prettified tool output into prose would have hidden it.

**The scaffolding spans are kept, not deleted.** Of 2,854 spans, 885 are framework
plumbing. They are hidden behind a toggle rather than filtered out of the data, because
"the agent did nothing here" is occasionally the finding.

## Changed after inspecting the traces

### 1. Everything is open by default

*Observed:* Phoenix collapses every span. Reading one trace meant expanding up to 27 of
them one at a time, and the clicking dominated the reading.

*Changed:* every span renders expanded. Long tool results collapse to a summary line with
an expand control, and the 885 scaffolding spans hide behind a single toggle. The default
state is "readable"; collapsing is the thing you opt into.

*Effect:* a trace became something to scroll rather than something to excavate. This is the
change that made 102 traces feasible at all.

### 2. Notes attach to selected text and appear as margin notes

*Observed:* Phoenix's annotation control applies to the whole trace. But a failure lives at
a specific point — this tool result, that sentence — and open coding asks for a note on the
earliest failing step. A trace-level note cannot say where.

*Changed:* select any text and a note attaches to that selection. The highlight stays in
the reply; the note renders in a right-hand margin column, vertically aligned with what it
marks. Hovering either one outlines the other.

*Why it mattered more than expected:* several conversations carry many distinct failures.
support-0025 and support-0063 have ten annotations each, support-0028 has eight. Under
trace-level annotation those would have collapsed into one paragraph apiece, and the axial
coding that produced the eight modes works by grouping *notes*, not traces. Trace-level
annotation would have destroyed the input to the next step.

*A deliberate omission:* there are no dropdowns, no severity scales and no structured
forms. Notes are free text only. This was a direct instruction from the reviewer — "I just
want it to allow for 'in my own words' write-ups" — and it is also what open coding
requires. A dropdown of pre-written categories at this stage would have produced the
categories it was seeded with. The categories had to come out of the notes.

### 3. The expected outcome is pinned beside the trace

*Observed:* judging whether behaviour was wrong needs the scenario's expected outcome and
its source. Phoenix has no idea those exist, so every comparison meant leaving the view and
looking the scenario up by hand.

*Changed:* a third column pins the expected outcome, its ground-truth source (the SQL
query, the eligibility function, the policy document, the data-quality case) and the
governing `SPEC.md` requirement.

This is the one the standard viewer structurally cannot solve. Expected outcomes are
application knowledge, not tracing data; no general-purpose trace viewer can know that
order 8002 has a deliberately missing delivery date. It is also the column that made the
review defensible: it is the difference between "this reply feels wrong" and "this reply
contradicts a value computed in code."

### 4. Added during the review, not designed up front

Three things were requested by the reviewer partway through and added:

- **A progress bar and a completion state separate from notes.** A conversation can be
  finished-with-comments, clean, or not yet read — three different facts that were
  initially collapsed into two. `review_status.json` was split out from `annotations.json`
  so "reviewed and clean" stopped being indistinguishable from "not started".
- **Themes surfaced from the notes.** The progress tab summarises notes; the reviewer asked
  whether it could group them into emerging themes. This became the agent-suggestion
  pipeline below.
- **Filters that follow the work.** `nofailure`, `done`, `todo`, `noted`, `unnoted`,
  `denied`, `multi`, `missingtool`, `flagged`. Each was added when a specific question came
  up during review rather than anticipated.

### 5. Agent suggestions, marked as hypotheses and never as labels

A mechanical pass over all 261 conversations proposes candidates for a mode, each with its
grounding — the store's actual override from the database, the order total against the $100
threshold, the scenario's declared user style. They appear in the interface visually
distinct from human notes: dashed highlight, different border colour, an explicit tag, and
accept/dismiss buttons rather than edit/delete.

**Nothing an agent proposed became a label without the reviewer accepting it.** Across both
rounds, 60 candidates were put forward, 36 accepted and 24 rejected — and eleven of those
accepts were later reversed when a boundary revision reached back over earlier decisions.
The final round produced 33 candidates, 15 accepted and 18 rejected. The rejections were
the more useful half:

- Three rejections caught bugs in the heuristic rather than errors in judgment. support-0063
  was shortlisted for quoting the 30-day default while "Juniper Home Goods overrides to 14
  days" — but that conversation listed 17 orders and the code had picked the wrong store.
  The order under discussion was Harbor Knits, which has no override, so 30 days was
  correct.
- Five rejections in a row on the same heuristic rewrote a mode definition.
  `detail_level_ignores_the_ask` had been shortlisted on "terse user, long reply"; every
  such candidate was rejected and only the one about a decision stated without its basis
  accepted. Length is not the signal. A length-based judge would have been the obvious
  build for Homework 5 and the wrong one.

This is the design decision the whole approach rests on. A pipeline that wrote labels
directly would have recorded the wrong store for support-0063 as fact and shipped a
length-based definition into Homework 5.

## Remaining limitations

**No permalinks.** Phoenix serves from a local process and the review app from
`localhost:8030`. Neither URL means anything to anyone else, so every reference in these
reports is by scenario id. It works, but nobody can be sent a link to a specific finding.

**No cluster map.** The error-discovery skill specifies a 2D projection of all records with
sample and annotation state overlaid. This was not built: it needs scikit-learn or UMAP,
and the install path was the same one that blocked `uv` and Docker. Sampling used explicit
stratification on `record_state` instead, which is more legible but cannot show which
regions of the data were never visited.

**Scores are written to files, not to Langfuse.** Part E asks for each judgment to be
written to Langfuse as a score with a matching record under `analysis/state/labels/`. Only
the local record exists. The eight label files carry a `score_destination` field saying so
rather than leaving the absence implicit.

**Single reviewer, no agreement measure.** Every label is one person's. There is no second
annotator and so no inter-rater agreement, which means the boundary revisions documented in
the review summary rest on one reading. The closest substitute available was checking the
code rules against the human coding and investigating every disagreement — which is how the
`abandons_mid_task` misfiling was found, but it only works for the five modes a rule can
decide.

**The interface only shows what was exported.** Records come from a static
`records.json` built from the Homework 3 trace export. It does not connect to a live trace
store, so a conversation that failed to export cannot be reviewed here at all.
