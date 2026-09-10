# Homework 2, implementing the traced agent endpoint

Homework 2 asks you to expose the support agent through an authenticated HTTP endpoint and record its execution using OpenTelemetry GenAI semantic conventions. You will inspect model inputs, outputs, and tool results, then verify which authenticated identity reached the tools.

## Working through the assignment with a coding agent

If you would like a coding agent to walk you through the assignment, paste the prompt below at the start of a session in your repository. The prompt assumes no programming background, so it suits an analyst or a product manager as well as an engineer. The Homework 1 tutorial does not cover Homework 2.

> Walk me through Homework 2 in `homework/module-1/hw2.md` as an interactive tutorial. Read `AGENTS.md`, `homework/module-1/AGENTS.md`, the handout, and `SPEC.md` first. I may not have a programming background, so assume nothing about what I know, and adapt once you see what I do know.
>
> I am driving. Work one step at a time, in the handout's order. Before each step, explain in plain language what you propose to do and why the assignment needs it, and show me the command you would run or the change you would make. Then wait for me to say go. Do not run a command, change a file, or generate anything until I have said so, and do not take several steps on one go ahead. Reading files to prepare a proposal is fine. Once I say go, do that step, show me the result, and explain what it means. Move on only when you are confident I understand the current step. One short question about what I expect to see, or what a result means, is enough to check; keep questions few, and do not turn the session into a quiz. Explain every unfamiliar term the first time it appears, using the actual files and outputs as examples. When a picture would help, draw one; a text diagram is fine.
>
> If something fails, read the error, explain it plainly, and propose a focused fix. Keep a short progress note of what is done and what is next, so we can resume later, and keep a checklist of every deliverable so nothing is skipped. Leave the assessments and the video to me. Do not call the assignment done until every file in the "Files to commit" list exists and the checks in the handout pass.
>
> Concepts I need to understand before we use them: what an HTTP endpoint and a session are, why the server, not the conversation, decides who I am, what a trace and a span are, and how the standard `gen_ai.*` fields differ from the application's `cartwheel.*` fields. Diagrams that would help me: the path from my message to the endpoint, the agent, the tools, and the trace, and the tree of spans inside one trace.

## Expected work

- Estimated time: 4 to 6 hours.
- Expected production code: approximately 60 to 80 lines in `server/app.py` and `observability/instrument.py`.
- Expected test code: approximately 30 to 50 lines in `tests/test_observability.py`.
- Expected total code: approximately 90 to 130 lines.
- Other work: at least five traced requests, two trace records in JSON, and a video of no more than 5 minutes.

The estimate assigns most of the time to implementing and testing the endpoint. Starting Docker is necessary setup, but it is not counted as substantive programming work.

## Preparation

Continue in the same repository from Homework 1, with the five support tools implemented and the local database generated. Run the commands below from the repository root.

Read the following files before editing code:

- `server/app.py`, which provides request models and token helpers.
- `observability/instrument.py`, which configures OpenTelemetry and Langfuse.
- `agent/auth.py`, which defines the authenticated context passed to tools.
- `_call` in `agent/agent.py`, which invokes `record_tool_result` after every tool call.

The token implementation is suitable only for local development. The provided token allows the endpoint to distinguish identity supplied by the server from identity claimed in a conversation.

The supplied setup uses OpenLLMetry OpenAI Agents instrumentation to record agent, model, and tool operations. Langfuse receives the spans through its native OpenTelemetry integration. Standard fields describe the model and token usage. The recorded model fields depend on the model API; the inspection instructions in Part E explain which fields to check. Application fields remain in `cartwheel.*`. Read the [OTel GenAI overview](https://opentelemetry.io/blog/2026/genai-observability/).

Run `uv sync` to install the locked dependencies. You will verify tracing in Langfuse in Part E.

## Part A, add application attributes to tool spans

OpenLLMetry records each tool execution, including its arguments and result. In this part you add the authenticated caller and permission decision to the same tool span.

Implement `record_tool_result` and `_set_permission_denied_attributes` in `observability/instrument.py`.

Use the active tool span returned by `trace.get_current_span()`. Add the following application attributes:

- `cartwheel.user_role`, as a string (same for every tool call in the request)
- `cartwheel.user_id`, as the decimal user identifier stored in a string (same for every tool call in the request)
- `cartwheel.store_id`, as an integer when the caller is a merchant (same for every tool call in the request)
- `cartwheel.permission_denied`, as a Boolean value
- `cartwheel.permission_denied.reason`, when permission was denied

The supplied tool wrappers call the recorder while the tool span is active. Standard `gen_ai.*` fields and application `cartwheel.*` fields belong on the same span.

Verify the tool spans in Langfuse in Part E.

## Part B, implement session creation

The agent needs an authenticated caller before it can enforce access control. In this part you build the session creation endpoint that validates a user's identity against the database and issues a signed token.

Implement `create_session` in `server/app.py`. The endpoint must:

- Reject an unknown role with HTTP 400.
- Load the requested user from the database.
- Reject an unknown user identifier with HTTP 404.
- Reject a role different from the user's stored role with HTTP 403.
- Create an `AuthContext` from the stored identity.
- Store the context and its `SQLiteSession` in `_SESSIONS`.
- Return a session identifier and a signed token with HTTP 200.

The signed token must contain `session_id`, `user_id`, `role`, `store_id`, and `issued_at`, using the verified database identity. Do not construct the authorization context from later chat messages.

After implementing, run the session creation test:

```bash
uv run pytest --runxfail -vv tests/test_hw_holes.py -k "create_session_binds"
```

## Part C, implement the traced message endpoint

The supplied OTel GenAI instrumentation already records model spans and tool spans automatically. Part A added application attributes to the tool spans. In this part you create the root span that wraps the full request and carries the remaining application attributes.

Implement `post_message` in `server/app.py`. The endpoint must authorize the bearer token before it runs the agent. The authorization checks are already provided in `_authorize`: a missing or invalid token returns HTTP 401, a token issued for a different session returns HTTP 403, and an unknown session returns HTTP 404. The endpoint must then recover the session stored by the server and compute the prompt version by hashing only the system prompt template.

Run the agent inside a root span named `cartwheel.session_message`. Record the following attributes on the root span:

- `cartwheel.user_role`
- `cartwheel.user_id`, as the decimal user identifier stored in a string
- `cartwheel.prompt_version`
- `cartwheel.scenario_id`, when the request supplies a nonempty value
- `gen_ai.input.messages`, containing the incoming user message
- `gen_ai.output.messages`, containing the final assistant reply after the run completes

Use the OTel GenAI message format, serialized with `json.dumps`, for both message attributes. For example, the input is `[{"role": "user", "parts": [{"type": "text", "content": body.message}]}]`. The output uses the same structure with role `assistant` and the final reply as its text. The automatic model spans contain the full input for each model call, including conversation history and tool results.

Return the session identifier, final reply, and prompt version.

Verify the root span and its attributes in Langfuse in Part E.

## Part D, test authentication

Create `tests/test_observability.py` with authentication tests for the following cases:

- Session creation rejects a user whose claimed role differs from the database role.
- A token issued for one session cannot authorize a different session.

The tests must not require Langfuse, Docker, or a model provider key. Check tracing through the recorded spans in Part E.

Run the supplied session creation test:

```bash
uv run pytest --runxfail tests/test_hw_holes.py -k hw2
```

Then run your tests and the complete suite:

```bash
uv run pytest tests/test_observability.py
uv run pytest
```

## Part E, run the endpoint and inspect traces

After implementing the endpoints and testing authentication, run the full stack and confirm that the required spans appear in Langfuse.

If you have not created `.env`, copy `.env.example` to `.env` and add one model provider key. Do not overwrite an existing `.env`. Verify that the three `LANGFUSE_*` values from `.env.example` are also present. You do not need a Langfuse Cloud account; the Docker Compose file runs a local Langfuse instance, and the `.env.example` values point at it.

Keep the course configuration in `.env`. No shell exports are needed.

Docker with Compose is required for the local trace stack.

For the fictional course data, add `TRACELOOP_TRACE_CONTENT=true` to your existing `.env` before starting the server. The setting is included in the updated `.env.example`; do not overwrite your keys. Without content capture, model metadata is recorded but the messages needed for review are omitted. Use `TRACELOOP_TRACE_CONTENT=false` when message content must not be recorded, and redact sensitive information before exporting traces.

For a model call, inspect the recorded model identifier, messages, and token counts. The standard integration records `gen_ai.request.model` for Chat Completions and LiteLLM calls, and `gen_ai.response.model` for Responses API calls. The first identifies the model requested by the caller; the second identifies the model returned by the provider. The pinned integration omits the requested model on Responses API spans; you do not need to patch the library to add it.

For a tool call, inspect `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, and the captured arguments and result. Confirm that the related spans share the request's trace ID.

OpenLLMetry also creates an `Agent Workflow` span around the SDK run. The span groups the agent operations; it is not another model call. Use the tree or timeline to inspect individual calls. If the formatted view shows nested message `parts`, expand the values or use the JSON view to read the recorded messages.

Start Langfuse and the agent server in separate terminals:

```bash
docker compose -f observability/docker-compose.yml up -d
uv run uvicorn server.app:app --port 8010
```

Open `http://localhost:3000`, then sign in as `student@example.com` with the password `cartwheel-dev-pass`.

Create a session with an HTTP client:

```bash
curl -s -X POST http://localhost:8010/sessions \
  -H 'Content-Type: application/json' \
  -d '{"user_id":1,"role":"shopper"}'
```

Copy the returned session identifier and token into a message request:

```bash
curl -s -X POST http://localhost:8010/sessions/SESSION_ID/messages \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer TOKEN' \
  -d '{"message":"Show my recent orders."}'
```

Submit at least five requests drawn from `hw1-session.jsonl`. For each request, use a session for the corresponding authenticated user and inspect the resulting trace in Langfuse.

In Langfuse, open the root span and tool spans and check the attributes listed in Parts A and C. Confirm that the response contains the session identifier, final reply, and prompt version. For an allowed tool call, confirm `cartwheel.permission_denied = false` with no denial reason. If a tool call returns a permission denial, confirm `cartwheel.permission_denied = true` and the recorded reason. You do not need to produce a permission denial or use a prescribed request.

## Part F, compare two prompt versions

Module 2 will use prompt version hashes to group traces by the prompt that produced them. In this part you confirm that the instrumentation captures the version and that a prompt change produces a different hash, establishing the baseline for later comparisons.

Choose one request from `hw1-session.jsonl` and save the current `SYSTEM_PROMPT_TEMPLATE` from `agent/agent.py`. Submit the request through the Homework 2 endpoint in a new session, then find its trace in Langfuse and record `cartwheel.prompt_version`. Homework 1 does not require traces, so generate the trace for the comparison now.

Stop the server and temporarily replace the prompt with the earlier version from Homework 1. If Homework 1 did not produce a revision, make a small wording change for the purpose of checking version recording. A wording change for this check does not need to address a failure.

Restart the server, create a new session and token for the same authenticated user, and submit the same request using the same model. Verify that `cartwheel.prompt_version` differs between the two traces. Restore the saved prompt and restart the server when the comparison is complete.

Both runs must start with empty message history and the same database state. If the request changes an order, reset the development data with `uv run python -m seed.generate` before each run. The seed command restores the initial world and removes changes from earlier requests. The comparison checks prompt version recording, rather than whether one prompt performs better.

## Trace record

Choose any two traces you can explain from the root span through the final response.

Create `hw2-traces.json` as a JSON array containing exactly two objects. For each trace, record:

- `trace_id`
- `permalink`
- `prompt_version`
- `user_role`
- `user_id`
- `tool_order`, as an ordered list of tool names
- `final_status`, with the value `completed` or `error`

## Files to commit

- `observability/instrument.py`
- `server/app.py`
- `tests/test_observability.py`
- `hw2-traces.json`, containing the two selected traces

## Video

Record one continuous screen video of no more than 5 minutes. In the recording:

- Run one authentication test.
- Read both selected traces from the root span to the final response.
- Explain how the endpoint established the authenticated identity.
- Explain the tool calls and their results in the selected traces.
- Show the two prompt version hashes produced by the controlled comparison.
- Regenerate the span count for one selected trace.
