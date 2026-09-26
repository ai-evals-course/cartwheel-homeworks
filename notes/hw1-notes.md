# HW1 notes for teaching

Concrete case studies from doing HW1. See [concepts.md](concepts.md) for
the generic ideas these exercise (spec-vs-implementation layers,
judgment-schema design).

## Case study 1: eligible refund escalated instead of auto-approved

- Setup: shopper asks to return an order that is refund-eligible, in the
  return window, and under the auto-approval threshold.
- Observed: agent called `escalate_to_human` instead of `issue_refund`,
  reasoning it needed to arrange return shipping (no such tool exists).
- Teaching point: a "miss" isn't always a clean prompt bug. This one tangles
  a real tool/capability gap (no return-shipping tool) with a model
  judgment call — good example of why a judgment schema needs more than
  one failure-cause bucket (prompt vs tool vs spec-is-silent).

## Case study 2: account-change request refused instead of escalated

- Setup: shopper asks to change their account email.
- Observed: agent refused outright, zero tool calls, no ticket created.
- Root cause found: the system prompt's escalation section named only one
  concrete trigger (refund-above-threshold) and its capabilities section
  put "account/credential changes" right next to the *refuse* rule — so an
  account-email-change request pattern-matched to "refuse," not "escalate."
- Confirmed the fix mattered: the help-center corpus already had the right
  answer (a policy doc explicitly listed account changes as an
  always-escalate case) but the agent never even searched the help center
  for this request — it never looked, because the prompt didn't tell it to.
- Fix: one added clause naming account changes as an explicit
  escalation trigger. Re-ran the identical request afterward and got a
  ticket instead of a refusal.
- Teaching point: this is the cleanest kind of finding for an "evaluate an
  agent" exercise — a single missing instruction, a fully reproducible
  before/after, and independent confirmation that the tools worked fine
  (ruling out "tool" as the failure cause).

## Case study 3: a homework contract fixed mid-course (find_order)

- The starter's `find_order` implementation (per the original handout) only
  searched a user's most recent 20 orders.
- Upstream (course maintainers) shipped a fix requiring the *entire*
  authorized order history be searched, adding a new db helper and a test
  that plants an old matching order behind 20+ newer non-matching ones.
- Teaching point: this is a good live example that "the tests pass" and
  "the requirement is fully specified" are different claims — a passing
  test suite only proves what it was written to check. Worth pairing with
  a discussion of how spec/test gaps get discovered in practice.
