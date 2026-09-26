# Teaching notes

Working notes on concepts and concrete examples surfaced while doing the
Cartwheel homeworks, kept for drafting a syllabus/class later. Not part of
any homework submission — safe to edit, reorganize, or delete freely.

- [concepts.md](concepts.md) — generic, reusable material: spec-vs-
  implementation layers, trace/span, gen_ai.* vs application-specific
  fields, the OTel/OpenLLMetry/Langfuse stack, prompt-version hashing,
  max_turns, request/trace/span/session distinctions, judgment-schema
  design, coverage vs. challenge sets, generalization failure vs.
  specification/tooling gap, why open coding and tool-assisted execution-
  level review are complementary rather than either/or, why human review
  comes before agent review generally (a sequencing-of-trust principle, not
  a tool choice), recording an explicit accept/revise/reject outcome per
  automated suggestion as an audit-trail mechanism, finalizing a taxonomy
  (why every mode needs both positive and close-negative examples), the
  published AgentDebug/AgentErrorTaxonomy reference taxonomy, why iterating
  a judge prompt against dev disagreements can overfit like a model can,
  why held-out test discipline only works if you don't peek early,
  confidence intervals in metric comparisons, cache-masked retries, a
  stated minimum sample size unblocking the pipeline but not the
  conclusion, why to resist fixing prompt/tool bugs mid-review, CI for
  evals (keeping a small high-quality eval set in CI), and practical
  gotchas (stale pinned Docker images; regenerating an input file mid-run
  without retracting earlier output).
- [hw1-notes.md](hw1-notes.md) — HW1 case studies: two real prompt-gap
  findings (with before/after evidence) and the find_order contract-drift
  example.
- [hw2-notes.md](hw2-notes.md) — HW2 case studies: the missing
  session-id span attribute, the stale MinIO image, and a suggested
  teaching sequence.
- [hw3-notes.md](hw3-notes.md) — HW3 case studies: coverage vs. challenge
  examples, scaling scenario generation from 30 to 250, a stale-trace
  export bug (and fix), the support-role coverage-gap design call, and
  keeping order numbers in scenario messages.
- [hw4-notes.md](hw4-notes.md) — HW4 case studies from open coding: a
  failure with no available tool-based fix, "didn't guess" vs. "handled it
  well," a leaked generator placeholder that invalidated five scenarios, and
  an escalation channel offered for the wrong reason.
- [hw5-notes.md](hw5-notes.md) — HW5 case studies from building an LLM
  judge: a judge that anchored on a good opening turn and ignored what came
  after, an exclusion clause that stated a rule without enforcing it, how
  fixing one boundary problem exposed a new one, and a list addition that
  didn't change behavior without a worked example.
- [hw6-notes.md](hw6-notes.md) — HW6 terminology (case/eval case vs.
  run/trial vs. baseline runs, and why classification needs multiple
  trials rather than one) plus case studies from wiring Harbor CI.
