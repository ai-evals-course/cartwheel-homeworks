# Raindrop Workshop notes (HW4 Part C)

9 runs inspected: one from the initial wiring test, plus 8 fresh runs driven
deliberately across all three roles and a spread of tools/intents. All ran
live against `server/app.py` (localhost:8010) with Workshop capturing tool
activity via `raindrop.begin()`/`finish()` (see `server/app.py`). Identified
by Raindrop run id and the `scenario_id` tag sent with each request.

This is a second, independent pass over fresh runs, not a replacement for
the open-coding review in Part B — see `notes/concepts.md` ("Two
error-discovery methods are complementary" and "Human-first, then agent, is
about sequencing trust") for why. Everything below is a candidate for you to
accept, revise, or reject, not a finding on its own authority.

## Runs inspected

| run id | scenario_id | role | message |
| --- | --- | --- | --- |
| `a466cb02b183af752e00b271fef4c9f0` | manual-workshop-test-1 | support | "A shopper says order 8003 arrived damaged. What should I do?" |
| `a04b68c2b590550ff0ff4bc53a875f4f` | workshop-1-refund | shopper | "I want a refund for order 4455, it broke after one use." |
| `8218a58ce6e4986ae5c4585da7994270` | workshop-2-search | shopper | "Do you have anything under $30 from Blue Heron Ceramics?" |
| `081b860cf3814a097dd27e868a74bc0d` | workshop-3-merchant-perm | merchant | "Can you pull up order 9704 for me?" |
| `2e0caaf06b8a5bfdffe98871992b3f25` | workshop-4-dispute | support | "A shopper says their order 6210 never showed up and wants a refund. What do I do?" |
| `daf12de3960e1ab7bc6f0a49d5506c55` | workshop-5-account | shopper | "Can you update my email to newemail@example.com?" |
| `c10e52805b2b354177a954aebe3ca0ff` | workshop-6-oos | shopper | "Can you recommend a good therapist near me?" |
| `4e2ea2fc6b5a19e2856ca43595020ab4` | workshop-7-mismatch | support | "Can you check on order 8003 for me?" |
| `96b988879caa51278057f382f7840951` | workshop-8-policy | shopper | "What's your return window?" |

## Candidate failures / unusual behaviors

1. **Thrashing tool use on an ambiguous product search** (`workshop-2-search`).
   Asked for "anything under $30 from Blue Heron Ceramics," the agent ran 10
   `search_products` calls before answering — guessing at specific product
   titles it had no way of knowing ("...Rustic Pitcher", "...9.75",
   "...Heavy-Duty Vase" twice, "...Walnut Vase", "...Compact Mug",
   "...Portable Mug") instead of the one broad, obviously-sufficient query
   (`store="Blue Heron Ceramics", max_price_usd=30`) it eventually landed on
   last. Not wrong, and no policy/data was misstated — but this looks like a
   genuinely different failure shape from anything in your current six: not
   a communication or escalation problem, an *efficiency/search-strategy*
   one.

   **Outcome: accepted**, irrespective of the final answer's correctness.
   Added as a 7th candidate mode, `inefficient_tool_use`
   (`analysis/state/patterns.json`). The trace was imported into the review
   set (`analysis/state/samples.json`, trace_id
   `8218a58ce6e4986ae5c4585da7994270`) and annotated.

2. **`continues_past_refusal` corroborated from an independent run**
   (`workshop-6-oos`). Asked for a therapist recommendation, the agent
   correctly declined up front, then continued with a list of external
   search suggestions and a follow-up question — the same shape already in
   your taxonomy from `pilot-0011`'s medical-recommendation trace. Useful as
   a second, independently-generated example if you want one for Part D's
   "≥3 positive examples" requirement.

   **Outcome: accepted** as a corroborating example of the existing mode, no
   new mode created.

3. **`ignores_data_quality_anomaly` corroborated from an independent run**
   (`workshop-7-mismatch`). Same order 8003 (store/product mismatch) as
   `support-0188`/`support-0190`/`pilot-0023` — the agent again reports it
   as a normal Blue Heron Ceramics order with no sign of noticing the
   mismatch. Confirms this isn't a one-off — the same input reliably
   reproduces the same miss.

   **Outcome: accepted** as a corroborating example of the existing mode, no
   new mode created.

4. **Escalation behavior looks inconsistent across similar requests, not
   just cautious.** `workshop-3-merchant-perm` (permission-denied order
   lookup) and `workshop-5-account` (account-email change) both called
   `escalate_to_human` immediately, no confirmation asked. That's a
   different behavior from `support-0160` and `support-0222` in your
   reviewed set, where structurally similar requests got an *offer* to
   escalate instead of an actual call. Worth being aware this may not be a
   single fixable "always asks first" or "never escalates" bug — it looks
   like real run-to-run variance for the same category of request, which
   changes how you'd frame any mode built around it (a consistency problem,
   not a one-directional one).

   **Outcome: rejected.** Re-ran each scenario 5 more times (10 fresh runs
   total, `rerun-perm-1..5`, `rerun-acct-1..5`). Account-change escalated
   directly 6/6. Permission-denied escalated directly 5/6 -- the one
   exception (`rerun-perm-4`) didn't skip escalation carelessly; it
   cross-checked the merchant's own order list, noticed the order wasn't in
   their store, and reasonably asked whether the order number was a typo
   before offering to escalate. Not enough evidence for a mode, and the one
   deviation has a defensible alternative explanation rather than looking
   like a dropped ball. This also means `support-0160`/`support-0222` (the
   two single-sample cases that first raised this) are probably statistical
   outliers rather than a representative 50/50 split -- worth keeping in
   mind, not necessarily revising those two labels.

   **General note on genuinely uncertain single-sample cases**: when a trace
   raises a plausible-sounding concern that rests on one observation, before
   deciding it's a real pattern, the options are roughly: (1) accept it as a
   one-off worth noting but not formalizing into a mode, (2) look for
   corroborating evidence elsewhere in the already-reviewed set, or (3)
   re-run the same scenario several times fresh and look at the actual
   distribution of behavior. Option 3 is cheap when a live agent is
   available (as it was here) and turns "I saw this once" into an actual
   base rate -- it's what separated a real recurring failure
   (`ignores_data_quality_anomaly`, reproduced identically on every re-run of
   order 8003) from what looked like inconsistency here but was mostly one
   dominant behavior plus a reasonable outlier.

## Uncertain case

**`workshop-4-dispute`** (support role, "order 6210 never showed up and
wants a refund"). `get_order` shows the order already `status: refunded,
refund_eligible: false` — so the premise ("never showed up, wants a
refund") doesn't match the record's current state at all. The agent never
calls `escalate_to_human`; it recommends telling the shopper the refund
already went out, waiting 10 business days, and escalating only if the
money still doesn't show up.

Two readings, and I'm genuinely unsure which is right:
- **Same shape as `support-0151`**: a dispute-flavored request that should
  have escalated (or at least been executed, not just recommended) and
  didn't.
- **Defensible triage**: the record doesn't actually support an active,
  unresolved dispute right now (it's already refunded) — informing the
  shopper first and reserving escalation for if they push back afterward
  isn't unreasonable, and lines up with the "ok to ask/inform first"
  judgment call you already made for `support-0160`.

I can't tell from this trace alone which reading you'd want to apply — flagging
it rather than picking one.

**Outcome: no mode, no example added.** Re-ran 5 more times: 5/6 total
inform-and-defer, 1/6 (`rerun-dispute-5`) escalated immediately -- and gave a
sharper justification than "it's a dispute" (specifically flagged the
`refunded`-but-"never arrived" tension as needing human reconciliation). So
the model is genuinely inconsistent here, and the minority behavior reasons
more precisely than the majority one. Left out of the taxonomy entirely,
though, because this scenario was invented on the spot rather than drawn
from the official 250 -- there's no `expected.outcome` to check either
behavior against, so "5/6 do X" isn't evidence of a requirement violation,
just variance with nothing to anchor it to.
