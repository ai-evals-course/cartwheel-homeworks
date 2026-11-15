# Part D: provisional grouping of human observations

Status: coding-agent proposal for student review. No modes are final and no
binary labels have been assigned. Source: the 56 human notes on 48 distinct
traces in `analysis/state/review_app.json` at the start of Part D. The state
also records 120 reviewed traces; that count alone does not establish that
every homework sampling requirement has been met.

The proposed groups below are drawn from those notes. Example scenarios are
navigation aids, not confirmed positive labels. Scenario IDs recur across
runs: use the exact trace and annotation IDs in the evidence table below.

## Proposed groups and boundaries

| Proposed name | Provisional binary definition: present when… | Boundary / next check | Requirement / evaluator |
| --- | --- | --- | --- |
| `unsupported_policy_answer` | The agent gives a substantive Cartwheel policy answer that contradicts policy or lacks supporting policy evidence anywhere in the available conversation. | Earlier-turn retrieval can support a later reply; absence of a new lookup alone is insufficient. Separate a grounded answer missing only a citation. | `PURPOSE-1`, `SCOPE-1`, `RESP-1`; LLM judge with policy and tool context. |
| `unnecessary_response_content` | The final reply includes a generic offer of further help, redundant narration, or an unrelated refund assessment that adds no information needed for the user's request. | This reflects repeated human notes, but the prohibited content and exceptions need student agreement. Helpful next steps, required caveats, and pre-tool narration should not automatically count. | Candidate refinement of `RESP-5`; explicit requirement revision needed before finalizing. LLM judge. |
| `avoidable_clarification` | The agent asks the user for information already supplied or unambiguously established by the conversation and tools, delaying an otherwise executable task. | An order total does not necessarily establish the requested refund amount. Clarification is appropriate when the user has not specified a full refund or another amount. | `SCOPE-1` supports task completion but does not define this efficiency rule precisely; student specification decision needed. LLM judge. |
| `omitted_requested_action` | The user clearly authorizes an available action, its prerequisites are established, and the agent ends the turn without attempting it or explaining a valid reason it cannot proceed. | Exclude genuine missing information, permission denial, kill switches, pending approval, and already completed actions. Keep required human escalation in its own group because its fix differs. | `PURPOSE-1`, `SCOPE-1`, applicable `TOOL-7`/`TOOL-8`; task-completion boundary needs review. LLM judge plus tool checks. |
| `missing_human_escalation` | A request requires human handling under `ESC-1`–`ESC-4`, but no appropriate escalation or approval-queue action occurs before the turn ends. | An offer to open a ticket is not a tool execution. A successful above-threshold approval queue satisfies `ESC-1` without a second ticket. | `ESC-1`–`ESC-4`; LLM judge for trigger plus code checks for actions/results. |
| `misstated_action_status` | The agent describes a write as completed when the observed tool result supports only pending approval, failure, or no executed write. | “I can initiate” is an offer, not a completion claim. “Successfully initiated” followed by an explicit pending-approval explanation is a disputed boundary, not an automatic positive. | `RESP-2`, `TOOL-7`, `ESC-1`; LLM judge with tool results. |
| `incorrect_tool_arguments` | The agent supplies a tool argument inconsistent with its documented meaning, producing an avoidable error or materially changing the requested scope. | An ID passed where a store name/slug is expected is a candidate. A recovered read error does not necessarily violate a current product requirement; no cross-store error should be inferred if results match the requested store. | Relevant tool contract (`TOOL-3` and `agent/tools.py`); recovered-error acceptance rule needs student agreement. Code checks where deterministic, otherwise LLM judge. |

These are seven candidate groups, not seven established final modes. Merge,
revise, or drop a group if human review does not support a distinct corrective
change. Do not split groups merely to meet the required count of 5–8.

## Starting evidence from the student's notes

| Group | Scenario | Exact trace ID | Human annotation ID |
| --- | --- | --- | --- |
| unsupported_policy_answer | support-0112 | `3e02d9597f54c2a052bda149f882cecb` | `19ffd077-01ac-4ad1-a771-c0ae0568057b` |
| unsupported_policy_answer | support-0102 | `8920d8223801c80982e5be23cc88e651` | `fe93d863-62f4-4a32-89e3-dbf65f683a86` |
| unsupported_policy_answer | support-0119 | `63118e9dda7e8c1f6b67ae84dc958354` | `3031c69b-f858-47f5-a394-75514d1151d8` |
| unsupported_policy_answer | support-0124 | `383ef4888c490343f389d023b46e5736` | `8073c836-cca9-4b39-aa1c-85a7ba6f1ef7` |
| unnecessary_response_content | pilot-0001 | `a89ead3274f5c7ba346f20f604c88c0d` | `d99ea638-e663-4f3d-afdc-210deedf2a8f`, `22568a3c-3480-45fe-8df5-df7ecf5c7989` |
| unnecessary_response_content | support-0018 | `e28cb30aefd6d9ab2febf73572f98d12` | `e08d0945-f1a6-434b-8b5b-824e4ffe241e` |
| unnecessary_response_content | support-0114 | `781e5b8b700e87ff2d1366ea9ffa501a` | `07d95c9c-628d-4db1-9d7e-01fb010b8fba` |
| avoidable_clarification | support-0212 | `9dcc98eee60aac9bf4147f7c326be06a` | `6a603a6d-8e73-422b-a382-a8f10e722133` |
| avoidable_clarification | support-0074 | `c45a49546acc59f50d4315a70747a9f8` | `817f2edb-07f1-48f4-a2a1-2d727efe52c8` |
| omitted_requested_action | support-0066 | `9bd873f786d40e73d25193009ea7f9b5` | `c8f31b07-c1ec-470c-9a86-2e8259c451b7` |
| omitted_requested_action | support-0069 | `49804473d4b34079a6929db47921de66` | `f5b729da-ff9c-44ce-b31b-6646a04d07c7` |
| omitted_requested_action | support-0074 | `c45a49546acc59f50d4315a70747a9f8` | `3312ab5b-1788-4135-bcc5-97fbdefd1fae` |
| missing_human_escalation | support-0153 | `f820bda867728400d62e82f64919334c` | `67adc506-7489-4421-a093-d27d9f877abb` |
| misstated_action_status | support-0047 | `358f44276b9109622faa83b93d4fa303` | `ea01946e-ee2d-402e-9d01-2293ed041957` |
| misstated_action_status | support-0039 | `5caaf6834e4bdb51c607fa81a15f39d2` | `d6c1db68-526c-4206-82c5-685cdf358026` |
| incorrect_tool_arguments | support-0128 | `d7cc90af945e09973feefd9db9260be9` | `a2fd55fb-793a-4497-adfb-be62d6d366c7` |

Some human notes may change interpretation after examining the entire trace.
The original notes remain authoritative history and should not be overwritten.
The Part C runs of support-0153 and support-0128 have different trace IDs from
the two annotated runs above; do not substitute one run's evidence for another.

## Observations needing a requirement or interpretation decision

- Policy hyperlinks: notes on support-0101, support-0113, and support-0121 ask
  for links. `RESP-1` currently requires policy identifiers, not clickable links.
  An identifier-only citation should not be called a missing citation. Decide
  whether to add a hyperlink requirement before creating a mode for it.
- Merchant refunds: `AUTH-1` explicitly allows a merchant to request a refund
  for its own store. The note that merchant refunds do not make sense needs
  interpretation against that access matrix.
- Partial refunds: `TOOL-7` accepts an amount; the function contract allows
  positive amounts up to the order total. The absence of a partial-refund
  paragraph in a policy does not by itself establish a prohibition.
- Public payout facts: the access matrix permits every role to search policies.
  A shopper receiving public payout-policy information is not automatically an
  authorization failure. Any new audience restriction needs an explicit rule.
- Explanations for ineligibility, internal store IDs, and hedging such as
  “It looks like” have human notes but insufficiently precise rules or supporting
  cases for separate final modes at this stage. Preserve them for discussion.

## First review packet: policy answers

Start by checking the four `unsupported_policy_answer` examples in the table.
In each, inspect the user's request, all earlier conversation context, retrieved
policy evidence, and the final reply. Refund timing is 5–10 business days, and
store policy overrides are allowed under the constraints in `facts.yaml`.
The student's existing excerpts suggest conflicting numbers or rules, but
confirmation requires the full trace.

A useful candidate close negative is the Part C support-0102 run
`a98e6e8edc561cb1a6b2d5448d605cc9`: it retrieved `cw-refunds`, reported 5–10
business days, and cited the identifier. It is a different execution from the
annotated support-0102 above. Also check earlier-turn retrieval as a close
negative for any proposed “no tool call” rule.

For each reviewed example record: candidate mode, exact trace ID, present or
absent decision, evidence, and accept/revise/reject for the proposal. Decisions
must come from the student. No confirmed-positive or close-negative quota is
claimed in this draft.

## Remaining Part D work

1. Student reviews these proposed definitions and supporting traces; revise
   ambiguous requirements before treating preferences as failures.
2. Establish 5–8 supported final modes, each with at least three confirmed
   positives, three close negatives where data permits, originating annotations,
   a neighboring-mode boundary, evaluator type, and requirement reference.
3. Search for additional instances of one student-confirmed mode. Returned
   matches remain suggestions until reviewed; record actual accept/reject
   decisions, including at least one genuinely rejected suggestion.
4. Revise that definition based on review and repeat the search. Recheck earlier
   traces when definitions change; document one real taxonomy revision.
5. Once stable, compare with the published AgentDebug taxonomy for omissions
   or naming clarity. Add nothing unsupported by the student's observations.

The final taxonomy, repeated searches, human confirmations, and AgentDebug
comparison are pending. No existing annotations, scores, specification text,
or final taxonomy settings were changed to create this proposal.

## Update: previously unassigned comments, 2026-11-15

See [the unassigned-comment review](unassigned_taxonomy_review.md) for the updated eight-mode proposal, 31 new proposed links, one definition revision, evidence checks, and eight unresolved comments. Current helper definitions and links are in `analysis/state/patterns.json`. The original proposal above remains history; all modes remain provisional.

## Update: complete comment coverage

At review revision 133, all 55 current comments now have a provisional group, including singleton groups. See [complete taxonomy coverage](taxonomy_coverage.md) for the five added groups and their requirement caveats. There are 13 provisional groups; final HW4 mode selection remains pending. Removed human notes were not restored.
