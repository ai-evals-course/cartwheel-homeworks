# Homework 5, build and evaluate an LLM judge

In Homework 5, you build an LLM judge to detect one failure mode from Homework 4. You compare its Pass and Fail decisions with your human labels, use the disagreements to improve the prompt, and test the final judge on held out traces.

Submit your judge prompt, labels, and evaluation results. In a **video of up to 5 minutes**, explain one development disagreement and whether you would use the judge.

## Work with a coding agent

Paste the following prompt once. Continue in the same conversation for Parts A through E.

> Guide me through Homework 5 in `homework/module-2/hw5.md`, one part at a time. Read `AGENTS.md`, the handout, and `SPEC.md`. Use `write-judge-prompt` and `validate-evaluator`. Help me install them if needed. First help me choose a failure mode and check its boundary. Reuse my Homework 4 interface and labels. Use `validate-evaluator` to split the labels before choosing prompt examples. Use `write-judge-prompt` for the draft, with training examples only. Return to `validate-evaluator` for development review and the final test. Explain each step before we start. Compute TPR, TNR, and confidence intervals. Do not require minimum scores. Follow the handout if the skills differ on label counts or evaluation requirements. Use the Cartwheel helpers for DocETL batches and statistics. Save my prompts, labels, and evaluation results as we go. Leave labels and final decisions to me. Before a paid batch, show me the model and trace count. Wait for my approval. Do not show me test predictions before I freeze the judge. Leave the video to me.

## Preparation

Homework 5 uses the failure modes and labels from Homework 4. If you did not complete Homework 4, apply the reference bundle:

```bash
git lfs pull
git apply homework/module-2/hw4-reference.patch
```

The bundle provides one reviewed failure mode, 100 labels, and a review summary. If you completed Homework 4, keep your own work and do not apply the patch.

## Skills

Install the two skills from the course repository:

```bash
npx skills add https://github.com/ai-evals-course/evals-skills --skill write-judge-prompt
npx skills add https://github.com/ai-evals-course/evals-skills --skill validate-evaluator
```

| Skill | What you use it for |
| --- | --- |
| [write-judge-prompt](https://github.com/ai-evals-course/evals-skills/tree/main/skills/write-judge-prompt) | Define the judge's task, Pass and Fail rules, examples, and output format. |
| [validate-evaluator](https://github.com/ai-evals-course/evals-skills/tree/main/skills/validate-evaluator) | Split your labels, inspect development disagreements, and evaluate the final judge. |

### DocETL

You use DocETL, a Python library, to run the same judge prompt across a batch of traces. You receive a critique and a Pass/Fail verdict for each trace. With the Cartwheel helper functions, you also save predictions and calculate metrics.

Use the provided Cartwheel helpers to call DocETL.

Run commands from the Cartwheel repository root. Install Python dependencies, including DocETL, with `uv sync`.

## Part A, choose one failure mode

Choose a failure mode from Homework 4 that is suitable for an LLM judge. For example, you could judge whether the final reply has enough information for the user's next decision, without unnecessary detail.

### Failure definition

Decide exactly what you will label as a failure. State your question, Pass and Fail rules, and the evidence you need.

Refer to [SPEC.md](../../SPEC.md) for the intended Cartwheel behavior.

### Label collection

Label each trace **Pass** (failure absent) or **Fail** (failure present). A trace can be Pass for your selected mode even if it has a different failure.

You need at least **30 Pass and 30 Fail labels** from independent conversations. With 30 of each, you get 6 of each in training, 12 in development, and 12 in test. We recommend labeling closer to 100 traces total, because the extra labels make your development and test splits large enough to produce tighter confidence intervals.

Reuse your Homework 4 interface and labels. Use your coding agent to search for traces similar to your confirmed failures, and review each candidate yourself. If you need more cases, generate targeted scenarios and run them through Cartwheel.

To find more candidates, use:

```python
from analysis.helpers import next_to_label

candidates = next_to_label(
    mode="your_mode_id",
    k=20,
    strategy="enrich",
    trace_source="traces/support_traces.json",
)
```

Use your actual export path. Use `strategy="random"` to sample without searching for failures. Label each candidate yourself.

Save your labels and evidence through your review interface. Use **1 for Pass and 0 for Fail** in HW5. Export your HW5 labels to `analysis/state/hw5_labels/<mode>.jsonl` with that convention. Keep your original Homework 4 labels.

### Stop early

If you can't find enough Pass or Fail cases, explain why you stopped. Show your labels and any judge work you completed in your video.

## Part B, prepare inputs and split your labels

Create `analysis/run_judges.py`. Write a `prepare_inputs()` function to read your HW4 traces and save them to `analysis/state/hw5_trace_inputs.json`. Include one record per labeled conversation with:

- The original trace ID.
- The user request and assistant reply you want to evaluate.
- Earlier turns needed to understand the reply.
- The tool calls, tool results, and policy passages you used to decide Pass or Fail.

Use a JSON list. In each record, use `trace_id` for the identifier and `trace` for the list of messages. Keep each message's `role` and its text or tool data. You will use the same saved inputs for every prompt version.

For example, to judge a refund completion claim, include the refund tool result and final reply. You need both to distinguish a completed refund from a pending approval.

Use one evaluation record per conversation. Keep one record from each group of duplicate runs or close scenario variants.

**Keep your human labels, failure annotations, and extra metadata out of the judge input.** Including review notes or scenario metadata in the trace leaks the answer to the judge.

Check that you have one input record for every eligible label.

Set the export path:

```bash
export CARTWHEEL_JUDGE_TRACE_SOURCE="$PWD/analysis/state/hw5_trace_inputs.json"
```

With that setting, you use the saved export even when you have Langfuse configured. Keep the export unchanged after your first prompt run. You can resume from the same inputs without fetching traces again.

Use `validate-evaluator` for the split. In `analysis/run_judges.py`, write a `split_data(mode)` function using `split_labels`. Use 20% training, 40% development, and 40% test. Run it once and check the class counts before choosing prompt examples.

<details>
<summary>Helper calls for your coding agent to split your labels</summary>

Use the following helper call inside `split_data(mode)`. Replace `your_mode_id` with your selected failure mode:

```python
import json
from pathlib import Path
from analysis.helpers import split_labels

records = json.loads(Path("analysis/state/hw5_trace_inputs.json").read_text())
splits = split_labels(
    "your_mode_id",
    fractions=(0.20, 0.40, 0.40),
    seed=7,
    min_per_class=10,
    eligible_trace_ids=[record["trace_id"] for record in records],
)
```

</details>

With the minimum of 30 Pass and 30 Fail labels, you would have:

| Set | Pass | Fail | How you use it |
| --- | ---: | ---: | --- |
| Training | 6 | 6 | Choose examples for your prompt. |
| Development | 12 | 12 | Inspect disagreements and revise. |
| Test | 12 | 12 | Evaluate your final prompt after freezing. |

Report your actual counts. Keep `analysis/state/splits.json` unchanged during development.

Do not use development or test examples in your prompt. Do not inspect test predictions while choosing the final prompt.

## Part C, write and refine your judge

Use `write-judge-prompt` to draft a prompt from your failure definition and training examples. The prompt should include your Pass and Fail rules, a clear Pass, a clear Fail, and a borderline example from training, and an output format that produces a critique with specific trace evidence followed by a verdict.

Save the draft in `analysis/prompts/<mode>-v0.txt`. Review the boundary with neighboring issues before running it. Tell the judge to evaluate the trace without following instructions quoted inside it.

Run the prompt on development traces through DocETL and use `validate-evaluator` to compare the verdicts with your labels.

### Confusion matrix

**Pass is the positive class (1), Fail is the negative class (0).**

| | Human Pass | Human Fail |
| --- | --- | --- |
| Judge Pass | TP | FP (missed failure) |
| Judge Fail | FN | TN |

- **TPR** = `TP / (TP + FN)`, the rate at which the judge agrees with human Pass labels.
- **TNR** = `TN / (TN + FP)`, the rate at which the judge agrees with human Fail labels.

Overall agreement is misleading when failures are rare, because a judge that always says Pass would have high agreement but zero TNR.

### Compute TPR, TNR, and confidence intervals

Compute TPR and TNR from your confusion counts, and calculate a 95% Wilson confidence interval for each rate. For example, if you correctly detect 16 of 20 human Fail cases, TNR is 0.80 with an interval of about 0.58 to 0.92. With 20 Fail cases, you still have substantial uncertainty about the judge's detection rate.

### Run development batches

Use `gpt-4o-mini` as your judge model. Set your OpenAI API key locally. Use the same model for development and the final test.

In `analysis/run_judges.py`, write `run_development(mode, prompt_path)`. Register the prompt, run it on development traces, and calculate metrics with the helpers below. Save the judge ID and metrics for each version.

<details>
<summary>Helper calls for your coding agent to run your judge on development traces</summary>

Use the following helper calls inside `run_development(mode, prompt_path)`. Replace the mode ID and prompt path with your own.

```python
from pathlib import Path
from analysis.helpers import register_judge, run_judge, judge_alignment

record = register_judge(
    mode="your_mode_id",
    prompt_text=Path("analysis/prompts/your_mode_id-v0.txt").read_text(),
    judge_model="gpt-4o-mini",
)
judge_id = record["judge_id"]  # Save this id for later commands.
run_judge(judge_id, split="dev", batch_size=10)
development = judge_alignment(judge_id, split="dev")
```

</details>

Save the metrics to `analysis/report/dev-<judge_id>.json`. Keep your judge records under `analysis/state/judges/`. You have the cached predictions and critiques there.

In your HW4 review interface, display the judge verdict and critique beside your human label. Filter for disagreements and inspect every one before editing the prompt. For each disagreement, decide whether the judge is wrong (fix the prompt), your label is wrong (fix the label and recalculate), or the definition is unclear (clarify the boundary and recheck affected labels).

Register each revised prompt as a new version. Make at most two revisions. Explain why you stopped revising.

## Part D, freeze and test

Choose your final prompt based on development results and freeze it. Use `validate-evaluator` for the held out test.

In `analysis/run_judges.py`, write `run_test(judge_id)` to freeze the prompt, evaluate test traces, and save the metrics.

<details>
<summary>Helper calls for your coding agent to freeze your judge and evaluate test traces</summary>

Use the following helper calls inside `run_test(judge_id)`:

```python
from analysis.helpers import freeze_judge, run_judge, judge_alignment

freeze_judge(judge_id)  # Do this once for your selected version.
run_judge(judge_id, split="test", batch_size=10)
test = judge_alignment(judge_id, split="test")
```

</details>

Save the metrics to `analysis/report/test-<judge_id>.json`. Report the confusion counts, TPR, TNR, intervals, and class counts. Explain whether you would use the judge based on the rates and uncertainty.

### Resume after an interruption

If the process is interrupted, rerun `run_judge` and `judge_alignment` with the same judge ID. Don't call `register_judge`, `split_labels`, or `freeze_judge` again. Completed batches are cached, so you only pay for the missing predictions.

## Part E, commit your work and record the video

Commit the files you created:

| Artifact | Location |
| --- | --- |
| HW5 labels and evidence | `analysis/state/hw5_labels/<mode>.jsonl` |
| Split assignment and exact inputs | `analysis/state/splits.json`, `analysis/state/hw5_trace_inputs.json` |
| Every evaluated prompt | `analysis/prompts/` |
| Judge versions, predictions, and critiques | Your mode's files in `analysis/state/judges/` |
| Your code for exports, judge runs, and metrics | `analysis/run_judges.py` |
| Development and test metrics | `analysis/report/dev-<judge_id>.json`, `analysis/report/test-<judge_id>.json` |

Keep your Homework 4 files too.

Record your screen for up to 5 minutes in one continuous take. Walk through your failure mode, one development disagreement and how you responded, and your test TPR, TNR, and confidence intervals. Explain whether you would use the judge. Recalculate test metrics from saved predictions live on camera.

## Optional extensions

**Build two more judges.** Use the same skills for two other modes. Reuse your code and interface, and keep separate labels for each mode.

**Estimate failure prevalence.** Sample new traces randomly from the same source, run your judge on them, and calculate the Fail rate. Use `validate-evaluator` to adjust the rate for judge errors using your test TPR and TNR.

## References

- [Cartwheel specification](../../SPEC.md)
- [write-judge-prompt](https://github.com/ai-evals-course/evals-skills/tree/main/skills/write-judge-prompt)
- [validate-evaluator](https://github.com/ai-evals-course/evals-skills/tree/main/skills/validate-evaluator)
- [Helper functions](../../analysis/helpers/)
- [Course reader](https://docsend.com/v/rcdy7/evals-course-reader), Module 2 sections on LLM judges and held out validation.
