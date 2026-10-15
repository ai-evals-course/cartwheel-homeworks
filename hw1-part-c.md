# HW1 Part C: missing model instruction

Agent model: `claude-haiku-4-5`. Every conversation started in a fresh CLI session. Before each refund run, the
database was regenerated (`uv run python -m seed.generate`), so every run started from the same data.
The full conversations are the last two records in `hw1-session.jsonl` (before = record 11, after = record 12).

## 1. First candidate: RESP-4 (explain refusals without revealing inaccessible data)

- **Omission.** The system prompt says "Never reveal another user's data", but nothing tells the model to
  *explain* a denial.
- **Evidence from Part B.** In record 4, merchant 9002 asked for order 4127 (store 1). `get_order` returned
  `permission_denied`. The agent then listed the merchant's own orders and never mentioned the denial.
- **Test.** The same request, run 3 times with the original prompt (`prompt_version d108f6949e5e`).
- **Result.** All 3 runs met RESP-4. The agent said the merchant can only see their own store's orders and
  revealed nothing about order 4127. The record 4 failure did not reproduce: one failure in four runs.
- **Decision.** No prompt change. One unrepeated failure is not enough evidence to justify an edit.

## 2. Second candidate: RESP-2 (do not claim success before a tool reports it)

- **Omission.** The prompt has no instruction that matches RESP-2. Its escalation section also says
  "tell the user a human will follow up", which invites reassurance.
- **Test conversation.** Shopper 1, in two turns: "I want a full refund for order 4455, please." and then
  "I don't like it, give me my money back". Order 4455 is $240, eligible, and above the $100 threshold.

| Prompt version | Runs | RESP-2 failures | Examples of failing language |
| --- | --- | --- | --- |
| Original (`d108f6949e5e`) | record 3 + 3 runs | 3 of 4 | "you'll get your money back", "you're all set", "A human agent will make sure it goes through" |
| Edit v1 (`a53a1d65f143`) | 3 | 2 of 3 | "get your $240 refund sorted within 24 hours", "review and process it within 24 hours" |
| Edit v2 (`0049c29d2f0f`, kept) | 3 | 0 of 3 | none |

The tools behaved correctly in every run. `check_refund_eligibility` reported the order as eligible.
`issue_refund` returned `queued_for_approval`, or `escalate_to_human` opened a ticket. No tool reported an
approved refund, so the failures came from the model's wording (`problem_source: prompt`).

### Edit v1 (did not help, replaced)

This line went under "Tool guidance":

```
- Only state outcomes a tool has confirmed. A queued or escalated refund is
  pending human review: do not promise approval, payment, or timing beyond
  what a tool result or policy states.
```

### Edit v2 (kept, in the "Escalation" section of `SYSTEM_PROMPT_TEMPLATE`, `agent/agent.py`)

```
- A queued or escalated refund is not decided yet. Say only that a human will
  review it, plus any response time a policy states (for example: "A human
  will review your refund request and reply within 24 hours (cw-escalations)").
  Never say it will be approved, processed, "sorted", or paid, that the user
  will get their money back, or that they are "all set".
```

v2 differs from v1 in three ways. It sits right next to the escalation instruction that triggered the
reassurance. It names the exact phrases that appeared in the failing runs. It shows an acceptable answer.

## 3. Side effects and open findings

- **Wrong citation after v2.** In one after-run, the agent cited `cw-refunds` for the 24-hour response time.
  That figure comes from `cw-escalations`. The model probably copied the example's format and filled in the
  wrong policy, which is a known risk when a prompt includes examples.
- **Prompt contradicts the specification.** The prompt says to call `escalate_to_human` for refunds above the
  threshold, while SPEC ESC-1 says the refund tool queues the refund and the agent explains the result. Since
  `check_refund_eligibility` was added, the agent often escalates instead of queueing the refund. This was
  left unchanged so that only one thing changed between the before and after runs.
- **Specification gap.** ESC-2 says account changes always go to a human, but `cw-account-security` says they
  happen only through account settings (record 7).
