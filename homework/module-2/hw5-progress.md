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
- [x] Label support-0164 (enrich candidate): Fail, unneeded mechanics. 101 labels, 100 eligible
- [x] Regenerate `analysis/state/hw5_trace_inputs.json` with `prepare_inputs()` (trimmed format, 100 records, 2026-09-26)
- [x] `analysis/run_judges.py`: `prepare_inputs()` writes `analysis/state/hw5_trace_inputs.json`
- [x] No labels, notes, quotes, scenario metadata, or system prompt in the judge input (checked in `check_inputs`)
- [x] One input record per eligible label (100; support-0235 excluded as a close variant of 0052)
- [x] `split_data("verbose_reply")`: 20/40/40, seed 7, run once (2026-09-26)
- [x] Class counts:

| Set | Pass | Fail |
| --- | ---: | ---: |
| Training | 11 | 9 |
| Development | 21 | 19 |
| Test | 21 | 19 |

### Part C, write and refine the judge
- [x] Draft with `write-judge-prompt`, training examples only: `analysis/prompts/verbose_reply-v0.txt` (examples: 0134 clear Pass, 0164 clear Fail, 0237 borderline Pass; all training)
- [x] Boundary review against neighbors; instruction to ignore instructions quoted in the trace
- [x] Approve model and trace count before the paid dev batch (gpt-4o-mini, 40 dev traces, approved 2026-09-26)
- [x] `run_development`: v0 dev metrics to `analysis/report/dev-verbose_reply-v0.json`
- [x] Review app shows judge verdict and critique beside my label (HW5 tab, decisions saved to `analysis/state/hw5_dev_review.jsonl`)
- [ ] Inspect every v0 disagreement (14) and record a decision
- [ ] Revision 1 (optional)
- [ ] Revision 2 (optional, max)
- [ ] Why I stopped revising

| Version | Change | Dev TPR [95% CI] | Dev TNR [95% CI] | Label flips |
| --- | --- | --- | --- | --- |
| v0 | initial draft (0134, 0164, 0237 examples; visible conversation only) | 0.333 [0.172, 0.546] (TP 7, FN 14) | 1.000 [0.832, 1.000] (TN 19, FP 0) | 0 |

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
- **2026-09-26, judge input format.** Built with the review app's `build_turn`, so the judge sees the same tool pairing I labeled from. Roles: `user`, `tool_call` / `tool_result` (tool name carried inside the data, because the helper's flattening drops the `name` field), `assistant` (the reply the user saw; the last one is judged). Turns after the target are left out.
- **2026-09-26, close variants.** support-0235 dropped from the inputs as a close variant of support-0052 (same late refund refusal, same tool sequence, both Fail). Label kept in `hw5_labels/`. support-0011 and support-0120 share an opening template but the agent behaved differently; both kept.
- **2026-09-26, frozen inputs.** Run judges with `export CARTWHEEL_JUDGE_TRACE_SOURCE="$PWD/analysis/state/hw5_trace_inputs.json"`. `prepare_inputs()` refuses to rewrite the file once a `verbose_reply` judge is registered; `split_data()` refuses to re-split.
- **2026-09-26, split reset before any prompt work.** A first split of the 99 eligible labels ran (train 11/9, dev 21/18, test 21/19 Pass/Fail) and was removed from `splits.json` before any prompt examples were chosen or any judge was registered, so one more conversation could be labeled. The split runs again, once, after support-0164 is labeled.
- **2026-09-26, light uniform trim.** Judge inputs drop the model's pre-tool text (`agent_reasoning`): the user never sees it and it was not evidence for any label. Every tool call and result stays, because rule 2 (relevance to the user's situation) and the RESP-8 exception depend on order records and write results (HW5 handout line 92: include the tool data used to decide). Same rule for every record. Median input 2.6k to 1.8k characters.
- **2026-09-26, support-0194 kept Fail** (training): repetition, the delivery date is stated three ways.
- **2026-09-26, visible conversation only.** Tool calls and results removed from the prompt examples and from `hw5_trace_inputs.json` (option A): verbosity is judged from what the user saw, and I labeled from the reply itself. Inputs are `user` and `assistant` messages for every turn up to the target (median 645 characters). Supersedes the light-trim entry above. Trace ids unchanged, so the split stands. Known risk: relevance calls that depend on facts the reply does not state (for example support-0008, where no store override applied).
- **2026-09-26, target turn mix-up (dev).** The queue picked the target turn from HW4 labels, including agent-provisional ones. For support-0120 and support-0038 that made turn 1 of 2 the target, while I read to the end of the conversation. The judge saw only turn 1. Inputs are locked after v0, so the fix is to relabel those two against turn 1, not to move the target. The review app no longer allows moving the target for conversations in the split.
