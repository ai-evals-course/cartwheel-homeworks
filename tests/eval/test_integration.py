"""Integration tests for one agent step, with the remaining behavior fixed.

The unit under test is a subtree of the trajectory (Module 2.1): grounding,
or tool-output handling. The model is scripted (FakeModel, the SDK's own
test pattern) and/or the tool is mocked (unittest.mock), so these tests are
cheap and repeatable like unit tests but exercise the REAL Runner loop and
the REAL tool plumbing. They run on every push, with zero API calls.

What each test isolates:

  - Wrapper delegation: search_products forwards arguments, records its
    result, and converts NotImplementedError into a structured tool error.
    This checks the SDK tool boundary without a model call.

  - Grounding: fix the retrieved-docs set (mock the retrieval tool) and
    assert the model's next-turn context contains exactly those docs. With
    a live model, the follow-on assertion is that the answer cites the store
    override's 14-day figure, not the platform 30-day default; the fixture
    here proves the harness feeds the model the right context, which is the
    half a scripted model can check byte-for-byte.
  - Tool-output handling: mock `issue_refund` to return queued_for_approval
    and assert that truth reaches the model's context verbatim. The
    `tool_result_misreport` failure (saying "processed" when the tool said
    "queued") can only happen after this point, so a live-model version of
    this test asserts the reply says queued; the scripted version pins the
    plumbing half.
  - End state through the real tool: a scripted refund on order #4127
    actually writes an auto_approved refund row, because the real Runner
    executed the real tool against the (copied) seeded world.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from agents import Agent, Runner
from agents.tool_context import ToolContext

from agent.agent import TOOLS_BY_ROLE, render_system_prompt, search_products
from agent.auth import AuthContext
from tests.eval.fake_model import FakeModel, text_message, tool_call

SHOPPER_1 = AuthContext(user_id=1, role="shopper")


@pytest.mark.parametrize("implemented", [False, True])
def test_integration_search_products_wrapper(implemented: bool) -> None:
    arguments = json.dumps({"query": "mug", "store": "Ceramics", "max_price_usd": 25, "limit": 2})
    context = ToolContext(
        context=SHOPPER_1, tool_name="search_products",
        tool_call_id="search", tool_arguments=arguments,
    )
    expected = (
        {"ok": True, "products": []} if implemented else
        {"ok": False, "error": "not_implemented", "reason": "homework hole"}
    )
    with (
        patch(
            "agent.agent.hw_tools.search_products", return_value=expected,
            side_effect=None if implemented else NotImplementedError("homework hole"),
        ) as search,
        patch("agent.agent.record_tool_result") as record,
    ):
        result = asyncio.run(search_products.on_invoke_tool(context, arguments))

    assert result == expected
    search.assert_called_once_with(SHOPPER_1, "mug", store="Ceramics", max_price_usd=25, limit=2)
    record.assert_called_once_with(SHOPPER_1, expected)


def _build_fake_agent(ctx: AuthContext, fake: FakeModel) -> Agent[AuthContext]:
    return Agent[AuthContext](
        name="cartwheel-support",
        instructions=render_system_prompt(ctx),
        tools=TOOLS_BY_ROLE[ctx.role],
        model=fake,
    )


def _function_call_outputs(request_input: object) -> list[str]:
    """The tool outputs the model saw in one request, as strings."""
    outputs: list[str] = []
    if isinstance(request_input, list):
        for item in request_input:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                outputs.append(json.dumps(item.get("output")))
    return outputs


def test_integration_grounding_feeds_fixed_docs_to_the_model(world: dict) -> None:
    """Fix retrieval to two docs (platform policy + a 14-day store override)
    and assert the model's second-turn context holds exactly that override
    figure. Grounding is isolated from retrieval: a failure here points at
    output handling, not ranking."""
    fixed_docs = {
        "ok": True,
        "results": [
            {
                "policy_id": "cw-returns",
                "title": "Returns and refunds",
                "snippet": "Cartwheel's platform return window is 30 days from delivery.",
                "score": 9.0,
            },
            {
                "policy_id": "store-juniper-home-goods",
                "title": "Juniper Home Goods store policies",
                "snippet": "Juniper Home Goods accepts returns for 14 days from delivery.",
                "score": 8.5,
            },
        ],
    }
    fake = FakeModel()
    fake.set_next_output(
        [tool_call("search_help_center", {"query": "Juniper Home Goods return window"})]
    )
    fake.set_next_output(
        [text_message("Juniper Home Goods accepts returns for 14 days (store-juniper-home-goods).")]
    )
    agent = _build_fake_agent(SHOPPER_1, fake)

    with patch("agent.agent.search_help_center_logic", return_value=fixed_docs):
        result = Runner.run_sync(
            agent,
            "what's the return window at Juniper Home Goods?",
            context=SHOPPER_1,
        )

    # The real Runner made exactly two model calls: tool turn, answer turn.
    assert len(fake.requests) == 2
    # The model's second-turn context carries the fixed docs verbatim: the
    # override's 14-day figure and both policy ids made it through the real
    # tool plumbing.
    outputs = _function_call_outputs(fake.requests[1]["input"])
    assert outputs, "the tool result never reached the model"
    joined = " ".join(outputs)
    assert "14 days" in joined
    assert "store-juniper-home-goods" in joined
    assert "cw-returns" in joined
    assert "Juniper Home Goods" in str(result.final_output)


def test_integration_tool_output_handling_sees_queued_not_processed(world: dict) -> None:
    """Mock `issue_refund` to return queued_for_approval and assert that
    truth reaches the model verbatim (the tool_result_misreport subtree,
    stage-4 tool-output handling from Module 2.6)."""
    queued = {
        "ok": True,
        "status": "queued_for_approval",
        "refund_id": 999,
        "order_id": 4455,
        "amount_usd": 240.0,
        "note": "amount is above the $100 auto-approval threshold; a human support agent will review it",
    }
    fake = FakeModel()
    fake.set_next_output(
        [tool_call("issue_refund", {"order_id": 4455, "amount_usd": 240.0, "reason": "cracked"})]
    )
    fake.set_next_output(
        [text_message("Your refund request is queued for review by a human agent.")]
    )
    agent = _build_fake_agent(SHOPPER_1, fake)

    with patch("agent.agent.issue_refund_logic", return_value=queued):
        Runner.run_sync(
            agent,
            "refund my $240 order #4455, it arrived cracked",
            context=SHOPPER_1,
        )

    outputs = _function_call_outputs(fake.requests[1]["input"])
    assert outputs, "the tool result never reached the model"
    joined = " ".join(outputs)
    assert "queued_for_approval" in joined
    # The failure this subtree guards is the reply contradicting this field;
    # a live-model version asserts the reply says queued, never processed.
    assert "auto_approved" not in joined


def test_integration_scripted_refund_writes_the_real_end_state(world_copy: Path) -> None:
    """A scripted tool call executes the REAL tool against the copied seeded
    world: order #4127 ($84, eligible, under the threshold) ends refunded
    with an auto_approved refund row. State-based grading, mocked model."""
    fake = FakeModel()
    fake.set_next_output(
        [tool_call("issue_refund", {"order_id": 4127, "amount_usd": 84.0, "reason": "leaking base"})]
    )
    fake.set_next_output([text_message("Done: $84.00 refunded to your original payment method.")])
    agent = _build_fake_agent(SHOPPER_1, fake)

    Runner.run_sync(agent, "please refund order #4127", context=SHOPPER_1)

    conn = sqlite3.connect(world_copy)
    try:
        refund = conn.execute(
            "SELECT status, amount_cents FROM refunds WHERE order_id = 4127"
        ).fetchone()
        order_status = conn.execute(
            "SELECT status FROM orders WHERE id = 4127"
        ).fetchone()[0]
    finally:
        conn.close()
    assert refund == ("auto_approved", 8400)
    assert order_status == "refunded"
