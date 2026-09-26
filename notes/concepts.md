# Concepts and practical knowledge (generic, not homework-specific)

Reusable material for a syllabus — ideas and gotchas that apply beyond this
one repo. See [hw1-notes.md](hw1-notes.md) and [hw2-notes.md](hw2-notes.md)
for the concrete case studies that surfaced each of these.

## An agent spec is not the running system

A written spec (requirements doc, PRD, whatever) states intended behavior,
but the running application never reads that document. A requirement only
becomes real behavior through one of three implementation layers, and
*which* layer it lands in matters:

| Kind of requirement | Where it belongs | Why |
| --- | --- | --- |
| What to answer/refuse, tone, escalation triggers | The system prompt | The model decides |
| Who can see/do what | Auth code + each tool/function | Must hold even if the model misbehaves |
| Numeric policy (thresholds, windows, limits) | Config/data + deterministic code | Testable, not left to model judgment |

Teaching hook: give students one requirement from a spec and have them
guess which layer it belongs in *before* looking at the code. Deliberately
pick one that's easy to misplace (e.g. something that sounds like a
"tell the model" rule but must actually be code-enforced) to make the
distinction stick.

## HTTP endpoint & session

A CLI-style chat keeps identity in memory for the life of the process. An
HTTP server has no memory between requests — each call is a fresh
connection. That's why authenticated systems split into two steps:
verify identity once (issue a signed credential), then require every
later call to present that credential; the server looks up the stored
identity by an id, never by anything claimed in the request body/message.
This is *why* the server, not the conversation, decides who's talking.

## Trace & span

**Trace** — the complete record of one request, start to finish.
**Span** — one unit of work inside a trace (e.g. "call this tool," "call
the model"). Spans nest: a tool-call span sits inside the overall request
span, which is why a trace viewer shows a tree, not a flat list.

`trace.get_current_span()` (OpenTelemetry) returns whichever span is
"open" right now via an ambient context — conceptually like
`sys.exc_info()`, but for spans. When no span is open (tracing not
configured), it returns a no-op placeholder rather than `None` — check
`span.is_recording()` to tell the two cases apart.

## Vendor-neutral fields vs. application-specific fields

Auto-instrumentation records vendor-neutral fields (model name, messages,
tool name/args/result — defined by a shared spec, e.g. OTel's GenAI
semantic conventions: `gen_ai.*`). Anything the application alone knows
(which authenticated role/user made this call, whether a permission check
failed) has to be added by hand, in its own namespace (e.g. `cartwheel.*`
in this repo). Both kinds of fields end up as attributes on the same
spans — the split is about *who* can know the fact, not where it's stored.

## The three-layer observability stack (OpenTelemetry / OpenLLMetry / Langfuse)

Easy to conflate three different things:
- **OpenTelemetry** — the general-purpose tracing standard/API (spans,
  traces, exporters). Not AI-specific.
- **OpenLLMetry** (by Traceloop) — AI-specific instrumentation built on
  top of OTel. Ships pre-built instrumentors per AI library/SDK (OpenAI,
  Anthropic, LangChain, various agent frameworks) that auto-generate spans
  and `gen_ai.*` attributes for model/tool calls, so application code never
  hand-writes span creation.
- **Langfuse** — a trace *backend*: where OTel spans get exported to and
  viewed. OTel-compatible, built specifically for LLM traces (though the
  standard itself isn't tied to any one backend).

## Prompt version hashing

A prompt-version hash is a *fingerprint*, not a copy of the content — you
can't recover the prompt text from it. Its job is correlation: stamping
every trace/log with a short hash lets you group or filter records by
"which instructions were active," compare behavior across two prompt
revisions, or notice drift when the hash changes unexpectedly.

Design trap to watch for: hash only the *fixed* instructions, not anything
that gets filled in per-request (user id, role, session variables). If you
hash the fully-rendered prompt, every user/session gets a different hash
for otherwise-identical instructions — which defeats the entire point of
"group these by which prompt produced them." The actual content should
still be preserved somewhere durable (e.g. version control) — the hash
only ever answers "same or different," never "what was it."

## `max_turns` / tool-call loop limits

In an agentic loop, a single incoming request can trigger multiple
internal LLM calls: call model → maybe call a tool → feed the result back
→ call model again → ... until the model stops calling tools and returns
a final answer. A turn limit caps that internal cycle count — separate
from (and usually much smaller than) how many messages a user might send
in an ongoing conversation. It exists purely as a safety bound against a
run that never converges on a final answer.

## Request vs. trace vs. span vs. session — keeping four things straight

- **Request**: one call from a client to an endpoint.
- **Trace**: the full observability record of that one request.
- **Span**: one piece of work inside a trace; a trace's *root span* is
  whichever span is created first, with nothing else already open.
- **Session**: an identity + memory binding that outlives any single
  request — created once, then referenced by many separate requests
  (and therefore many separate traces) over time. A session is not a
  tracing construct; the link between "this trace" and "which session
  produced it" only exists if something explicitly stamps the session's
  id onto the trace. Don't assume that link exists by default — check.

**Multi-turn conversations produce multiple traces, not one.** Every
follow-up message in an ongoing conversation is its own new request, so it
gets its own new trace with its own root span — there is no single trace
that spans a whole back-and-forth conversation. A session id stamped on
each trace (e.g. `cartwheel.session_id` here) is the join key that lets
you regroup those separately-recorded traces back into "everything that
happened in this one conversation" after the fact — by filtering or
querying on that shared value. Whether a trace *viewer's UI* automatically
clusters same-session-id traces into one visual timeline (rather than you
manually filtering for them) depends on that specific backend recognizing
a particular attribute name as its own reserved session-linking field —
worth confirming per-tool rather than assuming a custom attribute name
triggers it automatically.

## Designing a judgment schema (met/unmet + reason codes)

A simple eval-logging schema (a boolean "did this meet the requirement"
plus a small enum of failure-cause categories, e.g. "the tool was wrong"
vs. "the model chose poorly" vs. "the spec doesn't say") forces a clear
binary call but loses nuance — e.g. "technically correct but unnecessarily
verbose" has nowhere to go. Worth discussing as a deliberate simplicity
trade-off when designing any lightweight eval-logging format: strictness
of the schema vs. richness of what it can express.

## Coverage set vs. challenge set (synthetic eval datasets)

When building a test set of scenarios/conversations for an agent, split it
into two labeled pools rather than one mixed pile:

- **Coverage set** — the everyday range of ordinary requests, spread across
  every important way requests vary (role, intent, record state, etc.),
  including routine edge values (e.g. a request that happens to land right
  at a normal threshold — that's still ordinary, since real users hit
  thresholds all the time).
- **Challenge set** — cases built *on purpose* to be hard: missing
  information, a correction mid-conversation, a rule that overrides the
  default, a permission boundary, deliberately broken/damaged data.

**Why separate them instead of reporting one blended score:** a dataset
that's 90% easy requests can score 95% "correct" overall even while
completely failing every hard edge case — the failures get diluted into
invisibility by the easy majority. Reporting the two pools separately
keeps the coverage score honest (closer to real-world performance) and
surfaces the challenge score as its own, usually much less flattering,
number — which is exactly where the interesting failures live.

**Caveat:** because the challenge set is deliberately loaded with hard
cases, its failure rate will look worse than real production traffic would
show — that's intentional (you're hunting for failure modes on purpose),
not a claim about how often the system fails in general. Don't quote a
challenge-set failure rate as if it were an overall production failure
rate.

## Vibe-coding a custom annotation UI vs. the platform's generic one

A generic annotation UI (Langfuse's default trace/review view, or any
similar tool) "serves everyone, which means it serves no one perfectly."
It shows raw spans, token counts, and JSON regardless of what a given
review task actually needs. An LLM-assisted ("vibe-coded") custom UI can
instead render only the fields one specific review task cares about —
e.g. request, final reply, the one relevant evidence source, and a single
accept/revise/reject control — because annotation queues, scoring APIs,
and the underlying data model already exist in the platform; building
custom is then a thin frontend layer, not a system from scratch.

Reasons it can pay off:
- **Cognitive load** — a reviewer doing the same judgment call hundreds of
  times benefits from seeing only the relevant fields, not reconstructing
  them from a generic span tree each time.
- **Domain-specific rendering** — code wants syntax highlighting, emails
  want formatting, structured data wants collapsible sections; a one-size
  interface can't specialize for all of them.
- **Non-technical reviewers** — someone without an OTel/tracing background
  gets more value from a tailored view than from a generic trace explorer.
- **Volume** — shortcuts and auto-advance only compound into real time
  savings once review counts get large (tens to hundreds of items).

The explicit caveat: don't default to building one. "If you're the only
reviewer or your traces render fine in a generic interface, stick with
the platform UI" — a custom UI is an ongoing maintenance cost, so it's
worth it only when volume, non-technical reviewers, or specialized
rendering needs actually justify it.

(Source: [Langfuse: Vibe Coding a Custom Annotation UI](https://langfuse.com/blog/2025-11-25-vibe-coding-custom-annotation-ui))

## End-user feedback vs. expected-result evals

An in-chat feedback button/textbox is a useful triage signal (which traces to prioritize reviewing) but measures user *sentiment*, not correctness — it can't replace expected-result checks grounded in the database/policy docs, since a user can be happy with a wrong answer or unhappy with a correct one.

## Sampling for review: uniform vs. cluster representatives

When picking which records to read first out of a large store, mix two
complementary strategies rather than relying on either alone:

- **Uniform (random) sampling** — every record has an equal chance of
  being picked, no clustering involved. Catches whatever a clustering
  scheme's chosen dimensions fail to capture — it doesn't know what it's
  missing, but neither does anything else.
- **Cluster representatives** — group records by structural similarity
  (for traces: turn count, tool-call count, which tools were used,
  retrieval presence, token totals) via k-means or similar, then pick one
  or two records closest to each cluster's center. This guarantees at
  least one example of every distinct *kind* of record in the store, even
  a rare kind that a random sample of the same size would likely miss
  entirely (an unusually long conversation might be 2% of the store —
  random sampling alone would rarely surface it; a cluster representative
  always does).

Combine both in the first reading batch: uniform sampling gives an
unbiased read on what's typical, cluster representatives guarantee
coverage of what's rare-but-real, and reading only one or the other biases
what failure modes you'll even notice exist. This is the mechanism behind
this project's `select_traces(strategy="diversity")` — it mixes roughly
two-thirds cluster representatives with one-third random picks under one
call.

## Generalization failure vs. specification/tooling gap

When a trace shows the agent got something wrong, ask *could it have gotten
this right with what it already had?* before deciding what kind of failure
it is — the answer changes what the fix looks like.

- **Generalization failure** — the agent had everything it needed (the
  right tool existed and returned the right data) and still produced the
  wrong answer. Fix: prompt or model change.
- **Specification/tooling gap** — no available tool could have surfaced
  the fact needed to answer correctly, or the spec never said what correct
  behavior even is. Fix: add/change a tool, fix the underlying data, or
  write the missing requirement — not a prompt edit, since no prompt can
  make a model check a fact it has no way to retrieve.

Concrete test: list the tools the agent actually has, and check whether
*any* combination of calls could have produced the correct fact. If not,
it's a tooling gap, not a model failure, and belongs in the taxonomy (if at
all) with a different fix attached and a different implication for whether
an LLM judge could ever catch it — a judge only checking the agent's
*output* can't distinguish "didn't try" from "couldn't have known."

## Two error-discovery methods are complementary, not either/or

Human open coding (reading transcripts against expected outcomes) and a
tool-assisted execution-level pass (e.g. a trace debugger's coding-agent
integration inspecting raw model activity and tool calls) are easy to treat
as competing options for finding failure modes. They aren't — they look at
the same underlying runs from two different levels and tend to catch
different things:

- **Open coding** reads at the *conversation* level. It's grounded and
  precise (a human checking actual behavior against an actual requirement),
  but limited to whatever a reader's attention catches while skimming
  transcript text across a large batch.
- **Execution-level tool inspection** reads at the *raw activity* level —
  tool-call arguments, sequencing, retries, timing — things that may never
  surface in a transcript's flattened text view even when they're symptoms
  of a real problem (a redundant call, an argument that doesn't match what
  the final reply implies).

The load-bearing design choice: treat the tool-assisted pass's output as
*hypotheses*, not labels. It runs on a much smaller sample (single digits vs.
the 100+ traces open coding covers) and a different reviewer (a coding
agent, not the human) is doing the first-pass noticing — so every suggestion
still needs the human to inspect the actual trace and decide accept/revise/
reject before it affects a taxonomy. This keeps the "human decides, tooling
proposes/scales" division intact even when the source of proposals changes.

## Human-first, then agent, is about sequencing trust — not which tool

Beyond this repo's specific tools: a general (if still emerging, not yet a
long-settled industry standard) practice in LLM/agent evaluation is to have
a human review traces and build a failure taxonomy *before* letting an
agent or LLM review the same population, rather than the other way around
or skipping the human pass entirely.

The reason is about where ground truth comes from, not which tool is more
capable. Only a human can anchor a taxonomy in what actually matters — the
spec, business judgment, which deviations are real failures vs. acceptable
variance. An agent reviewing cold has no such anchor: it will still produce
plausible-sounding categories, but with nothing to calibrate against, so
there's no way to tell a real finding from a hallucinated one. Once a
human-grounded taxonomy exists, a second automated/agentic pass — ideally
from a different vantage point (e.g. execution-level tool-call inspection
vs. conversational-transcript reading; see "Two error-discovery methods are
complementary" above) — is genuinely useful for finding gaps the human's
sampling or reading style missed. But its output stays a hypothesis to be
individually verified, never a label accepted on its own authority.

This is the same "human decides, tooling proposes/scales" split worth
naming explicitly as its own principle: the *order* (human first to
establish ground truth, automation second to generate candidates against
it) and the *epistemic status* of the second pass (hypotheses, not labels)
are what make this work — not the specific tool doing the second pass. The
same shape would hold with any two independently-instrumented review
methods, same tool or different.

(Related: Hamel Husain's error-analysis writeup, linked in References below,
argues directly against automating failure discovery before a human
understands the failures themselves.)

## Record an explicit outcome for every automated suggestion

A practical mechanism for actually enforcing "human decides, agent
proposes" (see "Human-first, then agent" above): for every individual
suggestion an automated/agentic pass produces, write down one of accept /
revise / reject, with a one-line reason, at the point of decision — not just
a summary verdict on the pass as a whole.

Without this, a suggestion can silently become a decision simply by sitting
unchallenged in a notes file, or a genuinely good suggestion can get lost by
never being revisited. Writing "accepted — became mode X" or "rejected —
re-ran N times, turned out to be Y" for each one, individually, creates an
audit trail: anyone reading it later can see exactly what was proposed, what
was actually checked, and why it did or didn't survive — without having to
reconstruct that reasoning from memory or from what the taxonomy happens to
look like afterward.

Concrete version of this from Homework 4 Part C: every Raindrop Workshop
suggestion in `analysis/report/workshop_notes.md` got its own `**Outcome:
...**` line (accepted into a new mode, accepted as corroboration of an
existing one, rejected after re-running the scenario showed it wasn't a
real pattern, or left out entirely for lacking ground truth to judge it
against) — four suggestions, four independent, individually-justified
outcomes, rather than one blanket "reviewed Workshop's findings" statement.

## Resist fixing bugs mid-review; note them and wait for evals

During open and axial coding it's tempting to patch an obvious prompt or
tool bug the moment you spot it. Fixing it isn't wrong in principle — the
challenge is keeping the review process trustworthy while you do. If you
change the system mid-review, later traces are being produced by a
different version than earlier ones, so the batch you're reviewing stops
being one coherent population — you lose track of which failures belong
to which version, and you can end up deleting a not-yet-characterized
example before you've actually understood it.

For the homeworks specifically: avoid changing the prompt/tools while
still doing open and axial coding. The goal at this stage is to
understand the *current* system and collect enough failures to name
recurring modes — not to already be improving it. Optimization is a later
stage: once failure modes and LLM-judges exist, you can make a change and
actually *measure* whether it helped (this is also where more systematic
methods like GEPA come in), rather than eyeballing whether a fix "seems"
to work on the handful of traces that prompted it.

That separation is what prevents over-optimizing to a few individual
traces. Practical rule: if you spot an obvious fix during open coding,
write it down (and note which already-reviewed failures you believe it
would resolve) — but hold off on applying it until evals are in place to
measure the effect. Same underlying discipline as "a held-out test set
only teaches you something if you don't peek early" above: the value of
a review pass — like the value of a held-out test set — depends on not
disturbing the thing being measured while you're still measuring it.

## Finalizing a taxonomy: why every mode needs positive *and* close-negative examples

Once open coding (and any second-pass tool-assisted review) has produced a
set of candidate failure modes, turning them into a *usable* taxonomy takes
more than writing each one down with one example. A repeatable sequence:

1. Sweep every annotation not yet linked to a mode and check it against the
   current definitions — this is where most of a mode's examples actually
   come from, not from the one or two traces that first suggested it.
2. Get each mode to several (e.g. ≥3) confirmed **positive** examples —
   traces that clearly contain the failure.
3. Find several **close-negative** examples per mode — traces that look
   similar on the surface but don't actually contain the failure.
4. Check merge/split: would one product change fix two modes' examples at
   once (merge candidate)? Do one mode's examples actually need different
   fixes (split candidate)?
5. For each surviving mode, record its boundary, evaluator type (checkable
   from the trace text alone, or does it need tool-result ground truth?),
   and requirement source (a spec id, or "human judgment").

**Why both positive and close-negative examples, not just positive ones:** a
mode's text definition alone is inherently fuzzy at the edges — natural
language always has gray areas. A single positive example anchors "yes,
this counts," but a reader (or a later LLM judge) has no way to tell which
of that example's details are the actual rule versus incidental surface
detail, and no sense of where the category *stops*. A close-negative
example — something that resembles the failure but doesn't cross the line —
is what actually marks the boundary; without one, both a human and a judge
default to pattern-matching on surface similarity and over-fire on
lookalikes. Several examples of each (not one) matter for the same reason
few-shot examples matter for any classifier: one example risks the reader
generalizing from an incidental feature of that single case rather than the
real invariant. This directly feeds Homework 5: an LLM judge built from a
fuzzy category with no boundary examples will systematically over- or
under-fire, no matter how well-written its prompt otherwise is.

**What "evaluator type" and "requirement source" mean, and why record them
per mode:**

- **Evaluator type** answers: what does checking this mode actually require
  — the final reply text alone, or also the tool-call trace and/or outside
  ground truth? Two rough buckets show up in practice: modes checkable from
  reply text alone (e.g. does it leak an internal field name, does it keep
  talking after a refusal), and modes that need more — either the correct
  answer isn't derivable from the reply itself (e.g. checking a policy
  citation is *correct*, not just present, requires knowing what should have
  been cited), or the failure only shows up in the tool-call sequence, not
  the final message (e.g. redundant tool calls, whether escalate_to_human
  was actually invoked). This isn't just documentation — it determines what
  data has to go into that mode's judge prompt in Homework 5. A judge fed
  only the final reply cannot possibly catch a mode whose evidence lives in
  the tool calls, no matter how well the prompt is written.
- **Requirement source** answers: is this mode enforcing something the spec
  actually says (a numbered requirement id, e.g. `RESP-1`), or is it a
  human-judgment quality bar the review surfaced with no written backing?
  Both are legitimate modes, but the distinction matters for accountability
  — a spec-backed mode is enforcing an explicit product decision, while an
  unbacked one is the reviewer's own judgment call about quality, which is
  worth being honest about rather than implying every mode traces back to a
  written rule.

## Practical gotcha: self-hosted Docker images going stale

Reference `docker-compose.yml` files for observability stacks (Langfuse
and others) often pin third-party images by a moving tag (`:latest`) on
Docker Hub. Some vendors (MinIO is a real example encountered here) later
restrict or stop free distribution of images on Docker Hub entirely,
turning a previously-working `docker compose up` into a sudden "access
denied" failure with no code change on your side. When that happens:
check whether the vendor publishes on an alternate registry (MinIO also
mirrors to Quay) before assuming the compose file itself is broken.
Pinning to a specific release tag (rather than `:latest`) reduces surprise
but doesn't eliminate this class of failure — the whole tag lineage can
still get pulled.

## Practical gotcha: regenerating an input file doesn't retract past runs

If a batch job (running scenarios/queries/prompts against a live system)
gets interrupted partway and the input file is then regenerated with new
random selections, any records already produced from the *old* version
still exist in whatever store received them — a trace store, a database,
a log. If those records are later joined back by an id that both file
versions happen to share (e.g. `scenario_007` in both the old and new
file, now pointing at different underlying content), a naive export can
silently merge the stale and the correct output under one id. Before
trusting such a join: filter by a timestamp cutoff at the restart point,
or use a fresh id namespace per attempt, and verify per-id result counts
against what the *current* input structurally expects.

Related, smaller gotcha: seeding one random-number generator (e.g.
Python's `random.seed(...)`) does not seed a *different* one in the same
pipeline (e.g. a database's own `RANDOM()` in a SQL query) — each needs
its own seed if determinism matters end to end.

## The AgentDebug / AgentErrorTaxonomy published taxonomy

A useful outside reference point when finalizing your own taxonomy (Homework
4 Part D asks you to compare against it): "Where LLM Agents Fail and How
They Can Learn From Failures" ([arXiv:2509.25370](https://arxiv.org/abs/2509.25370))
proposes **AgentDebug**, a debugging framework built on a taxonomy it calls
**AgentErrorTaxonomy** — 5 top-level dimensions, 17 specific leaf-level
failure modes, derived empirically from annotated failure trajectories
across three general-purpose agent benchmarks (ALFWorld, GAIA, WebShop):

- **Memory** (3): over-simplified/incomplete summary of past info,
  hallucinated (false) memory, retrieval failure (info existed but wasn't
  retrieved when needed).
- **Reflection** (4): misassessing progress, misinterpreting an action's
  outcome, correctly noticing a failure but blaming the wrong cause,
  hallucinating a reflection on events that never happened.
- **Planning** (3): ignoring constraints (time/budget/etc.), planning an
  impossible step, inefficient/wasteful planning.
- **Action** (3): plan-action disconnect (the action taken doesn't match
  the stated intent), malformed/invalid action format, bad/unreasonable
  parameters.
- **System-level** (4): step-limit exhaustion, tool/API execution errors,
  LLM/model limits (timeouts, token caps), environment bugs unrelated to
  the agent.

Since this taxonomy is general-purpose (built for tool-using agents
broadly, not customer support specifically), the useful comparison isn't
"does every category exist in mine" — most won't map cleanly (their
Memory/Reflection dimensions assume long multi-step reasoning most
short-conversation support scenarios don't exercise). The actual value is
narrower: does the published taxonomy name a real failure category your own
open coding might have missed, given what it actually surfaced? Their
Action/Parameter-Error and Planning/Inefficient-Planning categories, for
example, map fairly directly onto failure modes a review of a tool-using
agent would likely also surface independently — which is itself a useful
sanity check that your own taxonomy isn't missing something structural.

## Iterating a judge prompt against dev disagreements can overfit, like a model can

Reading every dev-set disagreement and patching the prompt to fix each one
feels like careful, grounded iteration — and it is grounded, but it's still
fitting to a sample, not to the underlying rule. A fix built from "here's
exactly what went wrong in these 15 traces" tends to encode some of *those
traces'* specific shape (a particular phrasing, a particular tool-call
pattern) alongside the general principle it's meant to teach. The dev score
goes up because the prompt now handles the dev set's specific quirks; that
gain doesn't necessarily transfer to different quirks the test set happens
to contain. This is the same overfitting concept from model training,
just applied to prompt wording instead of weights — and it's easy to miss
specifically because each individual revision felt well-justified by real
evidence at the time.

## A held-out test set only teaches you something if you don't peek early

The overfitting above is only *detectable* because dev and test stayed
genuinely separate until iteration was declared finished. If test scores
had been checked during iteration too, revisions would have started
chasing test's specific noise as well, and nothing would have been left to
reveal the gap. The discipline (look at test exactly once, after freezing,
no exceptions for "just a quick check") isn't bureaucratic caution — it's
the only thing that makes the eventual test number mean anything.

## Confidence intervals change what a metric comparison is allowed to claim

A point estimate alone invites over-reading small differences: "0.85 beats
0.77" sounds decisive until the sample size behind both numbers is small
enough that their intervals overlap substantially. With something like 15
examples in the class that matters, a 10-20 point swing in TPR/TNR between
two versions of anything (a prompt, a model, a pipeline change) is easily
within noise. The discipline is to hold the interval next to the point
estimate before concluding one version is actually better — and to say so
plainly when a comparison can't support the stronger claim.

## A retry can silently repeat the same bad output if a cache sits underneath it

When a request is cached by its exact inputs (e.g. a (prompt, content)
pair), a plain retry after a malformed or invalid model response hits the
identical cache key and gets back the identical bad response — it isn't
actually asking the model again. This looks like intermittent flakiness
("it failed, let me just retry") when it's really deterministic and
unrecoverable without forcing a fresh call. The fix is scoped: bypass the
cache only for the specific items that came back invalid, not for the
whole batch (which would re-pay for everything that already succeeded).

## A stated minimum sample size unblocks the pipeline, not necessarily the conclusion

"At least 30 of each class" is enough to make a train/dev/test split
mechanically valid — every stage has something to work with, the numbers
satisfy the guard. It says nothing about whether that's enough data to
actually learn or verify the general pattern rather than a narrow slice of
it. A judge can clear every stated minimum in the pipeline and still land
at a ceiling (here, a TNR that didn't move regardless of prompt version)
that's set by how much and how varied the underlying data is — a different
problem than the prompt wording, and one no amount of further prompt
iteration fixes.

## CI for evals

How eval work turns into an actual guardrail on every change, rather than
staying a one-off review exercise.

### A case is a non-deterministic test function, not a single assertion

A single eval "case" (one line in a cases file, one scripted scenario) is
conceptually one pytest function — but the thing under test is a
non-deterministic LLM, not deterministic code. A normal unit test asserts
once and gets a stable true/false forever; an AI eval case has to run
**N times** (e.g. `N=5`) and report a *pass rate*, because the same
prompt/task against the same model can genuinely produce a different
outcome from one run to the next. That's the reason `pass@k`/`pass^k`
exist as first-class metrics here rather than a single boolean: the
"result" of a case is inherently a distribution, and any framework that
collapses it to one true/false (from a single run) is silently choosing
one arbitrary sample of that distribution and reporting it as ground
truth. See [hw6-notes.md](hw6-notes.md) for the concrete case/run/trial/
baseline terminology this maps onto in one implementation.

### Keep a small, high-quality eval set running in CI

A practical target: ~30 carefully chosen evals (not hundreds) wired into
CI, rather than skipping automated checks until a large suite exists. A
small set that's actually high-quality — each case grounded in a real
requirement or a real observed failure, not padding — is more valuable
than a large set diluted with redundant or low-signal cases, and it's
cheap enough to run on every change without becoming a bottleneck. Grow it
deliberately (e.g. adding a case for each newly confirmed failure mode)
rather than trying to front-load comprehensive coverage before shipping
any CI gate at all.

## References

- [Hamel Husain: Why is error analysis so important in LLM evals, and how is it performed?](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html) — relevant to the open-coding/failure-taxonomy work in Homework 4.
- [Where LLM Agents Fail and How They Can Learn From Failures (AgentDebug / AgentErrorTaxonomy)](https://arxiv.org/abs/2509.25370) — the published taxonomy Homework 4 Part D asks you to compare your own against.
