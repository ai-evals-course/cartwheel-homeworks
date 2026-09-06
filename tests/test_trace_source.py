"""Offline regression coverage for the Module 2 trace-source workflow."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from analysis.helpers import _state, langfuse_io, scale, tools


@pytest.fixture(autouse=True)
def offline_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTWHEEL_ANALYSIS_STATE", str(tmp_path / "state"))
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def records() -> list[dict]:
    return [
        {
            "id": "live-1",
            "input": "Can I return my order?",
            "output": "I will check the policy.",
            "metadata": {"cartwheel.scenario_id": "support-1"},
            "observations": [
                {"type": "TOOL", "name": "search_policy", "output": "30 days"}
            ],
        },
        {"trace_id": "live-2", "turns": [{"user": "Hello", "agent": "Hi"}]},
    ]


@pytest.mark.parametrize("format", ["list", "wrapped", "jsonl"])
def test_selection_then_labeling_uses_manifest(
    tmp_path: Path, records: list[dict], format: str
) -> None:
    export = tmp_path / ("export.jsonl" if format == "jsonl" else "export.json")
    if format == "jsonl":
        export.write_text("\n".join(json.dumps(record) for record in records))
    else:
        export.write_text(json.dumps({"traces": records} if format == "wrapped" else records))
    samples = tools.select_traces(export, k=1, strategy="random")
    saved = _state.read_json(_state.state_path("samples.json"))
    assert saved == samples
    assert isinstance(saved, list)
    assert set(saved[0]) == {
        "trace_id", "reason", "trace", "text", "features", "meta", "permalink", "flags"
    }
    manifest = _state.read_json(_state.state_path("sample_manifest.json"))
    assert manifest["source"] == str(export)
    assert set(manifest) == {"source", "k", "strategy", "selected_at", "picks"}
    _state.append_jsonl(
        _state.state_path("labels", "returns.jsonl"),
        {"trace_id": samples[0]["trace_id"], "label": 1},
    )
    # Labeling uses the complete source, including records outside the sample.
    unsampled_id = ({"live-1", "live-2"} - {samples[0]["trace_id"]}).pop()
    assert tools.next_to_label("returns", k=10, strategy="random") == [
        {"trace_id": unsampled_id, "signal": "random"}
    ]


def test_explicit_source_overrides_manifest(tmp_path: Path, records: list[dict]) -> None:
    _state.write_json(_state.state_path("sample_manifest.json"), {"source": "missing.json"})
    export = tmp_path / "override.json"
    export.write_text(json.dumps(records))
    assert len(tools.next_to_label("returns", k=2, strategy="random", trace_source=export)) == 2


def test_no_manifest_returns_no_candidates() -> None:
    # The review UI's list is never interpreted as source configuration.
    _state.write_json(_state.state_path("samples.json"), [{"trace_id": "sample"}])
    assert tools.next_to_label("returns", k=1) == []


def test_langfuse_selection_labeling_and_scaling_share_normalized_records(
    monkeypatch: pytest.MonkeyPatch, records: list[dict]
) -> None:
    # Exercise the real Langfuse reader with an offline client, including its
    # normalization and scenario filtering. No SDK or network is needed.
    record = records[0]
    full = SimpleNamespace(id=record["id"], model_dump=lambda **kwargs: record)
    trace_api = SimpleNamespace(
        list=Mock(return_value=SimpleNamespace(data=[SimpleNamespace(id=full.id)])),
        get=Mock(return_value=full),
    )
    monkeypatch.setattr(langfuse_io, "is_configured", lambda: True)
    monkeypatch.setattr(langfuse_io, "_client", lambda: SimpleNamespace(api=SimpleNamespace(trace=trace_api)))
    live = tools._load_trace_source("LaNgFuSe")
    samples = tools.select_traces("langfuse", k=1, strategy="random")
    assert samples[0]["trace_id"] == "live-1"
    assert samples[0]["meta"] == {"scenario_id": "support-1"}
    assert samples[0]["text"] == live[0]["text"]
    assert tools.next_to_label("returns", k=1, strategy="random") == [
        {"trace_id": "live-1", "signal": "random"}
    ]
    assert scale.load_store_traces() == live
    assert trace_api.get.call_count == 4


@pytest.mark.parametrize("caller", ["select", "next"])
@pytest.mark.parametrize("failure", ["empty", "error"])
def test_failed_live_source_never_uses_demo_or_overwrites_samples(
    monkeypatch: pytest.MonkeyPatch, caller: str, failure: str
) -> None:
    _state.write_json(_state.state_path("store_traces.json"), [{"id": "demo", "text": "demo"}])
    _state.write_json(_state.state_path("samples.json"), [{"trace_id": "previous"}])
    manifest = {"source": "langfuse", "k": 1}
    _state.write_json(_state.state_path("sample_manifest.json"), manifest)
    monkeypatch.setattr(langfuse_io, "is_configured", lambda: True)
    fetch = Mock(return_value=[], side_effect=RuntimeError("unavailable") if failure == "error" else None)
    monkeypatch.setattr(langfuse_io, "fetch_traces", fetch)
    expected = RuntimeError if failure == "error" else ValueError
    with pytest.raises(expected, match="unavailable" if failure == "error" else "Langfuse returned no traces"):
        if caller == "select":
            tools.select_traces("langfuse", k=1)
        else:
            tools.next_to_label("returns", k=1)
    fetch.assert_called_once_with()
    assert _state.read_json(_state.state_path("samples.json")) == [{"trace_id": "previous"}]
    assert _state.read_json(_state.state_path("sample_manifest.json")) == manifest


def test_unconfigured_live_source_requires_explicit_export(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = Mock(side_effect=AssertionError("offline test reached live fetch"))
    monkeypatch.setattr(langfuse_io, "fetch_traces", fetch)
    export = _state.state_path("store_traces.json")
    _state.write_json(export, [{"trace_id": "demo", "segments": {"topic": "refund"}}])
    with pytest.raises(langfuse_io.LangfuseNotConfigured, match="export path"):
        tools.select_traces("langfuse", k=1)
    samples = tools.select_traces(export, k=1)
    assert samples[0]["trace_id"] == "demo"
    assert samples[0]["text"] == "observation: refund"
    assert scale.load_store_traces() == tools._load_trace_source(export)
    fetch.assert_not_called()


def test_missing_explicit_export_is_not_replaced_with_demo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="trace export does not exist"):
        tools.next_to_label("returns", k=1, trace_source=tmp_path / "missing.json")


@pytest.mark.parametrize("source", [Path("langfuse"), "export.json"])
def test_manifest_file_source_survives_working_directory_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str | Path
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(source).write_text(json.dumps([{"id": "file-trace", "text": "hello"}]))
    tools.select_traces(source, k=1)
    manifest = _state.read_json(_state.state_path("sample_manifest.json"))
    assert manifest["source"] == str(Path(source).resolve())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert tools.next_to_label("returns", k=1, strategy="random") == [
        {"trace_id": "file-trace", "signal": "random"}
    ]
