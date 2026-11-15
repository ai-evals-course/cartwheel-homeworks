# Unassigned comment taxonomy review

Status: coding-agent proposals for student review, 2026-11-15. No final modes, human decisions, or binary labels were created. Original comments, completion records, and scores are preserved.

## Coverage and source

Started with 56 human comments and seven provisional groups: 17 comments were already linked and 39 were unassigned. Proposed 31 additional links and one new group; 48 comments now have proposed groups and eight remain unassigned for the reasons below. These are comment counts, not failure counts or sample fractions.

Langfuse access failed with URLError / OS error 1 (Operation not permitted) in this sandbox. The offline check used `traces/support_traces.json`, exported 2026-11-09T11:01:40.615424+00:00, with exact trace IDs and complete available session context. Of the 39 unassigned comments, 32 have exact traces in that export; seven comments on five traces have only their saved human notes and excerpts available. No fresh runs or model calls were made.

Every available comment quote was found in its exact trace. The seven note-only associations remain explicitly unverified against full traces. Scenarios are navigation aids and never substitutes for exact trace IDs.

## Proposed taxonomy after grouping

| Mode | Previously linked comments | Added comments | Total comments | Distinct linked traces |
| --- | ---: | ---: | ---: | ---: |
| `unsupported_policy_answer` | 4 | 3 | 7 | 7 |
| `unnecessary_response_content` | 4 | 24 | 28 | 24 |
| `avoidable_clarification` | 2 | 0 | 2 | 2 |
| `omitted_requested_action` | 3 | 1 | 4 | 4 |
| `missing_human_escalation` | 1 | 0 | 1 | 1 |
| `misstated_action_status` | 2 | 0 | 2 | 2 |
| `incorrect_tool_arguments` | 1 | 1 | 2 | 2 |
| `unexplained_refund_refusal` | 0 | 2 | 2 | 2 |

## Definition checks and revision

- Expanded `omitted_requested_action` to include an available requested read as well as a write. The tray-listing note shows the same omission pattern: an applicable tool exists but is never attempted. A malformed attempted call stays in `incorrect_tool_arguments`.
- Extended `unnecessary_response_content` to account for the actual notes about excessive details and repeated conclusions. Required explanations, citations, order disambiguation, and approval status are excluded. This remains a candidate refinement of RESP-5, not an agreed specification change.
- Added `unexplained_refund_refusal` from two human notes. Its corrective change is to explain a refusal or acknowledge missing reasons. This differs from removing redundant wording. Neither saved get_order result provides a concrete eligibility reason, so the definition must not reward inventing one. Only two originating traces exist; finalization support is insufficient.
- Added the escalation-timeframe note to `unsupported_policy_answer`: the agent provides 24–48-hour advice without retrieval, while facts.yaml defines a 24-hour human response SLA. The two dispute notes also provide advice not supported by the retrieved order record. Their human notes concern policy grounding; no additional escalation labels were inferred.
- The Vintage Water Bottle note describes an attempted search with store="9" and not_found. Grouped with incorrect arguments because the contract requires a store name/slug. The metadata-disclosure note on a different trace remains a separate unresolved preference.
- Hyperlinks, merchant refund permissions, partial refund amounts, public payout facts, hedging, and internal-ID presentation were checked against SPEC.md, facts.yaml, and relevant tool contracts. No specification revision was made.

## Boundaries checked on exact traces

| Candidate boundary check | Exact trace | Observation |
| --- | --- | --- |
| Unnecessary content vs required status | `c71aba104857fd1b36c3bb3828f0d30b` | cancel_order reports cancelled; the completion confirmation is needed, while the human highlights only the generic closing. |
| Unsupported policy vs missing hyperlink | `9ea7ed863fa505f8cf30dc7fe74a885b` | Policy evidence was retrieved and cw-returns is cited. No hyperlink alone does not support this mode. |
| Unsupported policy vs allowed public facts | `bcb3b68215ebb654e69210e89a636fcf` | The payout answer cites retrieved cw-payouts. The human audience restriction is not in AUTH-1. |
| Omitted tool vs malformed attempt | `799e100145cfd1464b7bd85f1f0daeba` | search_products was attempted; the store argument failed. It is not an example of no search call. |
| Redundancy vs missing reason | `786bc2e9746c915caab5803bcc372fcc` | The human notes repeated ineligibility wording. Repeating delivered/not eligible does not prove a concrete refund reason was supplied. The note stays with redundancy. |
| Clarification vs partial-refund prohibition | `ee2da69c5f562a7d719db0c426ab0754` | Order total is known, but an explicit full-refund amount is not. A prohibition on partial refunds cannot be inferred. |

These are agent boundary checks and review candidates, not student-confirmed positives/negatives or accept/reject decisions. No quota of three confirmed positives and three close negatives is claimed for any mode.

## All 39 previously unassigned comments

| Human annotation ID | Exact trace ID | Proposed group / disposition | Evidence check |
| --- | --- | --- | --- |
| `3b906659-f53f-4ec8-806d-f12b3ad3f76a` | `732935f9da2ee47e5ef93571d23adc5a` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `34292f4d-d3e8-4d9c-af10-0bd4213988c1` | `732935f9da2ee47e5ef93571d23adc5a` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `d5c0d768-a9db-40f0-a4e6-2b2a293fb0a8` | `ceede4841b9015ecc621c905d2c11641` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `01da37c5-74fd-4f4c-801e-89f3c91e69af` | `ad8f545e094c06ee7b33d259977e28e4` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `88e87958-c219-46f2-bb2f-6df2ffd8c171` | `d1764466a31934aadadaab02879315ad` | `unnecessary_response_content` | Exact trace and quote checked. |
| `d20954bf-faa5-47b4-a607-dd242e5aa8e5` | `e28cb30aefd6d9ab2febf73572f98d12` | `unnecessary_response_content` | Exact trace and quote checked. |
| `c5c52ea0-5a5c-40df-a1c0-4052b61cf48e` | `0da84caf6abe4aaf5fca0b5048fb8a94` | requirement decision | Exact trace and quote checked. |
| `9bf24b56-7f24-4c67-a8bc-d565750d1dff` | `8b855cc69b2bc6bf6afa0089fd9c0b4f` | `unnecessary_response_content` | Exact trace and quote checked. |
| `29fa7bd4-68e5-4e82-b28e-65986689cccf` | `9ea7ed863fa505f8cf30dc7fe74a885b` | requirement decision | Exact trace and quote checked. |
| `94fe4afd-0198-41c3-82d5-43af9b07474e` | `3b324bc6a578ea899ae9c3eddc4b796f` | `unnecessary_response_content` | Exact trace and quote checked. |
| `b7f0909e-af54-4b2f-8e1b-a394051cec72` | `3b324bc6a578ea899ae9c3eddc4b796f` | requirement decision | Exact trace and quote checked. |
| `23b003ac-f12a-49e1-a014-392c45270a2e` | `42dc321dbe741e3a70b125bd63442a38` | requirement decision | Exact trace and quote checked. |
| `cae5cad9-adc6-46ba-abdd-fa5a2047c5f3` | `42dc321dbe741e3a70b125bd63442a38` | `unnecessary_response_content` | Exact trace and quote checked. |
| `abb03981-fbfd-489a-b000-c11a89e5d41f` | `799e100145cfd1464b7bd85f1f0daeba` | `incorrect_tool_arguments` | Exact trace and quote checked. |
| `f30ee441-da24-4b68-bf66-b4133137805c` | `599c13ea4ab3b8c789cb6cbe210e5bc1` | `unexplained_refund_refusal` | Exact trace and quote checked. |
| `69a0ad13-beb3-481a-accb-264558e56942` | `ca84ff30deac591c33e3124aaa3ae51b` | `unnecessary_response_content` | Exact trace and quote checked. |
| `63aee341-a425-4edf-a664-4af9594fff2c` | `a59ecb25bcb57b6fc01fd21602698bc3` | `unnecessary_response_content` | Exact trace and quote checked. |
| `0c64cf3a-382a-4ba7-abd8-d095ba28c4b1` | `fd13865682e5538ce16312ec270d480b` | `unnecessary_response_content` | Exact trace and quote checked. |
| `f98324c8-ee7d-4ab6-a1c4-97a8068d541a` | `0b243f127bd9afa7221b6480507ba354` | not supported by current spec | Exact trace and quote checked. |
| `6bc3e19d-39d5-44da-933b-ce5f6e02ed46` | `0b243f127bd9afa7221b6480507ba354` | `unnecessary_response_content` | Exact trace and quote checked. |
| `4c513174-363c-41ae-b51c-3efccc292808` | `7e9c42c82920bb0e4ea54a19010813a3` | `unnecessary_response_content` | Exact trace and quote checked. |
| `925c1802-94d4-48ec-adb6-7a15de861bb8` | `4fe7e8f628d328277f6e5b2f0d4c7c93` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `fb439ea9-c9a2-4298-bc29-242c29b009ba` | `560885f2bf8169423a83c8903cd8faf2` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `f3a74900-f340-4bd5-9c02-fd02a60a7cd9` | `560885f2bf8169423a83c8903cd8faf2` | `unnecessary_response_content` | Note/excerpt only; full trace missing. |
| `53a5d29d-6ff6-4cdc-b5f6-df0ab9023c8f` | `ee2da69c5f562a7d719db0c426ab0754` | not supported by current spec | Exact trace and quote checked. |
| `953bfdbc-35e3-4812-8ac2-0b8004fafa0b` | `49978c79474665f09d746781fa737b80` | requirement decision | Exact trace and quote checked. |
| `2fe7bda2-31a4-43b8-8a07-fca3865305d0` | `05c0bec29fd344c5903fefca5216584d` | `unnecessary_response_content` | Exact trace and quote checked. |
| `e5438829-5e33-4091-912e-800c08b04f25` | `bcb3b68215ebb654e69210e89a636fcf` | not supported by current spec | Exact trace and quote checked. |
| `e85c5d21-85fc-4a2c-b6cd-fbf7c07322f3` | `9fc27b2a646755158a3d1d9a4f26e00c` | `unnecessary_response_content` | Exact trace and quote checked. |
| `32d64a58-17e1-4c1b-999d-b0b84258b71e` | `8534177c687c3219c5d90a9f44edd687` | `unnecessary_response_content` | Exact trace and quote checked. |
| `9fa8ae35-c956-49f1-8bb1-b1e0c5189d00` | `2530e9c957ee78b92e5d851a951d904c` | `unnecessary_response_content` | Exact trace and quote checked. |
| `42341b62-0e9e-4082-acd3-06a954d8546d` | `36cfecb50701b3d52f7e659b03997bbd` | `unsupported_policy_answer` | Exact trace and quote checked. |
| `9c4cd777-baff-4566-af39-6229b592ba2c` | `ca4d9727afb0bf663c8e6ceba604d1b3` | `unnecessary_response_content` | Exact trace and quote checked. |
| `e845ec56-f85b-4026-af00-84b4dbd5db90` | `bf7e795ae9cd4d16db019ebf5d9892a4` | `unexplained_refund_refusal` | Exact trace and quote checked. |
| `a367cc2b-63cf-4299-8948-814f61eb09eb` | `786bc2e9746c915caab5803bcc372fcc` | `unnecessary_response_content` | Exact trace and quote checked. |
| `5013e1d9-c4b7-4332-a9b3-f56d62c7d978` | `82950e902a02d2a777455af6cf82b9ed` | `omitted_requested_action` | Exact trace and quote checked. |
| `a0d3eb9f-4084-438a-a335-a7b12bdf0492` | `c71aba104857fd1b36c3bb3828f0d30b` | `unnecessary_response_content` | Exact trace and quote checked. |
| `3bb33e42-6956-45f3-a4bd-383b321643d6` | `5fe43136ca9ccaeb1f1efa2994cb407c` | `unsupported_policy_answer` | Exact trace and quote checked. |
| `ddd59f1c-9c8e-4f08-8cad-92bf477d0f19` | `947302b09d3786b86adcad4e121f9ea6` | `unsupported_policy_answer` | Exact trace and quote checked. |

## Eight comments requiring a decision

- `c5c52ea0-5a5c-40df-a1c0-4052b61cf48e` (0da84caf6abe4aaf5fca0b5048fb8a94): Hedging preference: the tool confirms refund_eligible=false, but RESP-5 does not ban “It looks like”. A confidence/style rule needs a decision; do not infer an uncertainty failure from this phrase alone.
- `29fa7bd4-68e5-4e82-b28e-65986689cccf` (9ea7ed863fa505f8cf30dc7fe74a885b): RESP-1 requires a policy identifier, which the answer supplies. A clickable-link requirement would be a new specification decision.
- `b7f0909e-af54-4b2f-8e1b-a394051cec72` (3b324bc6a578ea899ae9c3eddc4b796f): RESP-1 requires a policy identifier, which the answer supplies. Keep hyperlink preference separate from unsupported policy content.
- `23b003ac-f12a-49e1-a014-392c45270a2e` (42dc321dbe741e3a70b125bd63442a38): The answer cites cw-returns. A missing hyperlink is not a missing identifier under RESP-1.
- `f98324c8-ee7d-4ab6-a1c4-97a8068d541a` (0b243f127bd9afa7221b6480507ba354): AUTH-1 allows a merchant to refund orders belonging to its own store. The separate note about unsolicited refund commentary is grouped under unnecessary_response_content.
- `53a5d29d-6ff6-4cdc-b5f6-df0ab9023c8f` (ee2da69c5f562a7d719db0c426ab0754): TOOL-7 and issue_refund_logic allow positive amounts up to the order total. The user does not explicitly specify a full-refund amount; policy silence does not establish a partial-refund prohibition.
- `953bfdbc-35e3-4812-8ac2-0b8004fafa0b` (49978c79474665f09d746781fa737b80): Store ID disclosure is a presentation preference here, not evidence of unauthorized data access. The trace also has a malformed store argument, but that is not the failure this human note describes; no extra assignment is inferred.
- `e5438829-5e33-4091-912e-800c08b04f25` (bcb3b68215ebb654e69210e89a636fcf): AUTH-1 permits all roles to search policy. Retrieved cw-payouts supports the schedule; a shopper reading public payout-policy facts is not an authorization violation.

## Remaining human validation

Review the supporting traces before accepting any proposed definition or assignment. Final mode choices, requirement revisions, confirmations, and label decisions remain with the student under HW4 Part D. The eight-mode draft is within the requested 5–8 range, but it is not ready for final labeling: establish three confirmed positives and three close negatives where data permits, resolve the requirement gaps, and recover missing exact traces. The original seven groups retain their earlier unconfirmed examples. The late-batch stability check, repeated depth searches, a genuine human rejection, and the AgentDebug comparison are still pending.

The review app imports helper patterns as provisional on its normal state poll. No restart or data regeneration is needed for these proposed links.
