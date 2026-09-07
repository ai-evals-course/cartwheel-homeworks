# Cartwheel course repository

> [!IMPORTANT]
> [Watch this video](https://www.loom.com/share/de1cac47e1a44a79a05f8658157968ae) before beginning

The repository contains the Cartwheel support agent and starter code for all five modules of "Evaluating and Improving AI Agents." Cartwheel is a fictional commerce platform that hosts independent stores. You begin by completing the agent, then use the same repository for trace analysis, automated evaluation, continuous integration, adversarial evaluation, and improvement experiments.

Begin with the [homework index](homework/README.md). Each assignment names the code and records required for the corresponding module.

## Get started with Homework 1

The course instructors put together this [HW1 walkthrough](homework/module-1/hw1-tutorial.md) for anyone who wants a hand, including PMs. Your coding agent handles setup and coding while you decide what to expect and check the results.

Choose the walkthrough for step-by-step help, or ask your agent to jump into a task. You can ask for help whenever you get stuck and switch approaches at any time.

Open this repo in Codex, Claude Code, or your preferred coding agent and paste:

```text
Read AGENTS.md and help me get started with Homework 1.
```

If you haven't downloaded the repo yet, paste this instead:

```text
Help me get started with Homework 1 in https://github.com/ai-evals-course/cartwheel-homeworks. Use my existing local copy if I have one, or help me clone it. Then read AGENTS.md and help me choose how to proceed.
```

## Setup

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). Run the commands from the repository root.

```bash
uv sync
uv run python -m seed.generate
uv run pytest
```

If `.env` does not exist, copy `.env.example` to `.env`. Add a key for the model provider you will use, and preserve any existing settings. The tests and seed command do not require a model key.

The default model is `gpt-5.5` with OpenAI. You can select `claude-opus-4-6` with Anthropic or `glm-5.2` with Together AI using `CARTWHEEL_MODEL` in `.env`. The CLI's `--model` flag overrides the default. You need a key for only one provider.

The starter contains unfinished homework functions. Tests for unfinished functions report expected failures until you implement them. Follow [Homework 1](homework/module-1/hw1.md) to complete the five support tools, then use the chat interface:

```bash
uv run python -m agent.cli --role shopper --user 1
```

CLI tracing is off by default. Add `--debug` to print tool calls and results locally. To send traces to OpenAI, add `--trace-openai` and set `OPENAI_API_KEY`; OpenAI hosted tracing is unavailable for zero-data-retention organizations. For the course's Langfuse setup, use `--trace` instead. The two tracing flags cannot be combined. `OPENAI_AGENTS_DISABLE_TRACING=1` disables SDK tracing for either destination.

The default development seed is the executable course world: 20 stores, 800
products, 525 users, 10,000 orders, and 18 policy documents. The seed script
is deterministic. Two runs produce identical data, and the
three demo orders from lecture (#4127, #3980, #4455, all owned by shopper
user 1) always come out the same. The seed also inserts six documented data
quality defects for challenge scenarios. Their identifiers and expected
handling are stored in the `data_quality_cases` table.

## Homework 2 and tracing

[Homework 2](homework/module-1/hw2.md) asks you to implement the authenticated endpoints and add application attributes to traces. The tracing setup is provided through OpenLLMetry and self-hosted Langfuse. The four HW2 functions listed below are intentionally unfinished; starting the server alone does not complete them.

Homework 2 also requires Docker with Compose. Follow the assignment for starting Langfuse and the server, configuring content capture, and verifying the exported spans. The local Langfuse settings are supplied in `.env.example`, and no Langfuse Cloud account is required.

## Repo map

```
AGENTS.md                 instructions for your coding agent
CLAUDE.md                 symlink to AGENTS.md
SPEC.md                   support specification: scope, access matrix, criteria table
facts.yaml                the facts sheet; every policy number lives here
data/
  policies/*.md           policy corpus, rendered from facts.yaml by the seed
  cartwheel.db            stores, products, users, orders (gitignored; run the seed)
seed/
  generate.py             deterministic world generator (--scale dev|full)
  eligibility.py          the pure refund-eligibility function (the test oracle)
  policies.py             policy-doc templates
  validate.py             checks every number in every doc against facts.yaml
agent/                    support agent scaffold
  agent.py                system prompt, model wiring, provided tools, tool registration
  tools.py                HOMEWORK 1: five tool holes
  auth.py                 auth context + permission checks (complete; do not weaken)
  db.py                   typed SQLite access layer (complete)
  helpcenter.py           policy corpus loading + BM25 (complete)
  cli.py                  chat shell; optional approval flow completed in Module 4
server/
  app.py                  HOMEWORK 2: session + message routes; token helpers provided
observability/
  docker-compose.yml      self-hosted Langfuse (web, worker, postgres, clickhouse, redis, minio)
  instrument.py           tracing setup (provided) + HOMEWORK 2: tool span attributes
scenarios/
  skill/SKILL.md          instructions that a coding agent follows to generate scenarios
  validate.py             executable schema and final-dataset checks
  runner.py               plays scenario JSONL against the endpoint (complete)
  export_langfuse.py      exports complete scenario traces for Module 2
analysis/                 MODULE 2: review interface, helper functions, and judge records
eval_cases/               MODULE 3: reviewed regression and capability cases
tests/eval/               MODULE 3: unit, integration, and end to end evaluation tests
replay/                   MODULE 3: repeated evaluation case execution
monitoring/               MODULE 3: sampling, corrected rates, and score writing
agent/guards.py           MODULE 4: input, output, and tool guards
agent/approvals.py        MODULE 4: refund approval and audit records
promptfooconfig.yaml      MODULE 4: automated adversarial evaluation
reports/
  smoke.sql               smoke-report queries against the trace store
homework/                 student assignments for Modules 1 to 5
tests/                    offline, no API keys; homework tests are xfail until done
```

## Module 1 implementation tasks

| Homework | File | Holes |
| --- | --- | --- |
| HW1 | `agent/tools.py` | `get_policy`, `search_products`, `list_my_orders`, `cancel_order`, `find_order` |
| HW2 | `observability/instrument.py` | `record_tool_result`, `_set_permission_denied_attributes` |
| HW2 | `server/app.py` | `create_session`, `post_message` |

The Module 1 implementation tasks are marked `### YOUR CODE HERE (HW1)` or `### YOUR CODE HERE (HW2)` and have docstrings describing the expected behavior. The supplied contract tests in `tests/test_hw_holes.py` cover the five HW1 tools and HW2 session creation. Homework 2 also asks you to write authentication tests and verify exported spans in Langfuse. Use the test commands in each assignment to check your implementation.

> [!IMPORTANT]
> The Module 1 handouts are in `homework/module-1/`. The [homework index](homework/README.md) lists all released assignments. A [video walkthrough](https://youtu.be/qO98jDayTHo?si=gLN5FZ3FDiAIs_gG) of how to attempt Homework 1 is also available.
