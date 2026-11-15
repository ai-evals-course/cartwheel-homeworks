# Complete comment taxonomy coverage

Current snapshot: 55 human comments at review revision 133. All 55 now have a taxonomy group; zero are unassigned. There are 13 provisional groups. Existing saved modes, human annotations, labels, and decisions were preserved. The removed hedging note was not restored.

This update follows the request to classify every comment, including singleton groups. Five new groups organize the seven remaining comments. These are provisional topic groups with explicit requirement-decision boundaries, not confirmed failures. No specification change, model call, live trace retrieval, or score write was performed.

| New group | Comments | Requirement status |
| --- | ---: | --- |
| `policy_link_missing` | 3 | Proposed extension of RESP-1; clickable links are not currently required. Requirement decision pending. |
| `merchant_refund_handling` | 1 | AUTH-1 explicitly allows this capability. Any proposed restriction needs a student requirement decision; no authorization failure is confirmed. |
| `partial_refund_amount_prompt` | 1 | TOOL-7 permits partial amounts; a full-refund default or prohibition would require a student requirement decision. |
| `internal_identifier_in_reply` | 1 | Candidate presentation refinement of RESP-5. No current blanket prohibition on internal identifiers; requirement decision pending. |
| `public_policy_audience_concern` | 1 | AUTH-1 currently allows policy searches for all roles. A new audience restriction requires a student requirement decision. |

The earlier unassigned-comment review is historical. Its unresolved comments are now grouped, while the interpretation questions remain open. Exact saved trace IDs and original annotation IDs are linked in patterns.json. The earlier offline evidence checks apply; no fresh trace verification is claimed.

HW4 asks for 5–8 final failure modes. These 13 groups provide complete provisional comment organization; final selection, merges, and requirement decisions remain pending with the student. Topic coverage does not establish confirmed-positive or close-negative quotas.
