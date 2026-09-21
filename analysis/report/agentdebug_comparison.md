# Comparison with the AgentDebug taxonomy (HW4 Part D)

Reference: "Where LLM Agents Fail and How They can Learn From Failures" (arXiv 2509.25370), whose AgentErrorTaxonomy groups errors by module: Memory (incomplete summary, false memory, retrieval failure), Reflection (progress misassessment, outcome misinterpretation, causal misattribution, hallucination), Planning (constraint ignorance, impossible action, inefficient planning), Action (planning-action disconnect, format error, parameter error) and System (step limit, tool execution error, LLM limit, environment error). Its "critical error" is the earliest step whose correction prevents the final failure, which is the same stopping rule the handout uses for open coding.

Drafted by the coding agent on 2026-09-20 from the eight final modes in `analysis/state/patterns.json`. Decisions belong to the reviewer; nothing here changes the taxonomy on its own.

## Mode by mode

| Cartwheel mode | Nearest AgentDebug type | Note |
|---|---|---|
| write_without_confirmation | Planning: constraint ignorance | The constraint is a product rule (RESP-6), not a physical one. Our name says what happened; theirs says which module to blame. Keep ours. |
| assumes_instead_of_asking | none | AgentDebug has no clarification category because its agents do not converse with a user mid-task. Nothing to borrow. |
| unwarranted_escalation | Planning: inefficient planning, or constraint ignorance (ESC-3) | Their split does not help here: the product change (tighten the escalation rule in the prompt) is the same either way. |
| redundant_policy_lookup | Planning: inefficient planning AND Memory: retrieval failure | AgentDebug separates "the agent wasted steps" from "the information existed but was not retrieved". The Workshop replays (W2 in `workshop_notes.md`) show both inside this one mode: repeats the agent chose (0011 turn 0 re-searched after already holding the policy) and repeats forced by ranking (0230, 0152, 0052, where `search_help_center` put store overrides or `cw-refunds` above `cw-returns`). Different product changes. See "Possible revision" below. |
| irrelevant_policy_nuance | none | Communication quality. Outside AgentDebug's scope. |
| unsolicited_next_steps | none | Same. |
| verbose_reply | none | Same. |
| first_person_framing | none | Same. |
| incomplete_write_outcome (backup) | Reflection: outcome misinterpretation is the closest, but wrong | The agent read the tool result correctly and reported too little of it. AgentDebug has no "under-reporting" type. |

Four of eight final modes are user-facing communication failures with no AgentDebug counterpart. That is expected: AgentDebug scores task success in benchmarks, Cartwheel is judged on what a shopper or merchant reads.

## Possible omission, checked against the traces

AgentDebug types absent from our taxonomy, and what the 313 traces show:

- **Reflection: outcome misinterpretation.** Present in the data. In support-0054 (replay) the agent held `refund_eligible: true` and told the shopper the order was past the return window; in support-0230 it explained `refund_eligible: false` with a deadline it computed from an unknown "today". The reviewer's Workshop suggestion W1 (`no_reference_date`) names the cause (no date in the prompt); AgentDebug's name describes the symptom (the tool result was overridden by the agent's own inference). If W1 is accepted, this comparison argues for defining it by the symptom, for example "the reply contradicts or explains away a field the tool returned", with the missing date as the first known cause. That definition is checkable by a judge and survives the prompt fix.
- **Action: parameter error.** Not present. All 51 `issue_refund`/`cancel_order` calls used valid arguments; the two refunds whose amount differed from the order total (support-0133, support-0231) were partial refunds the shopper asked for, executed correctly. One `search_products` call returned `invalid_argument`. Not enough to support a mode.
- **System: tool execution error.** Not present as a failure. The 7 `permission_denied` results on `get_order` are the authorization layer working; the agent handled them.
- **System: step limit exhaustion.** Not observed. The longest turn made 12 tool calls (support-0023) and completed.
- **Memory: retrieval failure.** Present, but currently folded into `redundant_policy_lookup` (above).

## Unclear name

`redundant_policy_lookup` reads as an agent decision. AgentDebug's module split shows it covers two causes with two owners (prompt versus retrieval ranking). Options for the reviewer:

1. Keep one mode and add to its boundary: "counts whether or not the repeat was caused by ranking; the label records the symptom, the retrieval cause goes to the tool-design backlog". Simplest, keeps the 8-mode cap.
2. Narrow the definition to agent-chosen repeats (the agent already held the policy text, or the first result answered the question) and record ranking-forced repeats as a SPEC gap on TOOL-1 rather than a mode. Cleaner attribution, but the existing 12 positives would need a recheck.

## Possible revision, if the reviewer accepts W1

Adding a ninth mode would break the 8-mode cap. Candidates to make room: fold `first_person_framing` (3 positives, 0 close negatives) back into `verbose_reply` as a tone clause, or keep W1 as a recorded SPEC revision (inject the world date into the prompt) without a judged mode. The handout allows adding a mode only when the traces and human annotations support it; W1 currently has three traces (0054, 0230, 0245 turn 1) and no human open code yet, so it needs the reviewer's own annotation on each before it can qualify.
