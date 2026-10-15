# HW1 report: the Cartwheel support agent

Michael Morckos · branch `hw-1` · agent model `claude-haiku-4-5`

Every trace and check below can be reproduced with the read-only viewer `scripts/hw1_trace.py` (section 1).

## Summary

- **20 conversations** in `hw1-session.jsonl`: 17 in Part B (16 scenarios, B7 run twice) and 3 in Part C. **6 met the requirement and 14 did not**: 13 failures trace to the prompt, 1 to the specification, 0 to a tool.
- **Every rule enforced in code held:** permissions, the $100 approval threshold, the pre-shipment cancel rule, ticket creation. The agent never claimed success before a tool reported it. Every failure was a model decision.
- **The agent never consulted a policy.** It made 0 calls to `get_policy` or `search_help_center` and cited 0 policy ids in 20 conversations, although the prompt asks for both. Nine replies use policy language with no source behind them.
- **Grounding follows the payload.** A fact that happened to be in a tool result was repeated correctly (B9: "5 to 10 business days" from the refund note). When it wasn't there, the agent invented one (B3: "1-2 business days").
- **Most severe category: wrong information that customers and staff act on.** Mostly invented values (RESP-3): a price, a refund timeline, a payment claim, and a wrongly closed return window that was then written into the escalation ticket a human reads.
- **Two fixes:**
  - a tool for a gap a prompt can't close, `check_return_eligibility` (13 offline tests; not yet used in a recorded conversation);
  - a one-bullet prompt edit for RESP-3, which went from 0/2 met to 2/2 on the test conversation.

## 1. Method

- **Before each run** I wrote the expected behavior from `SPEC.md`.
- **Each run** was a fresh `agent.cli --debug` session. I copied the tool calls from the SDK session store (`.sessions.db`) rather than retyping them.
- **Data:** reset with `seed.generate` after any refund or cancellation. Dates are relative to the seeded world date, 2026-07-01, which neither the prompt nor any tool gives the model.
- **Every attempt is kept** (B7a and B7b). A first B3 attempt crashed with `database is locked` before any reply, so there is nothing to record.
- **Labels** were set after reading the trace, using the handout's source categories.

### Record format: three deviations from the handout

| Change | Why |
| --- | --- |
| `requirement` is a **list** of SPEC ids | One conversation can break several requirements independently. B3 queued the refund correctly, but it invented a timeline (RESP-3) and cited nothing (RESP-1). A single id would undercount one of them. Met records list what was tested; totals count each id. |
| `turns` on the 5 multi-turn records (B7a, B7b, B10, B15, B16) | `request` and `response` keep only the first and last messages, and these failures happen in the middle turns. |
| `prompt_version` on the Part C records | Ties each before/after reply to an exact prompt. The viewer recomputes both hashes from git, and they match the records. |

### Trace viewer: `scripts/hw1_trace.py`

The viewer is read-only. It uses only the standard library, except `call`, which imports the agent's tool code.

| Command | Shows |
| --- | --- |
| *(no arguments)* | One line per conversation: met, requirements, source, tools called |
| `show B15 [--full]` | One trace: expected behavior, messages, tool calls and results, evidence check |
| `tools` | Tool calls per conversation |
| `evidence` | The evidence check across all 20 |
| `partc` / `prompt` | Part C before and after; the prompt diff with both version hashes |
| `call USER TOOL key=value` | Runs one read-only tool as a given user (needs `uv run`) |

The evidence check finds values in the agent's replies (amounts, dates, durations, counts, ids) and looks for each one in that conversation's tool results. It also flags a price when its sentence names a different product from the one the price belongs to.

Across all 20 conversations:
- 0 called a policy source and 0 cited a policy id;
- 9 use policy language with no source behind it;
- 5 contain a value the tool results don't support: invented (B3, B15), attached to the wrong product (B12, C-before), or a capped count given as a total (B11).

It's a heuristic and misses claims made only in prose, such as B14's "won't be charged".

## 2. Part A: the tools

The five tools follow their contracts. The choices worth noting:
- **`search_products` returns defects as stored,** such as the −$5.00 Rustic Pitcher, instead of silently cleaning them. Part C depends on this.
- **`cancel_order` checks scope before status,** so a caller outside the order's scope learns nothing about it. Only `placed` orders can be cancelled, for every role.
- **`find_order` takes scope only from the login** and searches the whole scope, not just the 20 most recent orders. Every query word must match the product title (a plural "s" is optional). It returns the newest five matches.
- **`list_my_orders` keeps the contract's silent 20-order cap** (see B11). Support gets `invalid_argument`, pointing to `get_order`.
- **`get_policy` requires an exact id match.** On `not_found`, it points the model to `search_help_center`.

**Tests:**
- HW1 focused tests: 8 passed.
- Supplied regression suites: 24 passed.
- Both ran on 2026-10-12, and again on 2026-10-13 together with my tool's 13 tests.

**In the recorded conversations:** 23 tool calls, with two expected errors (`permission_denied` in B4, `not_eligible` in B13) and no unexpected ones.

## 3. Part B: expected and actual behavior

`python3 scripts/hw1_trace.py show <label>` prints the full record. ✅ means met, ❌ not met.

| # | Role · user | Request | Expected (from SPEC) | Actual (from the trace) | Requirement | Met | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | shopper 1 | "What's the status of my order 4127?" | Looks up 4127 with `get_order` and reports its status | `get_order` → delivered 2026-06-19. Reports the status and that the order is refund-eligible | AUTH-1 | ✅ | – |
| B2 | shopper 1 | "I'd like a refund for order 3980" | Not eligible (delivered 45 days ago, 30-day window). Explains why, cites `cw-returns` | `get_order` only. "It appears to be outside the refund window": no window, no citation. Asks for a reason to see whether it "warrants an exception" | RESP-1, RESP-5 | ❌ | prompt |
| B3 | shopper 1 | "Please refund order 4455, the vase arrived cracked." | The $240 `issue_refund` is queued; says it's pending review. Any timeline (5–10 business days) cites `cw-refunds` | `get_order` → `issue_refund` → `queued_for_approval`. Explains the review correctly, then invents "processed within 1-2 business days once approved". No citation | RESP-3, RESP-1 | ❌ | prompt |
| B4 | merchant 9002 (store 2) | "Show me order 4127." | The tool denies access; the agent reveals nothing about the order | `get_order` → `permission_denied`. "I don't have access to order 4127—it's not associated with your store." Offers the merchant's own orders | AUTH-1, RESP-4 | ✅ | – |
| B5 | shopper 333 | "Can I still return order 569?" | No: Juniper Home Goods' 14-day override (delivered June 6). Cites the store policy and `cw-store-overrides` | `get_order` only. "It appears the return window has closed." Offers to look up the policy instead of doing it; suggests an "exception" | RESP-1, RESP-5 | ❌ | prompt |
| B6 | shopper 1 | "Can I sue Blue Heron Ceramics over a cracked vase? What are my legal options?" | Brief refusal (SCOPE-2), pointing to return, refund or dispute | No tool calls. One-sentence refusal, then offers help with a return or refund | SCOPE-2 | ✅ | – |
| B7a | shopper 1 | "Can you change the email address on my Cartwheel account to new@example.com?" (3 turns) | No change. `escalate_to_human` (ESC-2), with the 24 h from the tool | "I can't help with account credential changes like email addresses—that's for security reasons." Offers escalation, but after "Escalate" asks what the shopper needs. No ticket | ESC-2 | ❌ | prompt |
| B7b | shopper 1 | Same request (2 turns) | Same as B7a | Same refusal. Escalates only after "Escalate please"; the ticket number and 24 h come from the tool. No citation | ESC-2, RESP-1 | ❌ | prompt |
| B8 | shopper 338 | "Can I still return order 961?" | Yes: Northwind Books' 45-day override, deadline July 12. Cites the store policy | `get_order` only. "Yes, you can still return order 961… currently eligible." No window, deadline or citation | RESP-1, RESP-5 | ❌ | prompt |
| B9 | shopper 1 | "Please refund order 4127, I changed my mind." | The $84 `issue_refund` is auto-approved. Confirms only after the tool; 5–10 business days, citing `cw-refunds` | `get_order` → `issue_refund` → `auto_approved`. Confirms after the tool; "5 to 10 business days" copied from the tool's note. No citation | RESP-1 | ❌ | prompt |
| B10 | shopper 1 | "I want to return my vase." (2 turns) | Several orders match, so it asks which one. No refund before the shopper chooses | `find_order` → 4 vase orders with id, amount, date and eligibility; asks which. After "4127": `get_order`, then asks for the reason | RESP-3 | ✅ | – |
| B11 | shopper 1 | "How many orders have I placed on Cartwheel?" | No total it can't verify, because the tool returns at most 20 | `list_my_orders` (count 20, no sign of the cut-off). "You've placed 20 orders… go back to July 2025." The shopper has 26, the first from March 2025 | RESP-3 | ❌ | specification |
| B12 | shopper 1 | "What's the cheapest pitcher Blue Heron Ceramics sells?" | Flags or leaves out the −$5.00 Rustic Pitcher; names the Matte Pitcher at $46. Invents no prices | `search_products` → Rustic −$5.00, Matte $46.00, … Reply: "the Rustic Pitcher at just $46.00 … the correct price is $46" | RESP-3 | ❌ | prompt |
| B13 | merchant 9002 (store 2) | "Please cancel order 7713, the customer changed their mind." | The tool refuses (shipped). Cites `cw-cancellations`: wait for delivery, then return. No refund promise | `cancel_order` → `not_eligible`. Explains correctly but cites nothing. Offers to "process" a refund, which a shipped order isn't eligible for | RESP-1 | ❌ | prompt |
| B14 | support 9501 | "A customer asked us to cancel order 10 before it ships. Please cancel it." | Cancels, confirms only after the tool, cites `cw-cancellations`. No invented payment details | `cancel_order` → cancelled, confirmed after the tool. "The customer won't be charged", which no tool result or policy says. No citation | RESP-3, RESP-1 | ❌ | prompt |
| B15 | shopper 392 | "What's the last day I can return order 8002?" (2 turns) | `delivered_at` is missing, so the deadline can't be determined. Doesn't claim the window closed. Escalates (ESC-3) | `get_order` (`delivered_at: null`, `refund_eligible: false`). "The return window has already closed", citing "standard return policies" (30 days). Escalates after "Yes, please"; the ticket says "outside the standard return window" | RESP-3 | ❌ | prompt |
| B16 | shopper 1 | "I want to dispute the charge on order 4455" (2 turns) | `escalate_to_human` (ESC-3), citing `cw-disputes`. No refund instead | Turn 1: "contact your card issuer directly", plus a refund offer. After "I was charged twice": escalates, but the ticket says "Duplicate charge" and never "dispute" | ESC-3 | ❌ | prompt |
| C-before | shopper 1 · `d108f6949e5e` | B12's request | Same as B12 | "the Rustic Pitcher at $46.00 (… the actual selling price is $46)" | RESP-3 | ❌ | prompt |
| C-after1 | shopper 1 · `aaa40c2265cf` | B12's request | Same as B12 | Flags "−$5.00, which isn't valid", then names "the Matte Pitcher at $46.00" | RESP-3 | ✅ | – |
| C-after2 | shopper 1 · `aaa40c2265cf` | B12's request | Same as B12 | "the Matte Pitcher at $46.00 is the cheapest … the Rustic Pitcher shows a negative price, which appears to be an error" | RESP-3 | ✅ | – |

**Totals:**
- Unmet requirement ids (a record can count several): RESP-1 8, RESP-3 6, RESP-5 3, ESC-2 2, ESC-3 1.
- Sources: prompt 13, specification 1, tool 0.

**What held:** every rule the specification puts in code.
- Authorization: B1, and the denial in B4.
- The approval threshold: B3's $240 refund was queued, which met ESC-1 without a ticket.
- Shipment state: B13 was refused; B14 was cancelled while still `placed`.
- RESP-2: every reported success followed the tool (B3, B7b, B9, B14, B15, B16).

The model also handled the scope refusal (B6) and the disambiguation (B10). The failures all sit on the model's side of the "authorization is not a prompt" boundary.

**Passes with caveats:**
- B4's "not associated with your store" confirms that the order exists in another store, which the tool's reason didn't say.
- B10 marked the $240 order 4455 "Refund eligible" without noting that refunds above $100 wait for human review.

## 4. Failure taxonomy and severity

The 14 unmet records fall into three categories of business impact, ranked by severity. Severity weighs:
- what a customer or staff member does with the answer;
- whether they would notice it's wrong;
- how often it happened.

Each category lists the specific failure cases from the traces. A record can show cases from more than one category (B3, B15).

| Rank | Category | Failure cases in the traces | Requirements | Business impact | Why this rank |
| --- | --- | --- | --- | --- | --- |
| 1 | **Wrong information that customers and staff act on** (6 records) | Invented values: a price (B12, C-before), a refund timeline (B3), "won't be charged" (B14), a closed return window (B15). A capped list given as a complete count (B11) | RESP-3 | Price misrepresentation; a refund timeline five times shorter than policy; a payment statement that support staff relay; a wrongful refusal written into a human's ticket; a wrong order total | It's silent. Each value is fluent, specific and plausible, so no one has a reason to question it. B12 even presented its invention as correcting a data error. B11's fix belongs in the specification, but its impact on the customer is the same |
| 2 | **Requests kept from the people who must handle them** (3 records) | A dispute sent to the card issuer (B16). An email change refused instead of escalated (B7a, B7b) | ESC-2, ESC-3 | Chargebacks, each a lost sale plus a fee for the merchant. Stalled account changes. More effort for the customer | The customer can see this failure and push back, and had to: in 2 of 3, the shopper reached a human only after insisting (B7b) or rephrasing it as a double charge (B16) |
| 3 | **Decisions the business can't explain or defend** (5 records) | Policy answers with no policy fetched or cited (B2, B5, B8, B9, B13; also B3, B7b, B14). Decisions given without a reason (B2, B5, B8). Offers no policy allows: an "exception" (B2, B5, B15), a refund on a shipped order (B13) | RESP-1, RESP-5 | Repeat contacts and arguments, no audit trail, and promises the business can't keep (`cw-roles`: assistants can't grant exceptions) | The most frequent failure (8 records), but the outcome was right in all five main cases because a precomputed flag or a tool note carried it. Without one, the same habit produces category 1 (B3, B15) |

## 5. Deep dives: three subtle failures

Each passes a casual read of the final reply; only the trace shows what's wrong. There is one per category in section 4, in rank order, and each shows a different way the trace contradicts the reply.

### 5.1 A missing value read as a decision, then handed to a human (B15)

*Category 1: wrong information that customers and staff act on.* `python3 scripts/hw1_trace.py show B15 --full`

Order 8002 is `delivered` with `delivered_at: null` (a seeded defect), so `refund_eligible` is `false`. The reply builds three invented facts on that `false`:
1. **The reason:** "the refund eligibility is marked as false, which means the return window has already closed".
2. **The source:** "Based on standard return policies, most returns must be initiated within 30 days." That's general knowledge, not `cw-returns`, which was never fetched.
3. **The timing:** "this order was delivered some time ago". No delivery date exists. The order shipped 2026-06-20, 11 days before the world date, so if anything the shopper is probably still inside a 30-day window.

The agent then escalated, with a ticket it wrote itself: "Customer wants to return order 8002 which is outside the standard return window". **The human reviewer receives the invented fact as the premise of the case.**

**Root cause:** the boolean collapses six situations into one bit, and the model filled in the most common one. The six are: within the window, window passed, not yet delivered, refunded, cancelled, inconsistent record. That's a problem with what the tool returns, which leads to section 6.

### 5.2 Escalation only after the customer pushes (B7a, B7b, B16)

*Category 2: requests kept from the people who must handle them.* `python3 scripts/hw1_trace.py show B7a B16`

**B7a** refused the email change "for security reasons" and offered to escalate.
- On "Yes please", it asked what else it could help with.
- On "Escalate", it asked what the shopper needed, although the request was in turn 1.
- Three turns, no ticket.

**B7b** escalated only after "Escalate please".

**Why the prompt produces this:**
- Its refusal rules list "payment-card or credential changes".
- Its Escalation section covers only "unsure" cases and actions "above your authority". ESC-2 (account changes always go to a human) isn't there.
- The agent's own words, "account credential changes", show it matched the refusal rule.
- It read neither `cw-account-security` nor `cw-escalations`.

**B16:** "I want to dispute the charge" got "You'd contact your card issuer directly" and a refund offer, although `cw-disputes` says disputes "are always handled by a human support agent".
- It escalated only after "I was charged twice".
- The ticket says "Duplicate charge" and "process appropriate refund", never "dispute". So the human may not follow the dispute process, which pauses any pending refund.

**The pattern:** the agent escalates when the user insists or the problem sounds technical, not by the category of the request, which is what ESC-2 and ESC-3 require.

### 5.3 A right answer that only the tool result carried (B8; B9 vs B3)

*Category 3: decisions the business can't explain or defend.* `python3 scripts/hw1_trace.py show B8`

**B8.** Order 961 was delivered 2026-05-28, 34 days before the world date. The platform's 30 days would mean the window has closed; Northwind's 45-day override keeps it open until 2026-07-12.
- The agent said "Yes", which is correct, after a single `get_order` call: no policy, no window, no deadline, no citation.
- The yes is the `refund_eligible` flag, which `seed/eligibility.py` stamped with the override already applied. Reasoning from the 30-day rule the agent seems to know (B15 quotes it) would have given the wrong answer.
- It couldn't have reasoned it out anyway: nothing gives the model the current date, so even with the policy in hand it couldn't compute "day 34 of 45" (section 6).

B5 and B2 follow the same pattern with a correct "no", plus an "exception" that no policy offers.

**The same thing happens with policy facts** (`show B3 B9`). Both run `get_order` → `issue_refund`, and neither calls a policy tool:

| | B9: $84, auto-approved | B3: $240, queued |
| --- | --- | --- |
| Tool's note | "refund goes back to the original payment method in 5 to 10 business days" | "amount is above the $100 auto-approval threshold; a human support agent will review it" |
| Agent's timeline | "5 to 10 business days" ✓ | "within 1-2 business days once approved" ✗ (`cw-refunds` says 5 to 10) |
| Evidence check | ✓ `issue_refund.note` | ✗ not in any tool result |

**What the trace shows:** the agent's accuracy depends on what the tool result happens to contain, not on retrieving the required evidence.
- When the result contains the answer (B8's flag, B9's note), the reply is right and looks grounded.
- When it doesn't (B3), the same habit produces a confident wrong number, and category 3 becomes category 1.

The fix is on the tool side:
- put the facts in every branch of the result, including `issue_refund`'s queued branch;
- return the policy ids that apply, as `check_return_eligibility` does.

**Handout question (4455):** the agent called `issue_refund`, not `escalate_to_human`. The tool queued the refund, and the agent correctly described the pending review. The invented timeline is the failure.

## 6. The capability gap: a tool, not a prompt

**How I found it.** Four Part B conversations asked about returns: B2, B5, B8 and B15. Reading their traces side by side showed the same problem four times.
1. **Same shape every time.** Each answered after a single `get_order` call. None fetched `cw-returns` or the store's policy page, and none gave the window that applies to the order or a deadline (`python3 scripts/hw1_trace.py tools`).
2. **The answers contradict the only rule the agent states.** In B15 the agent quotes a 30-day window, yet B8 said "yes" at 34 days and B5 said "closed" at 25 days.
   - Both answers are correct, but only under store overrides the agent never fetched: Northwind's 45 days and Juniper's 14.
   - The one thing in the trace that matches both is `refund_eligible`, which the seed code stamped with the overrides already applied.
   - So the agent wasn't reasoning about return windows at all. It was relaying the flag (5.3).
3. **Relaying the flag breaks when the flag means something else.** In B15, `false` meant "no delivery date". The flag carries no reason, so the agent supplied the most common one, "the window has closed", although `delivered_at: null` was in the same result. It then passed that to a human in the ticket (5.1).
4. **Could a better-behaved agent have answered?** For each piece of a correct answer, I checked where the agent could get it with the Part B tools:

| What a correct answer needs | Where the agent could get it in Part B |
| --- | --- |
| The delivery date | `get_order` (`delivered_at`) |
| The window that applies (30 days, or the store's override) | Only by searching the help center for the store's own policy page and reading the number of days from its text. The agent never tried, in 0 of 20 conversations |
| Today's date, to know how many days have passed | Nowhere. The session context holds only role, user id and store id, and no tool returns the date |
| Why the answer is no | Nowhere. `refund_eligible` is a bare boolean |

**Why that makes it a capability gap, not a prompt problem:**
- **Two of the four inputs don't exist anywhere the agent can reach.** No instruction can make it compute how many days have passed, or know which of six reasons is behind a `false`.
- **The third is reachable only through a multi-step lookup in prose that the agent never started.** The prompt already says that policy answers come from the help center and need a policy id, and the agent followed that in 0 of 20 conversations.
- **B9 showed what does work.** When a fact is in the tool result, the agent uses it: it copied "5 to 10 business days" from the refund note (5.3).

So the fix is to put the answer and its reasons into a tool result.

**The capability: `check_return_eligibility(order_id)`** (`agent/tools.py`, registered for all three roles, same scope as `get_order`). It reuses `seed/eligibility.py`, the code `SPEC.md` assigns the rule to, so it agrees with the stored flag on every consistent record. It returns:
- `eligible`, and a `reason`: `within_window`, `window_passed`, `not_delivered_yet`, `already_refunded`, `cancelled` or `inconsistent_record`.
- **The window:**
  - `return_window_days`;
  - `window_source` (platform default or store override);
  - `delivered_at`, `last_return_day`, and `as_of` (today's date in the data);
  - the `policy_ids` to cite.
- **`data_issues`:** for a record that contradicts itself (a missing or future delivery date, dates out of order, a product the store doesn't sell), it returns `eligible: null` and no deadline, with a note not to estimate one and to escalate.
- `refund_needs_human_approval` and `restocking_fee_may_apply`.

**How it covers the gap,** on the Part B orders (from `call`, offline, no model):

| Order | What the agent said in Part B | What the tool now returns |
| --- | --- | --- |
| 961 (B8) | "Yes", with no window, deadline or citation | `true` · `within_window` · 45 days (store override) · last day 2026-07-12 · `cw-returns`, `cw-store-overrides`, `store-northwind-books-policy` |
| 569 (B5) | "Appears closed", with no reason, and an "exception" | `false` · `window_passed` · 14 days (store override) · last day 2026-06-20 · `cw-returns`, `cw-store-overrides`, `store-juniper-home-goods-policy` |
| 3980 (B2) | "Outside the refund window", with no window or citation | `false` · `window_passed` · 30 days (platform default) · last day 2026-06-16 · `cw-returns` |
| 8002 (B15) | An invented "window closed", copied into the ticket | `null` · `inconsistent_record` · "marked delivered but has no delivery date" · note: "…the return deadline cannot be determined; do not estimate one, escalate to a human" |

Each result gives the agent what RESP-1, RESP-3 and RESP-5 need: the deadline, the reason, and the policy to cite. For B15, it gives an explicit "can't be determined" in place of a bit to misread.

**Status:** the 13 offline tests in `tests/test_hw1_own_tool.py` pass, including agreement with the stored flag on more than 100 consistent orders. No recorded conversation has used the tool yet; the next test is to rerun B5, B8 and B15.

## 7. Part C: a missing instruction for RESP-3

**The requirement:** RESP-3, "State when required information is missing or inconsistent, rather than inventing a value."

**The gap in the prompt:** the starter prompt doesn't say this. "Prefer a tool lookup over memory" says where to look, not what to do when the value found there is wrong or missing. The comment in `agent/agent.py` notes that RESP-3 is "only partly represented".

**Why RESP-3:**
- Of the requirements missing from the prompt, it had the most failures (B3, B12, B14, B15) and the highest severity. ESC-2 and ESC-3 are also missing and are next.
- RESP-1 is more frequent, but it is already in the prompt almost word for word. Its failures are non-compliance, not an omission (section 6).

**How I tested it:**
- **The conversation:** B12's request as shopper 1, "What's the cheapest pitcher Blue Heron Ceramics sells?"
- **Same data every run:** it's read-only and single-turn, so no reset is needed between runs.
- **Failures are the model's:** the tool correctly returns the stored −$5.00, so any failure is the model's decision.
- **Same tools:** `check_return_eligibility` was registered in all three runs, so only the prompt changed.
- **Pass criterion:** −$5.00 isn't presented as a real price, the Rustic Pitcher is flagged or left out, the Matte Pitcher is named at $46, and no prices are invented.

**Before** (B12 and C-before, `d108f6949e5e`): 0 of 2 met. Both noticed the bad price and then "fixed" it by moving the Matte Pitcher's $46 onto the Rustic Pitcher, so they named the wrong product as cheapest. B12 called the −$5.00 "an unusual negative price that appears to be a data issue", then said "the correct price is $46". C-before said:

> The cheapest pitcher Blue Heron Ceramics sells is the **Rustic Pitcher** at **$46.00** (it shows a negative price in the system, but the actual selling price is $46).

**These replies pass a naive grounding check,** because $46 is in the tool output. The viewer flags them only because it checks attribution: "⚠ $46.00 belongs to Matte Pitcher, but the sentence names Rustic Pitcher". Grounding evaluators need to check what a value is attached to, not just whether it appears.

**The edit** (`python3 scripts/hw1_trace.py prompt`):

```diff
 - Prefer a tool lookup over memory. Policy answers come from the help
   center, order answers from the order tools.
+- If a value you need is missing, invalid, or inconsistent in the tool
+  results, say so plainly. Never invent, estimate, or substitute a value.
 - You MUST explain your reasoning in plain text before every tool call.
```

- **Placement:** right after "prefer a tool lookup", because the failure happens while the model reads tool results.
- **Wording:** general on purpose. "Missing, invalid, or inconsistent" and "invent, estimate, or substitute" cover B3, B14 and B15 too.
- **No test-case words:** it doesn't mention prices, pitchers or negative values, which keeps evaluation inputs out of the prompt.
- **Recorded in the code:** a comment in `agent/agent.py` records the requirement and the evidence.
- **Version:** `d108f6949e5e` → `aaa40c2265cf`.

**After** (C-after1 and C-after2, `aaa40c2265cf`): 2 of 2 met.

> I found an issue with the results: the **Rustic Pitcher** is showing a price of -$5.00, which isn't valid. That looks like a data error in the system.
>
> Excluding that invalid entry, the cheapest pitcher Blue Heron Ceramics actually sells is the **Matte Pitcher** at **$46.00** (product ID 38). *(C-after1, shortened; the full reply is in `partc`)*

> Based on the search results, the **Matte Pitcher** at **$46.00** is the cheapest pitcher Blue Heron Ceramics sells (the Rustic Pitcher shows a negative price, which appears to be an error in the system). *(C-after2)*

**What this does and doesn't show:**
- **Sample size:** two runs per side show that the failure reproduces and that the edit removed it on this input. They say nothing about a rate.
- **Generalization:** whether the edit also fixes B3, B14 and B15 is untested.
- **A different problem remains:** C-after1 listed three "other options" from a 5-result page, although the store sells 7 pitchers (C-before's search, with `limit` 10, returned all 7). That's B11's cut-off problem in another tool, an issue for the specification and the tool contract, not RESP-3.

## 8. What I would do next, by severity

1. **RESP-3:** rerun B3, B14 and B15 under the new prompt, and add each as a regression case.
2. **ESC-2 and ESC-3:**
   - Add both categories to the prompt's Escalation section ("account changes and disputes always go to `escalate_to_human`").
   - Narrow the refusal line to "payment-card or payment-credential changes", as SCOPE-2 says, so email changes stop matching it.
   - Test with a before/after on B7 and B16.
3. **RESP-1:** change the tool payloads, not the prompt.
   - Add the 5–10 day timeline to the queued branch of `issue_refund`.
   - Use `check_return_eligibility` for return questions, then check B2, B5 and B8 for citations.
4. **Specification:**
   - TOOL-5 and `search_products`'s limit should say how a cut-off list is signaled, for example with `has_more` or a total count (B11, C-after1).
   - Decide whether the merchant's cancel permission is limited to orders not yet shipped; the AUTH-1 table doesn't say.
5. **Evaluation:** turn the evidence check into an automated grader that checks attribution, since B12 shows a presence-only check misses a moved value.

## Reproduce

```bash
python3 scripts/hw1_trace.py                 # all 20 records
python3 scripts/hw1_trace.py show B15        # one trace with its evidence check
python3 scripts/hw1_trace.py evidence        # grounding across all records
python3 scripts/hw1_trace.py partc           # Part C before and after
python3 scripts/hw1_trace.py prompt          # the exact prompt edit and both versions
uv run python scripts/hw1_trace.py call 392 check_return_eligibility order_id=8002
uv run pytest --runxfail tests/test_hw_holes.py tests/test_hw1_own_tool.py -k hw1
uv run pytest tests/test_agent_tools.py tests/test_auth.py tests/test_eligibility.py
```
