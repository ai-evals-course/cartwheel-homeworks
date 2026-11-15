# Local Workshop tracing

The server's authenticated message endpoint mirrors a turn summary into local
Workshop with the `raindrop-ai` SDK. After Langfuse initializes OpenTelemetry,
a standard OTLP/HTTP batch exporter mirrors existing spans to Workshop.
Langfuse retains its provider and exporters; OpenLLMetry retains model/tool
instrumentation. Raindrop's own tracing and automatic instrumentation remain
disabled. The local exporter uses no cloud write key and does not inherit OTLP
authorization headers. This follows Raindrop's
[OTLP integration](https://raindrop.ai/docs/sdk/opentelemetry.md) and the SDK's
local Workshop destination convention.

## Start and verify one real run

Start Workshop in your normal terminal:

```bash
~/.raindrop/bin/raindrop workshop
```

The local `.env` should contain the following alongside existing Langfuse settings:

```dotenv
RAINDROP_LOCAL_DEBUGGER=http://localhost:5899/v1/
TRACELOOP_TRACE_CONTENT=true
```

Restart the Cartwheel server to load the instrumentation:

```bash
uv run uvicorn server.app:app --port 8010
```

In a second terminal, run the existing read-only order-status scenario:

```bash
uv run python -m scenarios.runner scenarios/support_scenarios.jsonl \
  --ids support-0001 --model gpt-4o-mini \
  --output /tmp/cartwheel-workshop-smoke.jsonl
```

This makes live model calls and records a fresh conversation. In Workshop,
verify the `cartwheel.session_message` interaction shows input, reply, role,
scenario, session and prompt-version metadata, model calls, token usage, and
tool executions. Tool arguments/results are in the span attributes
`gen_ai.tool.call.arguments` and `gen_ai.tool.call.result`; the current Workshop
version leaves tool input/output previews blank. A multi-turn scenario produces
one interaction per message, linked by conversation ID. This instrumentation
applies to the server endpoint; direct CLI chats do not use it.

## Observed verification (2026-11-15)

- Checked for SDK updates; latest resolved `raindrop-ai` was `0.0.77`.
- Offline: Workshop/authentication/homework checks returned 32 passed,
  3 skipped, 7 xfailed, and 9 xpassed. CLI tracing checks: 23 passed.
  Existing homework placeholders remain; these results do not mean those
  assignments are complete.
- Live: two real `gpt-4o-mini` turns through the authenticated FastAPI endpoint,
  using temporary session databases and read-only order 4127 lookups. The first
  verified summaries; the second verified span enrichment.
- Workshop run `e6d821377b17bc684ad12acb6784d155` contains input/reply, metadata,
  two model calls (1,646 input / 149 output tokens), and one `get_order` execution
  with actual arguments and result. SDK flush reported no pending or dropped events.
- Langfuse's API independently returned the same trace ID with request,
  workflow, agent, two generation observations, and tool observation. The global
  OpenTelemetry provider identity remained unchanged during the invocation.
- Tracing verification does not replace homework assessments or human review.

Leave `RAINDROP_LOCAL_DEBUGGER` blank to disable this mirror. Setting
`TRACELOOP_TRACE_CONTENT=false` omits message and reply text. Pending interactions
and local spans are flushed during graceful server shutdown. Span enrichment
requires an initialized application OpenTelemetry provider; without one,
summaries still work and a warning reports the missing span path.
No human review labels are generated.
