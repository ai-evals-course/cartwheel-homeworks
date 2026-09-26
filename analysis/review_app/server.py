"""File-backed review server for our HW4 review interface.

Adapted from the course's reference server (``analysis/server.py``) for our
own UI in ``analysis/review_app/ui/``. The backend contract is unchanged
(same routes, same on-disk shape under ``analysis/state/``) since the
reference implementation is already generic; what we adapted is the UI
itself (``ui/index.html``), tailored to the Cartwheel trace structure we
observed. The human annotates in the browser, the app auto-saves every
change here, and a coding-agent session can watch ``state/annotations.json``
on a poll loop (see the error-discovery skill's review-loop.md).

Langfuse is the canonical store for traces and accepted labels. The state
files are an inspectable local mirror and hold workflow state that does not
belong in the trace store.

API (unchanged from analysis/server.py):

    GET  /                    the HTML review app
    GET  /api/samples         current sample set (+ manifest of why picked)
    POST /api/samples         push a new or updated sample set
    GET  /api/annotations     current human annotations
    POST /api/annotations     save annotations (the app posts on every change)
    GET  /api/graph           the 2D projection of all traces for the map view
    GET  /api/patterns        the taxonomy as currently held
    POST /api/patterns        push the updated taxonomy
    GET  /api/suggestions     depth-scan suggestions awaiting accept/reject
    POST /api/suggestions     push suggestions

Run it:

    python analysis/review_app/server.py                # serve on :8020
    python analysis/review_app/server.py --port 8021
    python analysis/review_app/server.py --replay state/demo_annotations.json
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ANALYSIS_DIR = HERE.parent
STATE_DIR = ANALYSIS_DIR / "state"
UI_DIR = HERE / "ui"

# API path -> the state file that backs it. GET reads the file, POST overwrites
# it. Keeping this a plain table makes the whole contract inspectable and keeps
# the handler tiny.
API_FILES: dict[str, Path] = {
    "/api/samples": STATE_DIR / "samples.json",
    "/api/annotations": STATE_DIR / "annotations.json",
    "/api/graph": STATE_DIR / "graph.json",
    "/api/patterns": STATE_DIR / "patterns.json",
    "/api/suggestions": STATE_DIR / "suggestions.json",
}

# Default empty document per endpoint, so a fresh checkout serves valid JSON
# before the agent has written anything. samples/annotations/suggestions are
# lists; graph and patterns are objects.
API_DEFAULTS: dict[str, Any] = {
    "/api/samples": [],
    "/api/annotations": [],
    "/api/graph": {"nodes": [], "clusters": []},
    "/api/patterns": {},
    "/api/suggestions": [],
}


def _read_json(path: Path, default: Any) -> Any:
    """Return the parsed JSON at ``path``, or ``default`` if missing or bad.

    A half-written file (the app crashed mid-save) reads as the default rather
    than crashing the server; the next good POST repairs it.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` atomically (write temp, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


class ReviewHandler(BaseHTTPRequestHandler):
    """Serves the UI and the file-backed JSON API."""

    # Quiet by default; the agent narrates the session, not the access log.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        return

    # -- helpers ----------------------------------------------------------

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Local single-user tool; permissive CORS keeps a file:// or
        # different-port UI from tripping over the browser same-origin check.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": f"not found: {path.name}"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # -- routes -----------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802  (http.server naming)
        self._send_json({}, status=204)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return

        # Any other static asset the UI references (kept single-file by
        # default, but this lets an adapted UI ship a companion file).
        if path.startswith("/ui/"):
            asset = UI_DIR / path[len("/ui/"):]
            if asset.is_file() and UI_DIR in asset.resolve().parents:
                self._send_file(asset, _guess_type(asset))
                return

        if path in API_FILES:
            data = _read_json(API_FILES[path], API_DEFAULTS[path])
            self._send_json(data)
            return

        # Read-only: scenario_id -> {tuple, expected} from the HW3 scenario
        # files, precomputed once. Not part of the generic API_FILES table
        # since nothing ever POSTs to it.
        if path == "/api/scenario_lookup":
            self._send_json(_read_json(STATE_DIR / "scenario_lookup.json", {}))
            return

        # Structured labeling (Part D/E): one JSONL file per mode, keeping the
        # last non-superseded row per trace_id. Present as {trace_id: 0/1}.
        if path.startswith("/api/labels/"):
            mode = path[len("/api/labels/"):]
            self._send_json(_read_labels(mode))
            return

        self._send_json({"error": f"unknown path: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/labels/"):
            mode = path[len("/api/labels/"):]
            body = self._read_body()
            if not isinstance(body, dict) or "trace_id" not in body or "label" not in body:
                self._send_json({"error": "expected {trace_id, label}"}, status=400)
                return
            if body["label"] not in (0, 1):
                self._send_json({"error": "label must be 0 or 1"}, status=400)
                return
            _append_label(mode, str(body["trace_id"]), int(body["label"]))
            self._send_json({"ok": True})
            return
        if path not in API_FILES:
            self._send_json({"error": f"cannot POST to {path}"}, status=404)
            return
        data = self._read_body()
        if data is None:
            self._send_json({"error": "expected a JSON body"}, status=400)
            return
        synced = 0
        if path == "/api/annotations":
            try:
                synced = _sync_annotation_scores(data)
            except Exception as exc:  # pragma: no cover - network-only path
                # Preserve a resumable local copy, but tell the client that
                # the canonical write did not complete.
                _write_json(API_FILES[path], data)
                self._send_json(
                    {
                        "error": f"Langfuse score write failed: {exc}",
                        "cached_locally": True,
                    },
                    status=502,
                )
                return
        _write_json(API_FILES[path], data)
        result = {"ok": True, "count": _count(data)}
        if synced:
            result["langfuse_scores_written"] = synced
        self._send_json(result)


def _count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return 0


def _labels_jsonl_path(mode: str) -> Path:
    safe = "".join(c for c in mode if c.isalnum() or c in "_-")
    return STATE_DIR / "labels" / f"{safe}.jsonl"


def _read_labels(mode: str) -> dict[str, int]:
    """Latest label per trace_id for one mode, from the append-only JSONL."""
    path = _labels_jsonl_path(mode)
    if not path.exists():
        return {}
    latest: dict[str, int] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "trace_id" in row and "label" in row:
            latest[str(row["trace_id"])] = int(row["label"])
    return latest


def _append_label(mode: str, trace_id: str, label: int) -> None:
    """Append one (trace_id, label) row; later rows for the same id win on read."""
    path = _labels_jsonl_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "trace_id": trace_id,
        "label": label,
        "source": "human",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _annotation_list(data: Any) -> list[dict[str, Any]]:
    """Normalize the annotations payload (a bare list or ``{"annotations": []}``)."""
    if isinstance(data, dict):
        data = data.get("annotations", [])
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _sync_annotation_scores(data: Any) -> int:
    """Write labeled annotations to Langfuse scores when configured.

    Langfuse is canonical when configured, while ``annotations.json`` is the
    local mirror. The function does nothing when the ``LANGFUSE_*``
    environment is absent, so the
    offline demo, the ``--replay`` path, and the test suite never make a
    network call here. An annotation is written as a score only when it
    carries both a ``mode`` and a 0/1 ``label`` (a per-trace binary verdict);
    free-text-only notes are stored on disk but have nothing to score against.

    Return the number of scores written, or zero in offline mode. Propagate a
    Langfuse error so the server can report that the canonical write failed.
    """
    try:
        from analysis.helpers import langfuse_io
    except Exception:
        return 0
    if not langfuse_io.is_configured():
        return 0

    written = 0
    client = langfuse_io._client()
    for ann in _annotation_list(data):
        trace_id = ann.get("trace_id")
        mode = ann.get("mode")
        label = ann.get("label")
        if not trace_id or not mode or label not in (0, 1, "0", "1"):
            continue
        langfuse_io.write_label_score(
            trace_id=str(trace_id),
            mode=str(mode),
            label=int(label),
            comment=ann.get("note"),
            client=client,
        )
        written += 1
    return written


def _guess_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css",
        ".js": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")


# ---------------------------------------------------------------------------
# Demo replay: append canned annotations on a timer.
# ---------------------------------------------------------------------------


def _load_canned(replay_path: Path) -> list[Any]:
    """Read the canned annotations, accepting either on-disk shape.

    The committed demo file wraps its list as ``{"annotations": [...]}`` (it
    carries a little metadata alongside), while an ad-hoc file may be a bare
    list. Accept both so the demo fallback does not care which the course seed
    produced. Each annotation is given a stable ``id`` if it lacks one, so the
    UI's id-based merge and de-duplication work on replayed items.
    """
    raw = _read_json(replay_path, None)
    if isinstance(raw, dict):
        raw = raw.get("annotations", [])
    if not isinstance(raw, list):
        return []
    out: list[Any] = []
    for i, ann in enumerate(raw):
        if isinstance(ann, dict) and "id" not in ann:
            ann = {**ann, "id": f"replay-{i}"}
        out.append(ann)
    return out


def _replay_annotations(replay_path: Path, interval: float) -> None:
    """Append the canned annotations to state/annotations.json on a timer.

    Reads the whole canned list up front, then adds one annotation every
    ``interval`` seconds. The watcher and the UI both poll annotations.json, so
    grouping and the suggestion pipeline fire exactly as they would in a live
    session. Idempotent enough for a demo: it starts from an empty live file so
    a re-run replays from the top.
    """
    canned = _load_canned(replay_path)
    if not canned:
        print(f"[replay] nothing to replay from {replay_path}")
        return
    live_path = API_FILES["/api/annotations"]
    _write_json(live_path, [])
    print(f"[replay] replaying {len(canned)} annotations, one per {interval:g}s")
    accumulated: list[Any] = []
    for i, ann in enumerate(canned, start=1):
        time.sleep(interval)
        accumulated.append(ann)
        _write_json(live_path, accumulated)
        note = ann.get("note", "") if isinstance(ann, dict) else ""
        print(f"[replay] {i}/{len(canned)}: {note[:70]}")
    print("[replay] done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--replay",
        metavar="PATH",
        help="canned annotations file to replay on a timer (e.g. "
        "state/demo_annotations.json), for the demo fallback",
    )
    parser.add_argument(
        "--replay-interval",
        type=float,
        default=4.0,
        help="seconds between replayed annotations (default 4)",
    )
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if args.replay:
        replay_path = Path(args.replay)
        if not replay_path.is_absolute():
            replay_path = ANALYSIS_DIR / replay_path
        thread = threading.Thread(
            target=_replay_annotations,
            args=(replay_path, args.replay_interval),
            daemon=True,
        )
        thread.start()

    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"review interface on {url}")
    print(f"serving state from {STATE_DIR}")
    print("open the URL, read a trace, select the failing text, type a note.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
