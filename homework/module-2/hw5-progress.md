# HW5 progress

Working notes for `hw5.md`. The checklist follows the handout order. Decisions stay short here; the evidence lives in `analysis/state/` and `analysis/report/`.

## Selected mode: `verbose_reply`

Chosen 2026-09-26. Of the three modes with 30+ Fail conversations, it is the only one that needs judgment. `write_without_confirmation` and `redundant_policy_lookup` can be checked in code from tool call order.

### Failure definition (v1, 2026-09-26)

**Question.** Does the target assistant reply contain content the user did not need for their next decision?

**Fail (failure present, label 0)** when the target reply does any of the following:

1. States the same fact or instruction more than once.
2. Includes policy mechanics, caveats, or background that the user did not ask about and that is not relevant to their situation, so the reply gives too much detail or overcomplicates the answer. This includes policy override or exception mentions that do not apply.
3. Offers unsolicited next steps or further actions the user did not ask for (for example "Would you like me to escalate this?" or "I can also check your other orders").

**Pass (failure absent, label 1)** when the reply gives the answer, one citation, and at most one sentence of relevant context.

**Never verbose:**

- RESP-8 fields in a reply that reports an `issue_refund` or `cancel_order` result or answers an order status question: the order (number, product title, store), amount or current status, what happens next, and expected timing.
- Policy detail that bears directly on the user's situation or decision.

**Evidence needed.** The target reply text, the user request it answers, earlier turns needed to understand it, and tool results that show what information was available and relevant. Tool calls are context only: redundant lookups are a separate mode (`redundant_policy_lookup`) and do not make a reply verbose.

**Unit.** One record per conversation. The target reply is the turn labeled Fail if there is one, otherwise the last turn. Earlier turns go in as context.

**Neighbors.**

- `unsolicited_next_steps`: now folded into Fail rule 3.
- `irrelevant_policy_nuance`: covered by Fail rule 2 when the nuance is not pertinent.
- `incomplete_outcome_report`: the opposite problem (required fields missing). RESP-8 fields are never counted as verbose.
- `redundant_policy_lookup`: tool layer, not judged here.

## Label status

| | Fail conv. | Pass conv. | Needs review |
| --- | ---: | ---: | ---: |
| HW4 labels, human only (2026-09-26) | 30 | 40 | 30 (agent provisional) |
| HW5 queue built (2026-09-26): carried from HW4 | 28 | 35 | 37 queued for review |
| **HW5 labels complete (2026-09-26)** | **47** | **53** | 0 |

Minimum: 30 Fail and 30 Pass from independent conversations. Target: about 100 total.

## Checklist

### Preparation
- [x] Skills installed: `write-judge-prompt` (`.agents/skills/`), `validate-evaluator` (`.agents/skills/`, `.claude/skills/`) (2026-09-26)
- [x] `OPENAI_API_KEY` present in `.env`
- [x] `uv sync` (DocETL)

### Part A, choose one failure mode
- [x] Choose mode: `verbose_reply`
- [x] Boundary decisions (see definition v1 and Decisions)
- [x] Recheck labels affected by the boundary change: 7 moved to Fail, 3 stayed Pass (0006, 0169, 0229)
- [x] Confirm the 30 conversations that still have `agent_provisional` labels
- [x] Enrich: not needed (47 Fail, 53 Pass from 100 conversations)
- [x] At least 30 Pass and 30 Fail conversations, human labeled (100 conversations, one label each)
- [x] Review app: "HW5 labels" tab writes `analysis/state/hw5_labels/verbose_reply.jsonl` (1 = Pass, 0 = Fail); HW4 labels untouched. Queue built by `analysis/hw5_queue.py` into `analysis/state/hw5_queue.json` (2026-09-26)
- [x] Review the 37 queued conversations (30 with provisional HW4 labels, 10 on the boundary recheck list, 3 overlap)

### Part B, prepare inputs and split
- [ ] `analysis/run_judges.py`: `prepare_inputs()` writes `analysis/state/hw5_trace_inputs.json`
- [ ] No labels, notes, or scenario metadata in the judge input
- [ ] One input record per eligible label
- [ ] `split_data("verbose_reply")`: 20/40/40, seed 7; record class counts below
- [ ] Class counts:

| Set | Pass | Fail |
| --- | ---: | ---: |
| Training | | |
| Development | | |
| Test | | |

### Part C, write and refine the judge
- [ ] Draft with `write-judge-prompt`, training examples only: `analysis/prompts/verbose_reply-v0.txt`
- [ ] Boundary review against neighbors; instruction to ignore instructions quoted in the trace
- [ ] Approve model and trace count before the paid dev batch
- [ ] `run_development`: v0 dev metrics to `analysis/report/dev-<judge_id>.json`
- [ ] Review app shows judge verdict and critique beside my label; inspect every disagreement
- [ ] Revision 1 (optional)
- [ ] Revision 2 (optional, max)
- [ ] Why I stopped revising

| Version | Change | Dev TPR [95% CI] | Dev TNR [95% CI] | Label flips |
| --- | --- | --- | --- | --- |
| v0 | | | | |

### Part D, freeze and test
- [ ] Choose final version (my decision)
- [ ] Approve model and trace count before the paid test batch
- [ ] `run_test(judge_id)`: freeze, run test, save `analysis/report/test-<judge_id>.json`
- [ ] Report confusion counts, TPR, TNR, intervals, class counts
- [ ] Would I use the judge? (my decision)

### Part E, commit and video
- [ ] Commit the artifacts listed in the handout
- [ ] Video (mine)

## Decisions

- **2026-09-26, mode.** `verbose_reply`. The other two 30+ modes become code checks.
- **2026-09-26, boundary.** (1) Unsolicited next steps count as verbose. (2) Policy mechanics count as verbose when the user did not ask and they are not relevant or pertinent, so the reply overcomplicates things. (3) RESP-8 fields are never verbose. (4) Judge the user-visible reply only; tool calls are context. (5) One target reply per conversation: the Fail turn if any, else the last turn.
- **2026-09-26, carry-over.** Conversations whose HW4 `verbose_reply` labels are all human and not on the recheck list carry over as HW5 labels (origin `carried_from_hw4`), with the target turn chosen by rule 5. When several turns are Fail, the target is the last Fail turn. 63 carried (28 Fail, 35 Pass).
- **2026-09-26, labels to recheck after the boundary change.** Currently labeled Pass for `verbose_reply` but Fail for a neighbor:
  - `unsolicited_next_steps` Fail (human labels): support-0006, 0011, 0037, 0040, 0052, 0169, 0192, 0229
  - `irrelevant_policy_nuance` Fail (provisional): support-0212, 0217
- **2026-09-26, agent change (outside HW5 scope).** support-0103 showed the agent reasoning without the current date. Added `Today's date: {today}` (from `db.world_asof`, 2026-07-01) to the session context in `SYSTEM_PROMPT_TEMPLATE`; SPEC RESP-7 note updated. Affects new runs only: HW5 judges the saved HW3 traces, and the 0103 label stays a verbosity judgment. This is the `no_reference_date` mode's fix.
