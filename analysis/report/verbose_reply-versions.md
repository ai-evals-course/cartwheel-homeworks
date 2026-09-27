# verbose_reply judge: every prompt version

All runs use `gpt-4o-mini`. Pass is the positive class: **TPR** is agreement with my Pass labels, **TNR** is agreement with my Fail labels (catching verbose replies). Intervals are 95% Wilson.

## Development (40 traces), all versions on my current labels (14 Pass, 26 Fail)

| Version | What changed | TP | FN | TN | FP | TPR [95% CI] | TNR [95% CI] |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| **v0** (frozen) | First draft: definition, 3 training examples | 7 | 7 | 26 | 0 | **0.50** [0.27, 0.73] | **1.00** [0.87, 1.00] |
| v1 | More rules: outcome explanations, refusals, short-answer rule; 2 more examples | 4 | 10 | 26 | 0 | 0.29 [0.12, 0.55] | 1.00 [0.87, 1.00] |
| v2 | Same rules, restructured: allowed categories first, sentence-by-sentence tagging | 6 | 8 | 24 | 2 | 0.43 [0.21, 0.67] | 0.92 [0.76, 0.98] |
| v3 | Fresh, short prompt written without the earlier versions | 5 | 9 | 26 | 0 | 0.36 [0.16, 0.61] | 1.00 [0.87, 1.00] |
| v4 | v3 plus an exception for out-of-scope refusals | 5 | 9 | 25 | 1 | 0.36 [0.16, 0.61] | 0.96 [0.81, 0.99] |

v1 and v2 were the two revisions the handout allows; v3 and v4 go beyond that limit. Each version fixed some errors and caused others, and every dev interval overlaps.

As scored when each version ran (dev labels changed after the v0 and v1 reviews): v0 0.33 / 1.00 (21 Pass, 19 Fail), v1 0.25 / 1.00 (16 Pass, 24 Fail), v2 to v4 as above. Sources: `analysis/report/dev-verbose_reply-v0.json` to `dev-verbose_reply-v4.json`; the current-label numbers are recomputed from the saved predictions in `analysis/state/judges/`.

## Held-out test (40 traces, 21 Pass, 19 Fail): frozen v0

| | Human Pass | Human Fail |
| --- | ---: | ---: |
| **Judge Pass** | TP 4 | FP 2 (support-0192, support-0202) |
| **Judge Fail** | FN 17 | TN 17 |

- **TPR 0.19** [0.08, 0.40]: the judge agreed with 4 of my 21 Pass labels.
- **TNR 0.89** [0.69, 0.97]: it caught 17 of my 19 verbose replies.

Source: `analysis/report/test-verbose_reply-v0.json`.

## What these rates mean in practice

**The Fail rate barely depends on the real rate.** With the test rates, the share of replies the judge would flag as verbose is:

| True verbose rate | Judge flags as verbose |
| ---: | ---: |
| 10% | 82% |
| 20% | 83% |
| 30% | 84% |
| 50% | 85% |

A monitor built on this judge would show roughly the same number whether the agent got better or worse. (Flag rate = true rate × TNR + (1 − true rate) × (1 − TPR).)

**It can't be corrected for its errors.** Correcting a measured rate for judge error divides by TPR + TNR − 1. Here that's 0.19 + 0.89 − 1 = **0.08**, so any small measurement error becomes a huge error in the corrected rate.

**The same kind of good reply failed in every version.** Five dev Passes were failed by all of v0 to v4: support-0028, 0115, 0172, 0174, and 0250. Each one declines or escalates, briefly explains why, and says what the user can do next. Neither rule changes (v1, v4), restructuring (v2), nor a fresh prompt (v3) moved them.

**Dev overstated how good the judge is.** v0's dev TPR (0.50) was measured after choosing the best of five versions on the same traces, and after seven dev labels were changed while reviewing the judges' critiques. The held-out test TPR (0.19) is the unbiased number.
