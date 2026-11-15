# Workshop conversation batch

Executed nine existing Cartwheel scenarios with live `gpt-4o-mini` on
2026-11-15 UTC. All ten user turns returned HTTP 200 and were independently
found in Workshop. The order-status conversation includes a follow-up.

The selection spans shopper, merchant, and support roles, with order status,
refund, cancellation, policy, product search, dispute, and out-of-scope intents.
These describe requested tasks; they do not assert which actions succeeded.
Observed execution includes 20 model calls and 10 tool calls across `get_order`,
`issue_refund`, `search_help_center`, and `search_products`.

Execution used the authenticated FastAPI endpoints through a lifespan-managed
TestClient, the unchanged agent configuration, a SQLite backup in `/tmp`, and
a separate temporary session database. Refunds and other writes targeted the
copy. The existing server process, source database, annotations, and taxonomy
were not changed. Existing Langfuse/OpenTelemetry setup remained enabled.

- `scenarios.jsonl`: exact selected scenarios from `scenarios/support_scenarios.jsonl`.
- `conversations.jsonl`: observed user messages, replies, HTTP statuses, and prompt versions.
- `manifest.json`: session IDs, model, execution paths, flush results, and linked Workshop run IDs.
- `workshop_runs.json`: independently queried run IDs and model/tool span counts.
- `workshop_tools.json`: observed tool span attributes, including arguments and results.

Flush completed with no pending or dropped Raindrop events. This completes
conversation generation for Part C. Coding-agent inspection and uncertainty
reporting are now in [workshop_notes.md](../workshop_notes.md).
Human decisions remain pending. No failure labels or human assessments were generated.
