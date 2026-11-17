# HW5 Part B: unnecessary response content

The student selected `unnecessary_response_content` and confirmed the saved
HW4 labels. The HW5 export uses 1 = Pass and 0 = Fail. The original HW4
files and all 301 confirmed HW5 labels are preserved.

## Inputs and eligibility

`analysis/run_judges.py` defines `prepare_inputs()` and `split_data()`.
The input source is the saved `traces/support_traces.json` export. The final
generation's input provides the conversation history actually seen by the
agent, including prior user requests, assistant replies, tool calls, tool
results, and policy evidence. Its output supplies the reply being judged.
Only conversation text and tool data are retained. System instructions,
review notes, labels, scores, and scenario metadata are excluded.

Of 301 labeled traces, 294 have evidence in the local export. Seven missing
traces are excluded. Related runs are grouped by shared scenario/session ID
or matching user histories after normalizing case, whitespace, and numeric
identifiers. The latest labeled record per connected group is retained,
without using its class to select it. Sixty related runs are excluded,
leaving 234 evaluation records: 64 Pass and 170 Fail.

The exact exclusions, selection rule, and source/input SHA-256 hashes are in
`hw5-preparation-unnecessary_response_content.json`. Paraphrases with different
wording and no shared scenario/session ID are not automatically identified.

## Fixed split

The supplied `analysis.helpers.split_labels` created a stratified split with
fractions `(0.20, 0.40, 0.40)`, seed 7, and `min_per_class=10`.
The existing demo mode in `analysis/state/splits.json` was preserved.

| Split | Pass | Fail | Total |
| --- | ---: | ---: | ---: |
| Training | 13 | 34 | 47 |
| Development | 26 | 68 | 94 |
| Test | 25 | 68 | 93 |

Every eligible record appears exactly once. Reruns reuse the saved split;
changed input records cannot silently overwrite the saved inputs. Do not
regenerate the split during prompt development.

To resume preparation from the repository root:

```bash
uv run python -m analysis.run_judges prepare
export CARTWHEEL_JUDGE_TRACE_SOURCE="$PWD/analysis/state/hw5_trace_inputs.json"
```

## Observed verification and next step

Offline preparation and helper regression checks: 8 passed, 2 skipped,
32 deselected. A temporary mutation disabling input-preservation protection
caused the expected test failure; the original code was restored. The saved
input file was also loaded through the judge's actual trace-source loader.
No live model calls, judge predictions, prompt-example selection, or test
prediction inspection occurred. Part C (drafting the prompt from training
examples) is next. Metrics remain pending until actual judge runs.
