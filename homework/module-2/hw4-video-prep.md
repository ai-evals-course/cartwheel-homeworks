# HW4 video prep (5 minutes, one take, no slides)

Human Trace Review & Failure Taxomony

Start the review app first: `uv run python -m analysis.review_app.server` (port 8030). To jump straight to a conversation, use a link like `http://localhost:8030/?batch=batch4_uniform&conv=support-0097` (add `&view=labeling` or `&view=taxonomy` for another tab). Have a terminal open in the repo for the two file sections.

Open all links in brower: ```grep -o 'http://localhost:8030[^ )]*' homework/module-2/hw4-video-prep.md | xargs -n1 open```

## 1. One interface decision made after inspecting the traces.
- Open: http://localhost:8030/?batch=batch4_uniform&conv=support-0011&view=review
- In Langfuse, following one conversation meant clicking into every tool call and losing the thread. Here all turns in a session sit on one page, each tool call on one row with arguments and result summary, expandable only when you need the payload, so you scroll and open-code without leaving the trace. Scroll both turns, expand one `find_order` result, highlight a sentence to annotate.

## 2. One Workshop suggestion and your decision to accept, revise, or reject it.
- Open: `analysis/report/workshop_notes.md`, section W1, then http://localhost:8030/?conv=support-0054&view=suggestions (Accepted table, row `support-0054 / no_reference_date`).
- Workshop replays showed the agent guessing today's date: 0054 called a July 12 deadline "past" while the tool said `refund_eligible: true` (the world is as of July 1, 2026). You accepted it; it became the mode `no_reference_date` and RESP-7.

## 3. Two failure modes and one supporting trace for each mode.
- Open: http://localhost:8030/?view=taxonomy (read `write_without_confirmation` and `unwarranted_escalation`), then http://localhost:8030/?batch=batch4_uniform&conv=support-0176&view=review, then http://localhost:8030/?batch=batch4_uniform&conv=support-0052&view=review
- `write_without_confirmation`: 0176, shopper says "I think I need to cancel it", agent calls `cancel_order` with no confirmation turn (point at the red write row). `unwarranted_escalation`: 0052 turn 1, order 28 was delivered in March, months past the 30-day window, so policy already answers the request, yet the agent opens ticket 164 "in case there are special circumstances".

## 4. One taxonomy revision or rejected group.
- Open: http://localhost:8030/?view=taxonomy, `unwarranted_escalation`, and read the definition's clauses (a), (b), (c).
- Two groups became one mode. "Premature escalation" was tickets opened before the order was confirmed (clause a, notes on 0168, 0222, 0118); "unnecessary escalation" was tickets for things already handled (clauses b and c). Merged because one fix covers both: confirm the order and check the tool result before opening a ticket.

## 5. One rejected search suggestion and the boundary excluding it.
- Open: http://localhost:8030/?conv=support-0035&view=suggestions (Rejected table, row `support-0035 / verbose_reply`).
- Suggested as a close negative because the reply is 84 characters; you rejected it because it says "cancelled" twice. Read your reason aloud: the boundary is repetition, not length.

## 6. One relationship between a mode and `SPEC.md`.
- Open: `SPEC.md`, section 6, RESP-6 (search "RESP-6").
- `write_without_confirmation` and RESP-6: the rule did not exist before HW4, was added from 0053/0066/0134, widened after 0167/0176, then tightened to "order number or widget" after the search review. The annotation ids are inline in the paragraph.

## 7. The number of new modes found in the final 15 reviewed traces.
- Open: http://localhost:8030/?batch=batch4_uniform&conv=support-0097&view=review
- "I found 1 new mode in the final 15." It was `incomplete_write_outcome`: 0097's queued refund reported as "submitted for approval" with no amount, order, or timing. I flagged 5 things as possibly new, 4 turned out to be tool design, a product idea, tone, or already covered; 1 new mode meant the taxonomy was stable and I did not draw a fifth batch. It was later promoted to the tenth mode `incomplete_outcome_report`.

## Scope statement (say once, near the end)
- Open: http://localhost:8030/?view=progress as a backdrop.
- Ten final modes (above the handout's eight, by decision), five labeled on 64 conversations, with 0192 labeled on 2 of 20 turns and batch 3 left for HW5.
