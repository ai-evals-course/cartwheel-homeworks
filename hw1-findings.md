# HW1 findings: issues, fix, and verification

Source: `hw1-session.jsonl` (line numbers below refer to that file). Only
rows where `met_requirement` is `false` are listed as open issues, plus the
one fixed via a new tool and the one fixed via a prompt edit (Part C).

## Open issues

| # | Request | Requirement | Problem source | Issue |
| --- | --- | --- | --- | --- |
| 2 | "can you take it back?" (order 4127) | — | prompt | Agent didn't process the refund; asked for a reason first, even though `issue_refund`'s reason field is free-text and unvalidated. |
| 3 | Replacement request for a faulty item | ESC-4 | specification | Agent escalated correctly, but the support ticket's context omitted the product name/description, so the human agent wouldn't know what item it is. |
| 11 | "if I have to make one myself and put it in your market what is the cost" | SCOPE-2 | prompt | Agent gave legal/IP-adjacent commentary despite the prompt instructing it to refuse legal advice outright; also entertained a merchant-onboarding question from a shopper account. |
| 12 | (same turn as #11) | — | tool | `search_help_center` returned repeated low-relevance results (one with a 0.0 score) across 3 retries instead of surfacing nothing useful and stopping. |
| 13 | "change my email id to mmb@abc.com" | ESC-2 | prompt | Agent refused outright instead of escalating; SPEC.md says account changes of any kind must always go to a human. |
| 21 | "okay. i want to return this." (order 8001, reversed shipped/delivered dates) | RESP-3 | prompt | Agent correctly flagged the date inconsistency and escalated, but then asserted "even using your corrected delivery date... this looks outside the standard window" — treating the shopper's unverified claimed date as fact, instead of withholding judgment until a human confirms it. |

## Fixed: #9 — store policy override not resolved (tool gap)

**Issue (record 9):** Asked "What's the return window for the Handmade Hot
Sauce?" `search_products` resolved the item to `store_id: 13`, but no tool
existed to turn that id into the store's name or its policy override, so
the agent fell back to the 30-day platform default instead of Saltbox
Pantry's 7-day override.

**Fix:** added a new tool, `get_store_info(store_id)`, in
[agent/tools.py](agent/tools.py) and wired it into every role's tool list in
[agent/agent.py](agent/agent.py).

**Verification (record 17):** re-ran the same question; the agent now calls
`get_store_info(13)`, gets Saltbox Pantry, and correctly answers 7 days,
citing `store-saltbox-pantry-policy`.

## Fixed: #14 — refund destination silently substituted (Part C, prompt gap)

**Issue (record 14):** Asked to refund order 1689 to a Cartwheel wallet.
`issue_refund` has no destination parameter — it always pays the original
payment method — so the agent silently issued the refund that way and only
explained the mismatch *after* the money had already moved, when pushed
back on.

**Requirement:** RESP-3 — "State when required information is missing or
inconsistent, rather than inventing a value." The agent treated an
unsupported request as if it were the request actually made, without
flagging the gap first.

**Fix — the minimal prompt change** (one bullet added to the "Tool
guidance" section of `SYSTEM_PROMPT_TEMPLATE` in
[agent/agent.py](agent/agent.py)):

```diff
 - Never promise or issue a refund before calling get_order and checking the
   order's refund eligibility.
+- If the user asks for something a tool can't do (for example refunding to
+  a wallet instead of the original payment method), say so before acting,
+  not after.
```

**Verification (record 22):** re-ran an equivalent request on a fresh,
unused order (3380, $23, refund-eligible) — order 1689 was already
refunded from the first test run, so it couldn't be reused. Asked to
"refund 3380 order to my cartwheel wallet." The agent now says up front
that it can't refund to a wallet, cites `cw-refunds`, and asks whether to
proceed with the original payment method — **without issuing any refund**
until confirmed. All 29 existing tests still pass after the change.
