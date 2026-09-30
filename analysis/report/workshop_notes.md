# Raindrop Workshop: why it was not used, and what was done instead

Part C of the handout points at [Raindrop Workshop](https://github.com/raindrop-ai/workshop)
as a tool for generating failure hypotheses across a trace set. It was not installed. This
records why, what replaced it, and what the replacement does and does not cover.

## Why it was not installed

The install path is `curl -fsSL https://raindrop.sh/install | bash` — piping a remote
script straight into a shell on a managed work laptop. The same pattern was declined
earlier in this course for `uv`, and the reasoning has not changed.

Three further properties made it the wrong thing to run here regardless of the install
mechanism:

1. It installs skills and an MCP server into the coding agent, changing the agent's own
   tool surface for every later task, not just this one.
2. On the cloud path it writes `RAINDROP_WRITE_KEY` into `./.env` — the same file holding
   the model API key for this project.
3. Interactive setup offers a connection to `app.raindrop.ai` that must be explicitly
   declined. Sending trace content to an external service is a publication step, and these
   traces contain seeded customer records and internal policy identifiers.

This is a documented gap, not a hidden one. `analysis/report/workshop_notes.md` is a
required commit file precisely so that skipping the tool means saying so.

## What Workshop does, and which part was reproduced

Workshop's role in the assignment is to read a body of traces mechanically and propose
failure hypotheses a human then judges. Two properties matter: it looks at **every** trace
rather than the ones a human happened to open, and its output is **hypotheses, not
labels**.

Both were reproduced with local tooling. Neither the model nor any external service was
involved; the substitutes are deterministic passes over data already on disk.

### The precedent from Homework 3

`.hw3-logs/triage.py` established the pattern. It was a mechanical pass over all 250
scenario results asking questions a human reading one trace at a time cannot — such as
"which conversations called `get_order` and returned an eligible flag but never called
`issue_refund`?" It caught pilot-0022, a refund failure that a manual shortlist review had
missed. That is the lesson Part C teaches, arrived at from the other direction.

### What was built for Homework 4

**`analysis/tools/label.py`** — a detector per failure mode, run over every reviewed trace. Five
of the eight modes have a rule that decides them; three do not, and the script says so
explicitly by returning "cannot decide" rather than guessing. Crucially the rules were
**validated against the reviewer's existing human coding before being trusted**, and every
disagreement was investigated rather than explained away. That check is what uncovered the
`abandons_mid_task` misfiling described in the review summary: eight disagreements, all
eight a misfiled trace rather than a broken rule.

**`analysis/tools/shortlist.py`** — candidate generation for the three modes no rule can decide.
Each heuristic is grounded in something checkable rather than in wording alone: the store's
`return_window_days_override` read from the database, the order total against the $100
threshold from `facts.yaml`, the scenario's declared `user_style`. Candidates are written
to `analysis/state/suggestions.json` and appear in the review interface as suggestions,
visually distinct from human notes, with accept and dismiss buttons.

**Depth searches over all 261 conversations** for each candidate mode, returning both
positives and close negatives — traces that look superficially like the mode but do not
contain it — so that a mode's boundary is tested rather than assumed.

## What the substitute caught that manual review had not

Three things, all of which changed the final taxonomy:

1. **`tool_call_malformed`.** 66 of 160 `search_products` calls across the full run send
   the literal string `"null"` for optional parameters and are rejected before reaching the
   application. The reviewer independently noticed it in three conversations; the
   mechanical pass showed it was not three conversations but a systematic argument-encoding
   fault, and the only tool-level failure among the eight modes.

2. **The scale of `cites_policy_by_internal_id`.** Human notes flagged it in 14
   conversations. A regex over every reply found it in 50 of the 102 reviewed traces —
   49%, the largest failure in the sample by a wide margin, and the one that motivates the
   `SPEC.md` revision.

3. **Two misfiled modes.** Described in full in the review summary. Only visible because a
   rule written from a definition disagreed with the labels filed under that definition.

## What the substitute does not cover

**No semantic clustering.** Workshop groups traces by meaning. The substitutes match
patterns — regexes, database joins, span statuses. A failure mode that has no lexical or
structural signature would not be proposed by any of this tooling, and there is no way to
know from inside the method how many such modes exist. The mitigation was the batch-2 and
batch-4 uniform random samples, read without any search guiding attention: batch 4 produced
zero new modes, which is evidence but not proof.

**No cross-dataset priors.** Workshop brings failure categories observed elsewhere. The
substitute for this was the AgentDebug comparison in the review summary, which is a
published taxonomy rather than a tool, and which tested two of its categories against this
data and found both genuinely absent.

**No independent judgment.** Everything here was written by the same agent helping with the
analysis, against a taxonomy that agent helped shape. A heuristic that encodes a
misunderstanding will produce candidates that confirm it. The only real guard was that a
human accepted or rejected every candidate, and rejected 24 of 60 — including three where
the rejection exposed a bug in the heuristic rather than a difference of opinion.

## Homework 5 substitutions

Two more, and the second is the first time the *handout's own tooling* rather than an
install was the obstacle.

**`gpt-4o-mini` -> `rl-muse-spark-1-1-playground`.** The handout names `gpt-4o-mini` as
the judge model. The configured endpoint serves three models and none is an OpenAI one,
which a read-only `/models` call established before anything was built. All three were
then probed on a miniature judging task: `1-1` answered correctly in 5.3s, `1-3-sglang`
in 7.0s, `1-2` in 64.1s.

`1-1` was chosen over `1-3-sglang` deliberately, not by speed. The agent under test ran on
`1-3-sglang`, and a judge sharing the model it grades is least likely to notice that
model's own kinds of mistake. The constraint bought judge independence that the handout's
setup does not require and a student with an OpenAI key would not get.

**DocETL -> a direct classifier.** DocETL enforces its output schema with a named-function
`tool_choice`. The endpoint rejects it:

    OpenAIException - only "auto" is supported for tool_choice

`analysis/tools/muse_classify.py` calls the endpoint with plain chat completions, requests
the schema in the prompt, and parses the reply. The rest of the pipeline is untouched:
`run_judge` accepts a `classify` callable in place of the DocETL backend, and the
replacement returns the same predictions-plus-critiques structure, so caching, resume,
alignment and disagreement review all behave identically.

Two smaller traps worth recording, both specific to a repository that has carried its
Homework 2 configuration forward:

- Loading `.env` to expose the model key also exposed the `LANGFUSE_*` keys, so the
  helpers concluded Langfuse was available and tried to fetch traces from a server that
  never ran. The handout anticipates this and the fix is its own:
  `CARTWHEEL_JUDGE_TRACE_SOURCE`, set inside `analysis/run_judges.py` rather than left to
  a shell export that could be forgotten.
- The judge is registered as `openai/<model>` because that is how LiteLLM routes to an
  OpenAI-compatible endpoint. LiteLLM strips the prefix; calling the endpoint directly
  means stripping it too, or the server is asked for a model it has never heard of and
  answers 404.

## Related substitutions in this project

Two others, both for the same reason:

- **Langfuse → local OTel file exporter + Arize Phoenix.** Langfuse runs in Docker, which
  could not be installed. Only the trace *consumer* changed; the graded instrumentation in
  `observability/instrument.py` and `server/app.py` emits standard OpenTelemetry and does
  not know what is listening. `scenarios/export_langfuse.py` was replaced by
  `.hw3-logs/export_traces.py`, which produces the same envelope from the same spans.
- **`uv` → `python3 -m venv` and pip.** Every handout command `uv run python ...` becomes
  `.venv/bin/python ...`.

## Open questions for the instructor

1. Is a documented substitute acceptable for Part C where Raindrop Workshop cannot be
   installed on a managed laptop?
2. Is `permalink: null`, or a local file reference, acceptable where Langfuse was never
   available — and is a Phoenix-based substitute acceptable for `export_langfuse.py`?
3. Part E asks for each judgment to be written to Langfuse as a score. Only the local
   record under `analysis/state/labels/` exists. Each label file records this in a
   `score_destination` field rather than leaving the absence implicit.
