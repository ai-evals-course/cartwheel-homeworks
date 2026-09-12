# Homework 4, human trace review and failure taxonomy

Homework 4 asks you to read Cartwheel traces, find the failures, and organize the failures into 5 to 8 named categories. You review at least 100 traces, describe each failure in your own words, then group similar failures together.

## Working through the assignment with a coding agent

If you would like a coding agent to walk you through the assignment, paste the prompt below at the start of a session in your repository. The agent builds the review interface with the error-analysis skill; the handout's review points are where you decide.

> Walk me through Homework 4 in `homework/module-2/hw4.md`. Read `AGENTS.md`, the handout, `SPEC.md`, and `analysis/skill/SKILL.md` first. Work one step at a time in the handout's order. Wait for my go before running commands or changing files. Explain error analysis concepts (open coding, axial coding, failure modes) in depth; treat infrastructure as a checklist. Leave the video to me.

## Expected work

- Estimated time: 6 to 8 hours.
- Review at least 100 traces and annotate failures.
- Build a review interface with a coding agent (under `analysis/review_app/`).
- Define 5 to 8 binary failure modes with definitions, examples, and boundaries.
- Apply every final mode to every reviewed trace (present or absent).
- Document one taxonomy revision and one rejected search suggestion.
- Record a video of no more than 5 minutes.

The starter repository provides trace loading and storage functions under `analysis/helpers/`. The reference interface (`analysis/server.py` and `analysis/ui/index.html`) is for comparison, not submission. Your annotations and taxonomy go in `analysis/state/`. Written notes go in `analysis/report/`.


### How the three tools fit together

This assignment uses three tools. Langfuse holds the Cartwheel traces from Module 1 and remains the canonical store for annotations. You will build your own *review interface* for the open coding workflow, because the standard Langfuse annotation view separates tool calls from replies and does not group multi-turn conversations. After open coding, Raindrop Workshop gives your coding agent execution-level access to raw model activity and tool calls, so you can discover failure modes your initial review may have missed.

During trace review, consult `SPEC.md` before deciding whether an observed behavior violates an existing requirement. For example, a reply claiming a refund succeeded before the tool reports success violates `RESP-2`. Record the relevant requirement identifier in every failure mode derived from an existing requirement.

Your error analysis may reveal a desirable behavior not yet required by `SPEC.md`. In such a case, record the missing or ambiguous requirement before assigning a failure label. Decide what the agent should do, then revise `SPEC.md`. Do not build an evaluator until the requirement is precise enough for another reviewer to apply.

## Prepare Langfuse and the analysis state files

You will review live traces in Langfuse and commit a local copy of your analysis state. Langfuse is the default trace and annotation store because the Module 1 application already recorded complete traces there. Each Langfuse score remains associated with a stable trace identifier. The Module 2 loader selects records carrying Module 1 scenario identifiers rather than relying on a temporary demonstration tag. Files under `cartwheel/analysis/state/` provide a committed copy for grading and reproduction. The local files also support an offline demonstration, but they do not replace Langfuse during the normal assignment.

Confirm your Langfuse project contains the Cartwheel support traces from Module 1. Then read:

- `cartwheel/analysis/skill/SKILL.md`.
- `cartwheel/SPEC.md`.
- `cartwheel/analysis/server.py`.
- `cartwheel/analysis/ui/index.html`, which is a supplied reference rather than the required submission.

Use the Module 1 trace export as an offline source only when the live Langfuse project is temporarily unavailable. Record the reason in the interface comparison. Preserve the stable trace identifiers so you can synchronize the saved judgments later.

## Part A, build a review interface with an AI coding agent

You will review 5 to 10 traces in the standard Langfuse annotation view, then use the observations to plan your own interface. Record any feature of the standard view that makes review slower or less reliable. For example, a tool result may appear far from the reply describing it.

Next, ask your AI coding agent to read the error analysis skill and the Workshop notes. Require the coding agent to compare the preliminary Workshop runs with several Langfuse traces, then propose a visual organization before writing code. You may begin with the following prompt:

> Read `analysis/skill/SKILL.md` and `analysis/report/workshop_notes.md`. Use Workshop to inspect the preliminary runs, then inspect 5 to 10 traces from my Langfuse project. Describe the trace fields and the visual organization you propose for human review. Do not write the interface until I approve the proposal. Use `analysis/ui/index.html` and `analysis/server.py` as implementation references, but adapt the interface to the trace structure you observe.

After you approve the proposal, ask the coding agent to build the interface under `analysis/review_app/`. Cartwheel creates one Langfuse trace per user turn, so a multi-turn conversation produces several traces. The interface must group traces by `cartwheel.session_id` and display each conversation in chronological order, otherwise a followup turn appears in isolation and the reviewer cannot see the tool calls from the earlier turn. The interface must provide:

- The complete conversation, retrieval results, tool calls, and tool results, grouped by session.
- Free form annotations entered beside the relevant trace content.
- A view of the current taxonomy and its supporting annotations.
- A structured labeling view with one present or absent decision per trace and final mode.
- A progress view showing reviewed traces and incomplete judgments.
- AI suggestions displayed separately from human annotations, with controls for explicit acceptance or rejection.
- Saving accepted binary judgments as Langfuse scores and matching local files under `analysis/state/`.

You may reuse the server API or individual components from the reference interface, but you may not submit the reference interface unchanged. Commit your interface code. Also commit a short `analysis/report/interface_comparison.md` with the following contents:

- One design you retained from the reference interface.
- One design you changed after inspecting your traces.
- One limitation remaining in your interface.

## Part B, review at least 100 traces

You will review at least 100 distinct traces and use several selection methods to cover different parts of the trace collection. Use the following four batches:

- Begin with 15 uniformly sampled traces and 15 cluster representatives.
- Choose one product dimension before looking at the outcomes, e.g., user role, then add 30 traces distributed across its values.
- Add 25 traces retrieved during depth searches for candidate modes and close negative examples.
- After drafting the taxonomy, review 15 additional uniformly sampled traces to check whether new modes continue to appear.

Use all four batches, and do not count one trace toward more than one batch. Your final review set must contain at least 100 distinct traces. Do not select traces only because a model or heuristic predicts a failure.


Recall from lecture and the section “Open and axial coding” in the [Module 2 reader](../../../reader/main.pdf): taxonomy construction begins with open coding. During open coding, read the conversation together with its retrieval and tool activity until you identify the first failure. The first failure is the earliest step to violate the product requirements or make a later failure materially more likely. Write a free form note describing the failure, then stop the initial review of the trace. The stopping rule keeps long traces manageable, while the later structured labeling pass can record additional modes. Do not assign a formal failure mode during the initial reading. If you find no failure, record “no failure observed” so the saved annotations distinguish a reviewed trace from an unreviewed trace.

For example, suppose the refund tool returns `queued_for_approval`, while the final reply claims the refund is complete. An appropriate open code is “the reply reports a completed refund even though the tool only queued it for approval.” A category such as `tool_problem` would omit the evidence needed to define the failure precisely.

### Worked example, from open code to structured label

The following example shows all three stages for one observation.

**Open coding.** You review a trace in which the agent tells a shopper “your refund of $47.50 has been processed,” but the `issue_refund` tool returned `{“status”: “queued_for_approval”, “approver”: “merchant”}`. Your open code is: “the reply reports a completed refund even though the tool only queued it for approval.”

**Axial coding.** After reviewing more traces, you find two similar open codes: “the reply says the order was cancelled, but the cancel tool returned an error” and “the reply confirms a price match, but the tool returned pending.” All three observations describe the same pattern: the reply asserts an action succeeded before the tool confirms success. You group them under a candidate mode called `unconfirmed_write` with the binary definition “the agent's reply states that a write operation succeeded, but the most recent tool result for that operation does not confirm success.” A trace where the tool returns `{“status”: “refunded”}` and the reply says “your refund has been processed” is a close negative, because the tool did confirm success.

**Structured labeling.** Once the taxonomy stabilizes, you return to the original trace and record `unconfirmed_write: Fail` (failure present) with the tool result as evidence. You also label the close negative trace `unconfirmed_write: Pass` (failure absent). Every trace in the review set receives one judgment per final mode.

After each review batch, begin axial coding by comparing the open codes and grouping observations under a possible shared binary decision rule. Revisit an earlier trace when a proposed group changes how you interpret its evidence. Keep the original open code in the saved history, because the sequence from observation to category must remain inspectable.

## Part C, inspect runs with Raindrop Workshop

After open coding, use Raindrop Workshop to inspect 5 to 10 fresh or replayed Cartwheel runs. Workshop is a local trace debugger whose coding agent integration can inspect model activity and tool calls. The goal is to discover failure modes your open coding may have missed.

Follow the current installation instructions in the Workshop repository, then ask your coding agent to run `/instrument-agent`. Preserve the existing OpenTelemetry and Langfuse instrumentation. A local Workshop installation is sufficient.

Select runs covering several parts of the application (different roles, different tools). Ask the coding agent to inspect the Workshop traces and prepare `analysis/report/workshop_notes.md` containing:

- The Workshop trace or run identifier for every inspected run.
- Candidate failures or unusual behaviors identified by the coding agent.
- One case for which the coding agent reports uncertainty or an alternative explanation.

Treat the Workshop analysis as a source of hypotheses, not labels. For every Workshop suggestion discussed in your final taxonomy, record whether you accepted, revised, or rejected the suggestion.

## Part D, construct and check the taxonomy

You will organize your observations into 5 to 8 binary failure modes, then search for more examples to check each definition. Construct the taxonomy only from observations you wrote or accepted after reviewing the trace. The coding agent may propose a name or a grouping. Before accepting a proposal, inspect every supporting trace and decide whether the proposed definition applies.

A positive trace contains the failure described by a mode. A close negative trace may appear similar, but it does not contain the failure. Close negative traces help another reviewer understand the boundary of a mode.

Each final failure mode must contain:

- A `snake_case` name describing the observed failure.
- A binary definition another reviewer can apply.
- At least three confirmed positive traces.
- At least three close negative traces when the reviewed data permits them.
- The human annotations from which the mode originated.
- A boundary separating the mode from its nearest neighboring mode.
- The likely evaluator type, either a code check or an LLM judge.
- A requirement source, either an identifier in `SPEC.md` or a recorded specification revision.

Use the likely product change to decide whether two observations belong in the same mode. Merge two groups when one product change would correct both behaviors. Split a group when its examples require different product changes, even when the traces use similar words.

After your taxonomy becomes stable, compare it with the AgentDebug taxonomy. Use the published taxonomy to identify a possible omission or an unclear name. Add a mode only when your own traces and human annotations support the addition.

### Search for additional instances

You will use the coding agent to search for additional instances of one confirmed mode. Treat a similarity score, model prediction, or deterministic filter as a retrieval signal rather than a label. Review every returned trace yourself. Record whether you accepted or rejected each suggestion.

Repeat the search after revising the mode definition. Recheck earlier traces when a mode discovered late in the process may apply to them. Your saved state must contain at least one rejected suggestion.

## Part E, apply the final taxonomy


You will apply every final mode to every trace in the review set. A trace may contain more than one mode. Therefore, assign a separate present or absent judgment to every trace and mode pair. Write each accepted judgment to Langfuse as a score. Preserve a matching record under `analysis/state/labels/`.

Report the count and fraction assigned to each mode within your reviewed sample. Refer to the quantities as sample fractions rather than prevalence estimates. Clustering, filtering, and focused searches deliberately change the composition of the reviewed sample. Homework 5 will use the complete Module 1 trace store to estimate prevalence.

Use the final 15 traces to assess whether the taxonomy has become reasonably stable. Record how many of the final 15 traces produced a previously unseen consequential mode. If several new modes appear in the final batch, review another batch before completing the assignment.

## Preparing for Homework 5

Homework 5 requires at least 30 Pass labels and at least 30 Fail labels per mode before you can split and validate an LLM judge. A mode that appears in only 5 of your 100 reviewed traces will need another targeted review round in Homework 5 before you can build a judge for the mode. When you report your counts, check whether each subjective mode you plan to evaluate with an LLM judge has enough Fail examples. If a mode has fewer than 15 Fail labels after this assignment, plan to collect more labels early in Homework 5.

## Files to commit

Commit:

- Your review interface code.
- `analysis/state/sample_manifest.json`.
- `analysis/state/annotations.json`.
- `analysis/state/patterns.json`.
- `analysis/state/suggestions.json`.
- One label file per final mode under `analysis/state/labels/`.
- `analysis/report/review_summary.md`.
- `analysis/report/workshop_notes.md`.
- `analysis/report/interface_comparison.md`.
- Any revision to `SPEC.md`, with the motivating annotation identified in the review summary.

Your review summary must report the size and composition of the reviewed sample. It must also report how many new modes appeared in the final 15 traces. Include a short account of one taxonomy revision.

## Video

Submit one continuous screen recording of no more than 5 minutes. Drive your review interface and repository during the recording. Do not use slides.

Explain:

- One interface decision made after inspecting the traces.
- One Workshop suggestion and your decision to accept, revise, or reject it.
- Two failure modes and one supporting trace for each mode.
- One taxonomy revision or rejected group.
- One rejected search suggestion and the boundary excluding it.
- One relationship between a mode and `SPEC.md`.
- The number of new modes found in the final 15 reviewed traces.

Open one trace and its saved Langfuse score during the recording. Regenerate one reviewed sample count from the committed label files. Make sure every numerical claim agrees with the committed artifacts.

## References

- [Error analysis skill](../../../cartwheel/analysis/skill/SKILL.md)
- [Raindrop Workshop](https://github.com/raindrop-ai/workshop)
- [Langfuse annotation queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues)
- [AgentDebug failure taxonomy](https://arxiv.org/abs/2509.25370)
