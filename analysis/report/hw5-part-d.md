# HW5 Part D: test runner prepared; final evaluation pending

`run_test(judge_id, approved=False)` is implemented in `analysis/run_judges.py`.
It requires the student's chosen final judge and approval for the paid batch.
It checks that the selected version has completed development predictions and
saved development metrics, then validates the fixed inputs and disjoint split.
There is no numerical acceptance threshold. The student still decides how to
resolve disagreements and whether to use the judge.

The function freezes a draft judge once, runs the supplied `run_judge` helper
on test with batch size 10, and calls `judge_alignment` for confusion counts,
TPR, TNR and 95% Wilson confidence intervals. It adds human class counts and
writes `analysis/report/test-<judge_id>.json`. On interruption, use the same
judge ID: cached predictions are reused, with no re-registration, re-splitting
or repeated freeze.

The future CLI invocation after student selection and approval is:

```bash
uv run python -m analysis.run_judges test \
  --judge-id <student-selected-judge-id> --approve-test-batch
```

Current status:

- No development run or disagreement review has occurred for this mode.
- Draft judge `unnecessary_response_content-v0` is registered; no final judge
  has been selected. The development attempt failed before saving predictions.
- No paid test approval has been given.
- No judge has been frozen and no test predictions have been generated.
- The test split contains 93 conversations: 25 human Pass and 68 human Fail.
- The planned judge model remains `gpt-4o-mini` for development and test.
- TPR, TNR, intervals, and the student's use decision are pending real results.

Observed verification: four offline preparation/lifecycle tests passed using
synthetic fixtures isolated in temporary state. The lifecycle tests verify
that approval and development are required before freezing or making calls,
that the judge is frozen before test classification, that repeat execution
reuses cached predictions, and that the real statistics helper saves metrics.
These synthetic metrics are not homework evaluation results.

Next step: resume the already-approved Part C batch on 94 development traces
using `gpt-4o-mini` when connectivity is restored, review disagreements, and
let the student choose a final version.
Then obtain test-batch approval, run Part D, and leave the use decision and
recording to the student.
