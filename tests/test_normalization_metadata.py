"""The Module 2 normalizer must read attributes nested by Langfuse."""

from __future__ import annotations

import json

from analysis.helpers.normalization import _metadata, normalize_trace


def test_metadata_merges_nested_langfuse_attributes() -> None:
    record = {
        "metadata": {
            "scope": {},
            "attributes": json.dumps(
                {"cartwheel.scenario_id": "support-9", "cartwheel.user_role": "shopper"}
            ),
        }
    }
    merged = _metadata(record)
    assert merged["cartwheel.scenario_id"] == "support-9"
    assert merged["cartwheel.user_role"] == "shopper"


def test_metadata_keeps_flat_keys_authoritative() -> None:
    record = {
        "metadata": {
            "cartwheel.scenario_id": "flat",
            "attributes": {"cartwheel.scenario_id": "nested"},
        }
    }
    assert _metadata(record)["cartwheel.scenario_id"] == "flat"


def test_normalized_trace_keeps_cartwheel_session_id() -> None:
    trace = normalize_trace(
        {
            "id": "trace-1",
            "text": "hello",
            "metadata": {
                "attributes": {"cartwheel.session_id": "session-1"},
            },
        }
    )
    assert trace["meta"]["session_id"] == "session-1"
