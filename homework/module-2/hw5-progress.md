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

### Definition v2 (2026-09-26, after v0 dev review)

Changes from v1, from the dev disagreement review (no dev text in the prompt):

- Rule 3 narrowed: unsolicited next steps are offers of a different or additional action. Telling the user how to continue the same request is not rule 3.
- Never verbose, added: explaining the outcome in one or two sentences (why it could not be done, was escalated, or was queued; RESP-4, ESC-1); lookup details that confirm the answer; a brief refusal plus one sentence on what the user can do instead; a link to the relevant policy in a refund or cancellation report; "queued for human review" is a required field.
- Short-answer requests (RESP-8): keep the outcome, the required fields, and a clause on why it cannot be done. Explanations of how the process works (thresholds, internal rules, approval mechanics) become unneeded mechanics.

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
- [x] Inspect every v0 disagreement (14) and record a decision (2026-09-26): judge wrong 5 (0028, 0042, 0087, 0115, 0132), label wrong 5 (0006, 0047, 0066, 0120, 0183, relabeled Pass to Fail), definition unclear 4 (0172, 0174, 0229, 0250)
- [x] Revision 1: `analysis/prompts/verbose_reply-v1.txt` (definition v2; adds training examples 0030 and 0184; dev-derived wording removed). Run 2026-09-26, `analysis/report/dev-verbose_reply-v1.json`
- [x] Inspect every v1 disagreement (12): definition unclear 6, judge wrong 4, label wrong 2 (0042, 0229 to Fail); dev now 14 Pass / 26 Fail
- [x] Revision 2: `analysis/prompts/verbose_reply-v2.txt` (same rules; allowed categories first, tagged sentence-by-sentence critique, default Pass unless a quoted sentence breaks a rule; examples 0134, 0164, 0030, 0184). Run 2026-09-27, `analysis/report/dev-verbose_reply-v2.json`
- [ ] Inspect every v2 disagreement (10)
- [x] Revision 3 (beyond the handout's two-revision limit, my choice): `analysis/prompts/verbose_reply-v3.txt`, written fresh by a separate agent from training data, my labels and notes, and the dev error review only (no earlier prompts). 4.5k characters; examples 0164 (Fail), 0030 (Pass), 0184 (Pass), 0194 (Fail); Example 1 critique also cites the store override paragraph (rule 2). Run 2026-09-27, `analysis/report/dev-verbose_reply-v3.json`
- [x] Revision 4: `analysis/prompts/verbose_reply-v4.txt` = v3 plus the out-of-scope exception in rule 3. Run 2026-09-27, `analysis/report/dev-verbose_reply-v4.json`
- [ ] Why I stopped revising

| Version | Change | Dev TPR [95% CI] | Dev TNR [95% CI] | Label flips |
| --- | --- | --- | --- | --- |
| v0 | initial draft (0134, 0164, 0237 examples; visible conversation only) | 0.333 [0.172, 0.546] (TP 7, FN 14) | 1.000 [0.832, 1.000] (TN 19, FP 0) | 0 |
| v0, relabeled | same predictions, 5 dev labels fixed after review (dev now 16 Pass / 24 Fail); `analysis/report/dev-verbose_reply-v0-relabeled.json` | 0.438 [0.231, 0.668] (TP 7, FN 9) | 1.000 [0.862, 1.000] (TN 24, FP 0) | 5 |
| v1 | definition v2 rules (outcome explanations, refusals, short-answer rule, narrower rule 3); training examples 0030 and 0184 added | 0.250 [0.102, 0.495] (TP 4, FN 12) | 1.000 [0.862, 1.000] (TN 24, FP 0) | 0 |
| v2 | same rules; allowed categories first, sentence-by-sentence tagged critique, Fail only on a quoted sentence; examples 0134, 0164, 0030, 0184 | 0.429 [0.214, 0.674] (TP 6, FN 8) | 0.923 [0.759, 0.979] (TN 24, FP 2) | 0 |
| v3 | fresh 4.5k prompt (default Pass, quote-to-fail, 3 rules, 4 training examples); third revision | 0.357 [0.163, 0.612] (TP 5, FN 9) | 1.000 [0.871, 1.000] (TN 26, FP 0) | 0 |
| v4 | v3 plus a rule 3 exception: after refusing an out-of-scope request, one sentence on what the assistant can help with is fine; fourth revision | 0.357 [0.163, 0.612] (TP 5, FN 9) | 0.962 [0.811, 0.993] (TN 25, FP 1) | 0 |
| **All on current labels** (14 Pass / 26 Fail) | v0 0.500 [0.268, 0.732] / 1.000 [0.871, 1.000]; v1 0.286 [0.117, 0.547] / 1.000; v2 0.429 [0.214, 0.674] / 0.923 [0.759, 0.979] | | | |

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
- **2026-09-27, support-0237 is a Fail.** ", not automatically" is an unrequested contrast (rule 2), the same call as support-0047. Training label changed to Fail (repetition). Not used as an example in v2; the unedited reply stays in the v0 and v1 prompts as they were run.
- **2026-09-27, third revision.** v1 and v2 each fixed some dev errors and caused others, and both got longer. I asked for a fresh, shorter prompt written without looking at v0 to v2, to test whether a simpler prompt does better. This exceeds the handout's two revisions and makes dev scores more optimistic; the test split is still untouched, so the test result stays unbiased.
