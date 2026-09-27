# HW5 video prep (up to 5 minutes, one continuous take)

Homework 5, build and evaluate an LLM judge

Start the review app first: `uv run python -m analysis.review_app.server` (port 8030). To jump straight to a judge version, list filter, and conversation in the HW5 tab, use a link like `http://localhost:8030/?view=hw5&judge=verbose_reply-v0&filter=disagree&conv=support-0047` (filters: `needs_review`, `carried`, `done`, `labeled`, `all`, `disagree`, `disagree_open`, `dev`, `train`). Have a terminal open in the repo for the report file and the live recalculation.

Open all links in browser: ```grep -oE 'http://localhost:8030/\?view[^ )`]*' homework/module-2/hw5-video-prep.md | sort -u | xargs -n1 open```

## 1. Walk through your failure mode
- Open: http://localhost:8030/?view=hw5&judge=verbose_reply-v0&filter=train&conv=support-0164 (definition panel at the top, then the training reply), with `homework/module-2/hw5-progress.md`, section "Failure definition (v1, 2026-09-26)", as backup.
- `verbose_reply` asks whether the final reply contains content the user did not need: Fail on repetition (including "not X" contrasts), unneeded mechanics, or unsolicited next steps, while required refund and status fields, outcome explanations, and refusals with a way forward are fine. I chose it because it was the only HW4 mode with 30+ Fail conversations that needs judgment, and labeled 100 eligible conversations (0164 is the clear Fail training example: "not 30 days from the purchase date").
- Show 8 and 177

## 2. One development disagreement and how you responded
- Open: http://localhost:8030/?view=hw5&judge=verbose_reply-v0&filter=disagree&conv=support-0047
- The user asked how long they have to dispute a charge; I labeled the reply Pass, v0 said Fail, and on review I decided my label was wrong because ", not automatically" states what is not true instead of what is. I relabeled it Fail, applied the same call to 0237 in training, and the "not X" contrast became part of rule 1 in the later prompts (with the 5 relabels, v0 dev TPR went from 0.33 to 0.44, `analysis/report/dev-verbose_reply-v0-relabeled.json`).

## 3. Your test TPR, TNR, and confidence intervals
- Open: `analysis/report/test-verbose_reply-v0.json`
- Frozen v0 on 40 test traces (21 Pass, 19 Fail): TP 4, FN 17, TN 17, FP 2 (0192, 0202). TPR 0.1905 [0.0767, 0.4000], TNR 0.8947 [0.6861, 0.9706], agreement 0.525.

## 4. Explain whether you would use the judge.
- Open: `analysis/report/verbose_reply-versions.md` (version table, then "What these rates mean in practice").
- I would not use it: across five prompt versions it kept failing good replies with every persion, the TPR ever not to .50, so this is not strong enough to discriminate. I would probably try to first update the system prompt with instructions to improve verbosity, and see if some of these cases just go away so there are not so many failures. And try another round with crystal clear criteria.

## 5. Recalculate test metrics from saved predictions live on camera.
- Open terminal: 
```
uv run python 
from analysis.helpers import judge_alignment as a
r = a('verbose_reply-v0', 'test')
r['disagreements']; print(r)
```
- This reads only the saved predictions in `analysis/state/judges/verbose_reply-v0.json`, your labels in `analysis/state/hw5_labels/verbose_reply.jsonl`, and `analysis/state/splits.json`; no model call. It prints TP 4, FN 17, TN 17, FP 2, TPR 0.1905 [0.0767, 0.4], TNR 0.8947 [0.6861, 0.9706], matching item 3.
