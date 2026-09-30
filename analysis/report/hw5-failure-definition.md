# Homework 5, Part A — failure definition

**Mode:** `irrelevant_policy_detail`
**Requirement:** `SPEC.md` RESP-5 — *"Use direct and respectful language that explains the
relevant decision."*
**Label convention (HW5):** `1` = Pass (failure absent), `0` = Fail (failure present).

## Why this mode needs a judge

The `write-judge-prompt` skill requires that code-based options be exhausted first. Of the
eight modes from Homework 4, five have a working deterministic check and three do not. This
is one of the three, and it is the one with the strongest evidence that a rule cannot do it:

- No code rule was ever written for it. Deciding whether a cited rule *governs* a case needs
  the order's store, that store's window override, the order total against the $100
  threshold, and the order's status — then a reading of whether the reply applied them.
- A grounded heuristic was tried and the reviewer **rejected 4 of 14** of its candidates,
  then a boundary revision reversed **5 more** earlier accepts. The heuristic matched on
  surface wording and repeatedly got the governing rule wrong.
- The remaining question is genuinely semantic: two replies can mention the same 30-day
  default, one correctly and one not, depending on whether the store's real window is named
  as governing.

## The question

> Does the reply explain a rule that does not govern this case?

One question, one mode. Not "is the reply too long", not "is the policy explanation good".

## The two tests

> **1. Does the rule the reply cites govern the path the agent actually took?**
> **2. Is there still a decision for that rule to govern?**

Fail on either. Everything below is those two tests applied to the shapes the traces
actually contain.

Both came from the reviewer, and each replaced something weaker.

The first killed a draft rule reading "explains the $100 automatic path on an order over
$100", which sounded right and was wrong: support-0035, 0037 and 0040 all cite the
over-$100 review rule **and all call `escalate_to_human`**. They are doing the thing they
describe. Citing a policy while taking the path it sets out is correct.

The second arrived from support-0034, and it is the reason this is not a single test. There
the refund was auto-approved and the reply explains that refunds of $100 or less execute
automatically — the rule cited is exactly the rule that governed. It passes the first test
and fails anyway, because the refund is already done and the customer has nothing left to
decide with that information. A judge given only the first test would let it through.

## Fail rules

Fail if the reply does **any** of the following.

**1. The platform default stated as the operative rule.** The order's store overrides the
return window, and the reply presents the 30-day platform default as the rule that applies
without naming the store's actual window as governing. A vague gesture — *"individual
stores can set their own window"* — does not count as naming it.
*Confirmed: support-0051 (Northwind, 45 days), support-0218 (Saltbox, 7 days).*

**2. A threshold cited for a path not being taken.** The reply explains the over-$100 human
review path when no refund is being queued at all, because it was already declined for a
different reason. The threshold decides nothing here.
*Confirmed: support-0221.*
*Not this: support-0035, 0037, 0040 — all over $100, all cite the rule, all escalate.*

**3. A fee the store has not opted into.** The reply raises the restocking-fee rule for a
store whose `restocking_fee_opt_in` is false.
*Confirmed: support-0025 (Copperline Tools), support-0026 (Paper Lantern Press).*

**4. Policy recited after the matter is settled.** The reply completes the action, then
explains rules that govern nothing the user still has to decide. This holds **even when the
rule cited is the one that produced the action** — the test is whether a decision remains,
not whether the rule was relevant a moment ago.
*Confirmed: support-0023 — the return window and restocking fee explained after the refund
was issued. support-0034 — the refund auto-approved, then the reply explains the under-$100
threshold that made it automatic.*

## Pass rules

Pass if **all** of the following hold.

- The rule named as governing is the rule that actually governs — the store's override
  where one exists, the platform default where none does, the threshold that determined how
  this refund was handled.
- **The reply is taking the path it cites.** Quoting the over-$100 rule while opening the
  approval ticket is correct.
- Mentioning the platform default as **contrast** is correct, wherever it falls in the
  sentence, provided the governing window is named and applied.
- Stating the one rule that decided the outcome is a Pass **even at length**, provided a
  decision is still open. Brevity is not the criterion.
- **A trace can Pass this mode while failing another.** If the policy named is the governing
  one, the reply passes here even when the conversation is wrong for another reason — a
  miscomputed date, a wrong conclusion, a missing escalation.

## Boundary against neighbouring modes

| Looks similar | Belongs to | The distinction |
|---|---|---|
| Reply prints `[cw-returns]` | `cites_policy_by_internal_id` | That is *how* the policy is named, not *which* policy |
| Reply repeats a fact already given | not elevated to a mode | Untidy, not misleading; different fix |
| Reply omits the rule that decided it | `detail_level_ignores_the_ask` | That is a missing rule, this is a surplus one |
| Reply contradicts the eligibility flag | `contradicts_eligibility_flag` | Wrong conclusion, not wrong rule |

The clearest borderline case is **support-0224**, held back for the judge prompt. Northwind
overrides to 45 days, the order was delivered 41 days before the world's current date, and
the tools returned `refund_eligible: true`. The reply denies the refund by measuring from
the real calendar instead of the seeded one. It is plainly a failed conversation — and its
policy reasoning is **correct**: it names the 45-day override as taking precedence and
applies it. **Pass for this mode.** It exists to test whether the judge answers its own
question rather than reacting to a trace that looks wrong.

## Evidence the judge needs

The verdict cannot be reached from the reply text alone. Every Fail shape above requires a
fact from outside the reply, which determines what `prepare_inputs()` must assemble in
Part B:

| Fail shape | Evidence required |
|---|---|
| 1, default as operative | the order's store, and that store's `return_window_days_override` |
| 2, threshold decided nothing | the order total, and whether a refund was declined |
| 3, fee not opted into | the store's `restocking_fee_opt_in` |
| 4, recited after settling | whether `issue_refund` ran, and its result |
| all | the user request and the agent's final reply, in full |

So each judge input needs the user request, the full reply, and the tool calls with their
results. The default trace normalisation returns early when conversation turns are present
and **drops the tool calls**, which would make this mode unjudgeable. `prepare_inputs()`
must include them explicitly.

**Kept out of the judge input:** human labels, review notes, the scenario's expected
outcome, and any Homework 4 annotation. Those leak the answer.

## Label counts at the time of writing

| | count |
|---|---|
| Fail (failure present) | 7 |
| Pass (failure absent) | 95 |
| Reviewed conversations | 102 |

The handout requires at least 30 of each. Pass is comfortable; Fail needs roughly 24 more,
drawn from the 159 conversations not yet reviewed.

The count fell from 10 to 6 during this boundary check, and that is the useful part. Four
traces the heuristic had flagged turned out not to contain this failure: it had matched the
strings `$100` and `30-day` without checking whether the rule governed anything. Catching
that here is much better than catching it in the development disagreements, or not catching
it and shipping a judge trained to flag any reply that mentions a threshold.

No shape now has more than two confirmed traces, so the top-up must not be allowed to
collapse into one shape. `next_to_label(strategy="enrich")` searches for semantic neighbours
of existing failures and will drift toward whichever shape is most numerous, so candidates
should be drawn deliberately across all four.
