from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic.v1 import BaseModel

from scenarios.export_langfuse import _jsonable, export_scenario_traces


class FakeTraceApi:
    def __init__(self) -> None:
        self.summaries = [
            SimpleNamespace(id="t1", metadata={"cartwheel.scenario_id": "support-1"}),
            SimpleNamespace(id="noise", metadata={}),
            SimpleNamespace(id="t2", metadata={"cartwheel.scenario_id": "support-2"}),
        ]

    def list(self, *, page: int, limit: int):
        start = (page - 1) * limit
        return SimpleNamespace(data=self.summaries[start : start + limit])

    def get(self, trace_id: str):
        if trace_id == "t2":
            return {
                "id": trace_id,
                "observations": [
                    {"metadata": {"cartwheel.scenario_id": "support-2"}}
                ],
            }
        return {"id": trace_id, "observations": []}


def test_export_filters_and_paginates_scenario_traces() -> None:
    client = SimpleNamespace(api=SimpleNamespace(trace=FakeTraceApi()))
    client.api.trace.summaries[2].metadata = {}
    records = export_scenario_traces({"support-1", "support-2"}, client, page_size=2)
    assert [record["id"] for record in records] == ["t1", "t2"]
    assert [record["cartwheel_scenario_id"] for record in records] == [
        "support-1",
        "support-2",
    ]


class NestedTraceApi(FakeTraceApi):
    """Langfuse stores OTel span attributes under metadata.attributes."""

    def __init__(self) -> None:
        self.summaries = [
            SimpleNamespace(
                id="t3",
                metadata={"scope": {}, "attributes": {"cartwheel.scenario_id": "support-3"}},
            ),
            SimpleNamespace(id="t4", metadata={"scope": {}}),
        ]

    def get(self, trace_id: str):
        if trace_id == "t4":
            return {
                "id": trace_id,
                "metadata": {"scope": {}},
                "observations": [
                    {
                        "metadata": {
                            "attributes": json.dumps({"cartwheel.scenario_id": "support-4"})
                        }
                    }
                ],
            }
        return {
            "id": trace_id,
            "metadata": {"scope": {}, "attributes": {"cartwheel.scenario_id": "support-3"}},
            "observations": [],
        }


def test_export_reads_nested_langfuse_attributes() -> None:
    client = SimpleNamespace(api=SimpleNamespace(trace=NestedTraceApi()))
    records = export_scenario_traces({"support-3", "support-4"}, client, page_size=2)
    assert [record["cartwheel_scenario_id"] for record in records] == [
        "support-3",
        "support-4",
    ]



class V1Trace(BaseModel):
    """Shape of the Langfuse SDK's pydantic v1 response models."""

    id: str
    timestamp: datetime


def test_jsonable_serializes_pydantic_v1_datetimes() -> None:
    record = _jsonable(V1Trace(id="t", timestamp=datetime(2026, 9, 5, tzinfo=timezone.utc)))
    json.dumps(record)
    assert record["timestamp"].startswith("2026-09-05")
