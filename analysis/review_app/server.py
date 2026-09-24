"""Review interface for Homework 4 error analysis.

Extends the reference server with conversation grouping, structured labels,
and Langfuse score sync. Serves ``index.html`` and reads/writes
``analysis/state/``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
STATE_DIR = HERE.parent / "state"
UI_PATH = HERE / "index.html"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.review_app.grouping import build_conversations  # noqa: E402

API_FILES: dict[str, Path] = {
    "/api/samples": STATE_DIR / "samples.json",
    "/api/annotations": STATE_DIR / "annotations.json",
    "/api/graph": STATE_DIR / "graph.json",
    "/api/patterns": STATE_DIR / "patterns.json",
    "/api/suggestions": STATE_DIR / "suggestions.json",
}

API_DEFAULTS: dict[str, Any] = {
    "/api/samples": [],
    "/api/annotations": {"annotations": []},
    "/api/graph": {"nodes": [], "clusters": []},
    "/api/patterns": {"modes": []},
    "/api/suggestions": [],
}

_trace_cache: list[dict[str, Any]] | None = None
_trace_cache_error: str | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def _annotation_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("annotations", [])
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _write_annotations(data: Any) -> None:
    anns = data if isinstance(data, list) else _annotation_list(data)
    _write_json(API_FILES["/api/annotations"], {"annotations": anns})


def _load_samples() -> list[dict[str, Any]]:
    data = _read_json(API_FILES["/api/samples"], [])
    return data if isinstance(data, list) else []


def _trace_cache_stale(traces: list[dict[str, Any]]) -> bool:
    if not traces:
        return False
    sample = traces[0]
    return not isinstance(sample.get("stats"), dict) or not isinstance(
        sample.get("features"), dict
    )


def _load_store_traces() -> list[dict[str, Any]]:
    global _trace_cache, _trace_cache_error
    if _trace_cache is not None and not _trace_cache_stale(_trace_cache):
        return _trace_cache
    if _trace_cache is not None:
        _trace_cache = None
    try:
        from observability.instrument import load_env

        load_env()
        from analysis.helpers import langfuse_io

        if langfuse_io.is_configured():
            _trace_cache = langfuse_io.fetch_traces(limit=2000)
            return _trace_cache
    except Exception as exc:  # pragma: no cover - network path
        _trace_cache_error = str(exc)
    samples = _load_samples()
    _trace_cache = samples
    return _trace_cache


def _conversations_payload() -> list[dict[str, Any]]:
    samples = _load_samples()
    store = _load_store_traces()
    sample_ids = {str(s.get("trace_id")) for s in samples}
    return build_conversations(samples, store, sample_ids)


def _normalize_patterns(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("modes"), list):
        return [m for m in data["modes"] if isinstance(m, dict) and m.get("name")]
    return [{"name": k, **(v or {})} for k, v in data.items() if isinstance(v, dict)]


def _labels_dir() -> Path:
    return STATE_DIR / "labels"


def _read_labels() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    labels_dir = _labels_dir()
    if not labels_dir.exists():
        return out
    for path in sorted(labels_dir.glob("*.jsonl")):
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        out[path.stem] = rows
    return out


def _effective_labels(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return trace_id -> latest non-superseded label row."""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        tid = str(row.get("trace_id", ""))
        if row.get("superseded_by"):
            continue
        latest[tid] = row
    return latest


def _judges_dir() -> Path:
    return STATE_DIR / "judges"


def _trace_splits(mode: str) -> dict[str, str]:
    """Map trace_id -> train|dev|test for ``mode``."""
    splits = _read_json(STATE_DIR / "splits.json", default={})
    assignment = splits.get(mode, {})
    out: dict[str, str] = {}
    for split_name in ("train", "dev", "test"):
        for trace_id in assignment.get(split_name, []):
            out[str(trace_id)] = split_name
    return out


def _judges_payload() -> dict[str, Any]:
    """Return registered judges and per-trace predictions for the review UI."""
    judges_dir = _judges_dir()
    if not judges_dir.exists():
        return {"judges": [], "by_mode": {}}

    judges: list[dict[str, Any]] = []
    by_mode: dict[str, Any] = {}

    for path in sorted(judges_dir.glob("*.json")):
        if path.name.startswith("_history_"):
            continue
        record = _read_json(path, default=None)
        if not isinstance(record, dict) or not record.get("judge_id"):
            continue
        mode = str(record.get("mode", ""))
        judge_id = str(record["judge_id"])
        prompt_hash = record.get("prompt_hash")
        preds_raw = (record.get("predictions") or {}).get(prompt_hash, {})
        critiques_raw = (record.get("critiques") or {}).get(prompt_hash, {})
        pass_positive = record.get("label_convention") == "pass_positive"
        by_trace: dict[str, dict[str, Any]] = {}
        splits = _trace_splits(mode)
        for trace_id, raw_pred in preds_raw.items():
            pred = int(raw_pred)
            if not pass_positive:
                pred = 1 - pred
            by_trace[str(trace_id)] = {
                "pred": pred,
                "critique": critiques_raw.get(trace_id),
                "split": splits.get(str(trace_id)),
            }
        summary = {
            "judge_id": judge_id,
            "mode": mode,
            "status": record.get("status", "draft"),
            "model": record.get("model"),
            "version": record.get("version"),
            "created_at": record.get("created_at"),
            "scored_count": len(by_trace),
        }
        judges.append(summary)
        existing = by_mode.get(mode)
        if existing is None or int(record.get("version", -1)) >= int(existing.get("version", -1)):
            by_mode[mode] = {**summary, "by_trace": by_trace}

    judges.sort(key=lambda row: (row.get("mode", ""), row.get("version", 0)))
    return {"judges": judges, "by_mode": by_mode}


def _labels_payload() -> dict[str, Any]:
    patterns = _read_json(API_FILES["/api/patterns"], API_DEFAULTS["/api/patterns"])
    modes = _normalize_patterns(patterns)
    mode_names = [m["name"] for m in modes]
    by_mode = _read_labels()
    judgments: dict[str, dict[str, int | None]] = {}
    for mode, rows in by_mode.items():
        for tid, row in _effective_labels(rows).items():
            judgments.setdefault(tid, {})[mode] = int(row.get("label", 0))
    samples = _load_samples()
    sample_ids = [str(s.get("trace_id")) for s in samples]
    return {
        "modes": mode_names,
        "judgments": judgments,
        "sample_trace_ids": sample_ids,
    }


def _append_label(mode: str, record: dict[str, Any]) -> None:
    path = _labels_dir() / f"{mode}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _sync_label_score(
    trace_id: str, mode: str, label: int, comment: str | None = None
) -> None:
    try:
        from observability.instrument import load_env

        load_env()
        from analysis.helpers import langfuse_io

        if not langfuse_io.is_configured():
            return
        langfuse_io.write_label_score(trace_id, mode, label, comment=comment)
    except Exception:
        raise


def _sync_all_labels() -> int:
    written = 0
    for mode, rows in _read_labels().items():
        for tid, row in _effective_labels(rows).items():
            _sync_label_score(tid, mode, int(row.get("label", 0)), row.get("note"))
            written += 1
    return written


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({}, status=204)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            if not UI_PATH.exists():
                self._send_json({"error": "missing index.html"}, status=404)
                return
            body = UI_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/conversations":
            payload = {
                "conversations": _conversations_payload(),
                "store_error": _trace_cache_error,
            }
            self._send_json(payload)
            return

        if path == "/api/labels":
            self._send_json(_labels_payload())
            return

        if path == "/api/judges":
            self._send_json(_judges_payload())
            return

        if path in API_FILES:
            data = _read_json(API_FILES[path], API_DEFAULTS[path])
            if path == "/api/annotations":
                self._send_json(_annotation_list(data))
                return
            self._send_json(data)
            return

        self._send_json({"error": f"unknown path: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        data = self._read_body()
        if data is None:
            self._send_json({"error": "expected a JSON body"}, status=400)
            return

        if path == "/api/labels":
            mode = data.get("mode")
            trace_id = data.get("trace_id")
            label = data.get("label")
            if not mode or not trace_id or label not in (0, 1, "0", "1"):
                self._send_json({"error": "need mode, trace_id, label 0|1"}, status=400)
                return
            label_int = int(label)
            record = {
                "trace_id": str(trace_id),
                "label": label_int,
                "source": "human",
                "ts": _utcnow(),
                "note": data.get("note"),
                "label_id": f"{trace_id}#{mode}#{int(time.time())}",
            }
            try:
                _sync_label_score(str(trace_id), str(mode), label_int, record.get("note"))
            except Exception as exc:
                self._send_json({"error": f"Langfuse sync failed: {exc}"}, status=502)
                return
            _append_label(str(mode), record)
            self._send_json({"ok": True, "record": record})
            return

        if path == "/api/labels/sync":
            try:
                count = _sync_all_labels()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=502)
                return
            self._send_json({"ok": True, "langfuse_scores_written": count})
            return

        if path not in API_FILES:
            self._send_json({"error": f"cannot POST to {path}"}, status=404)
            return

        if path == "/api/annotations":
            _write_annotations(data)
            self._send_json({"ok": True, "count": len(_annotation_list(data))})
            return

        _write_json(API_FILES[path], data)
        count = len(data) if isinstance(data, list) else len(data) if isinstance(data, dict) else 0
        self._send_json({"ok": True, "count": count})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"HW4 review interface on {url}")
    print(f"state directory: {STATE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
