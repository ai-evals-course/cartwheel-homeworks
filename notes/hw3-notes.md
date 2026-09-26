# HW3 notes for teaching

Concrete case studies from building the pilot scenario set. See
[concepts.md](concepts.md) for the full generic coverage-vs-challenge
write-up; the recap below keeps the key points in context here too.

## Coverage set vs. challenge set, recap

- **Coverage set** — the everyday range of ordinary requests, spread
  across every important way requests vary, including routine edge values
  (a request landing right at a normal threshold is still ordinary).
- **Challenge set** — cases built on purpose to be hard: missing
  information, a correction mid-conversation, a rule that overrides the
  default, a permission boundary, deliberately broken data.
- **Why separate them**: one blended score lets an easy majority hide
  edge-case failures (90% easy requests can mean 95% "correct" overall
  even while every hard case fails). Reporting the two pools separately
  keeps the coverage score honest and surfaces the challenge score as its
  own, usually much less flattering, number.
- **Caveat**: the challenge set's failure rate is deliberately inflated by
  design — don't quote it as if it were a general production failure rate.

## Coverage examples we built

- Shopper checks an order's status — plain, everyday request.
- Refund requests at several price points, including right around the
  $100 auto-approval line — ordinary, since customers legitimately ask for
  refunds at every price point; hitting a normal threshold isn't a "trick."
- A merchant checking their own store's recent orders — routine daily use.

## Challenge examples we built

- **The 6 seeded data-quality cases** — deliberately broken records:
  an order marked delivered with no delivery date, an order whose ship
  date is after its delivery date, an order whose store doesn't match its
  product's store, two products sharing one title, a product with a
  negative price, a product with an empty title. Each tests whether the
  agent notices the broken data and handles it gracefully (asks for
  clarification, escalates, refuses to assert a false fact) rather than
  confidently stating something wrong.
- **Store-override boundary**: an order at a store with a stricter 14-day
  return window (vs. the 30-day platform default), delivered 17 days ago —
  right in the gap where the platform's generic rule would say "still
  eligible" but the store's actual rule says "too late." Tests whether the
  agent applies the correct, stricter rule instead of defaulting to the
  generic one.
- **Cross-store permission boundary**: a merchant from one store tries to
  look up an order belonging to a different store — a direct test of
  whether the permission wall holds under an explicit attempt to cross it.
- **Correction across turns**: the user asks about one item, then
  immediately corrects themselves to a different item in the next message
  — tests whether the agent follows the correction instead of running with
  the now-outdated original request.

## Scaling to 250: scripted generation instead of hand-authoring

The 30-scenario pilot was hand-authored (each record individually grounded
and written). At 250, that doesn't scale in one sitting, so the final set
was built with a generator script instead: broad SQL pools of real
candidate records per dimension, expected outcomes computed by calling the
actual eligibility logic and reading real policy/data-quality facts (not
hand-typed), and message text filled from phrasing templates per
(intent, style) so requests of the same kind still read differently.
`SKILL.md`'s "vary the kind, not just the wording" concern is about *kinds*
of requests, not literally unique prose — a template filled with real,
varying facts satisfies that as long as the underlying record and framing
genuinely differ.

Two concrete generator bugs worth knowing as a class of mistake:
- **Non-determinism in "random" pools**: seeding Python's `random` module
  doesn't seed SQL's own `RANDOM()` — every rebuild reshuffled which real
  records backed most scenarios, even with a fixed Python seed. Harmless
  on its own, but see the trace bug below for why it mattered here.
- **`random.choice` over a small template list, called repeatedly with the
  same substitution values**: with only 4-7 phrasings and that many draws,
  duplicate exact strings are common (the validator's "same scripted
  conversation twice" check caught this immediately). Fix: index
  templates deterministically (`templates[i]`) whenever the number of
  draws is close to the number of template options, rather than sampling
  with replacement.

## Bug caught: stale traces from an aborted, since-regenerated run

A first attempt at the full 250-scenario run was stopped partway (11
completed) to fix a coverage gap (see below), and the scenario file was
then rebuilt with fresh random record selections. But the 11 real requests
already sent had created real traces in the trace store, tagged with
scenario ids that now referred to *different* underlying content after the
rebuild. The export innocently pulled both the stale traces (attempt 1)
and the correct ones (attempt 2) for the same ids — indistinguishable from
the legitimate "one trace per turn" pattern of real multi-turn scenarios
without checking timestamps.

Teaching point: regenerating a scenario/query file does not retroactively
invalidate traces already produced from an earlier version of it. If a
generation-and-run cycle gets restarted mid-way, either use a fresh scenario
id namespace per attempt, or filter exports by a timestamp cutoff and
verify per-id trace counts against what the *current* file structurally
expects (here: 1 trace per turn, so multi-turn ids should show >1 and
everything else should show exactly 1) before trusting an export.

## Design call: broadening support-role coverage

The first draft of the 250-scenario set had support role in only 5/250
scenarios (2%), all within `order_status`. On reflection this under-tested
a real capability: `AUTH-1` gives support universal order access ("any
order"), but that row was never actually exercised — only merchant/shopper
permission *denials* were tested. Added support-role refund, cancellation,
and dispute scenarios, plus a direct contrast pair: the same kind of
cross-store request that correctly denies a merchant should correctly
*succeed* for support. Good example of a coverage gap that isn't obvious
from raw counts alone (250 scenarios "looks like a lot") — it only shows
up when you ask "which access-matrix rows does this dataset actually
exercise," not just "how many scenarios mention each role."

## Design call: order numbers in scenario messages

The scenario runner only ever sends the scenario's literal message text to
the agent — there's no side channel telling it "this scenario is about
order X." So for a scenario's recorded expected outcome to be gradable at
all, the message needs *some* reliable way to point the agent at the exact
record the scenario was grounded in, or the agent could reasonably act on
a different real record belonging to the same user.

We chose to keep explicit order numbers in most messages (plausible: real
customers often have their order number handy from a confirmation email)
while still withholding the genuinely hidden facts — exact day counts,
dollar thresholds, or any hint at whether an action would be approved.
Worth flagging as a live example of the invariant "keep hidden expected
answers out of the generation prompt" needing situational judgment: it's
about withholding what a real user *wouldn't know*, not about withholding
every fact that happens to also appear in the expected-outcome record.
