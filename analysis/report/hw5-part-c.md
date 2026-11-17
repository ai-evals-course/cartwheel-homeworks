# HW5 Part C: draft judge prompt

Status: the student approved gpt-4o-mini on 94 development traces. The draft
was registered and the DocETL batch was attempted, but API connection/DNS
failure stopped execution. Zero predictions were saved; metrics and human
disagreement review remain pending. Part C is not complete.

Prompt: `analysis/prompts/unnecessary_response_content-v0.txt`.
Example provenance and input/split hashes:
`analysis/prompts/unnecessary_response_content-v0.examples.json`.

The draft evaluates only the final assistant reply for unnecessary content.
Generic closing invitations, redundant narration/conclusions, irrelevant detail,
and unrelated refund assessments fail. Requested information, specific useful
follow-ups, approval explanations, and required caveats pass. Earlier pre-tool
narration is context. Other defects, including policy grounding, citations,
action status, or escalation compliance, do not determine this mode's verdict.
This operationalizes the selected HW4 style criterion as a candidate refinement
of RESP-5; it does not change the application's prompt or specification.

Three examples were selected exclusively from the saved training split:

| Purpose | Trace ID | Human verdict |
| --- | --- | --- |
| Clear Pass: concise pending-refund explanation | `ffc646cec684a84abf45671c701292d2` | Pass |
| Clear Fail: generic closing after requested listing/price | `016de42625b7b5fe3fea972b92701613` | Fail |
| Borderline: specific store/product follow-up | `383ef4888c490343f389d023b46e5736` | Pass |

The borderline example's policy accuracy is a separate issue. Its Pass label
here concerns unnecessary content only. Excerpts preserve actual messages;
intermediate narration and call IDs are omitted. Critiques were drafted by the
coding agent to explain the saved human labels, not recorded as model outputs.

Training trace `5a3b52da903fbc5651703b933687e2c0` is marked Pass but ends with
"If the customer has any further questions, feel free to ask!" This appears
inconsistent with the generic-closing Fail rule. It is flagged for the student,
not relabeled or used as a prompt example. No other student labels changed.

Offline verification confirmed all three examples belong to training, their
verdicts match the saved human labels, and the existing labels, split, and
fixed input export are unchanged. No development or test examples were selected.

`run_development(mode, prompt_path)` is implemented using the supplied helpers.
It checks the training provenance and fixed input/split hashes, registers the
prompt once, and reuses the matching judge on resume. Development metrics are
saved only after complete predictions, with confusion counts, TPR/TNR, 95%
Wilson intervals, class counts, and disagreement IDs. No minimum scores are
required. The test split is not evaluated.

Judge ID: `unnecessary_response_content-v0`. The observed failed attempt is
recorded in `dev-attempt-unnecessary_response_content-v0.json`. There is no
`dev-unnecessary_response_content-v0.json` yet because metrics do not exist.
Five offline preparation/lifecycle tests passed. The live DocETL attempt failed
with an API connection error; the log contains a DNS resolution failure.

Resume after connectivity is restored (existing student approval remains valid):

```bash
uv run python -m analysis.run_judges dev \
  --mode unnecessary_response_content \
  --prompt-path analysis/prompts/unnecessary_response_content-v0.txt \
  --approve-dev-batch
```

Inspect every development disagreement with the student after the run succeeds.
Leave labels and final prompt selection to the student. Make at most two prompt
revisions. Do not freeze or test during Part C.

## Resumed development completed

The student ran the approved command and confirmed completion. Saved artifacts
contain all 94 development predictions and 94 critiques for
`unnecessary_response_content-v0`. The metrics file is now
`dev-unnecessary_response_content-v0.json`.

Observed confusion counts: TP=16, FN=10, TN=47, FP=21. TPR=0.6154 with a 95%
Wilson interval [0.4253, 0.7757]; TNR=0.6912 with [0.5736, 0.7883]. There are
31 disagreements (21 false Pass, 10 false Fail). Counts were independently
recomputed offline from saved predictions and human labels. The full review
packet is `dev-review-unnecessary_response_content-v0.md`.

The earlier connection-failure record is retained as attempt history. Human
review of every disagreement is pending. No labels or prompt text changed;
the judge remains draft and contains no test predictions. Part C remains in
progress until the student reviews disagreements and chooses whether to revise.
