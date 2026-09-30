"""Review interface for Homework 4 open coding.

Standard library only, no dependencies. Serves one HTML page and a small JSON API.

    .venv/bin/python analysis/review_app/server.py          # http://localhost:8030
    .venv/bin/python analysis/review_app/server.py --port 8031

Built after reviewing traces in the standard viewer. Three things were slow there, and
each drove a decision here:

  1. Every span had to be expanded one at a time.
     -> everything is open by default; long tool results collapse with a summary line;
        there is an expand-all control; the 885 scaffolding spans hide behind a toggle.
  2. Annotation applied to a whole trace, not to the failing step.
     -> notes attach to selected text and appear in the margin, level with what they mark.
  3. The expected outcome was not visible next to the trace.
     -> it is pinned in its own column, with its ground-truth source and SPEC requirement.

State is written under analysis/state/ so it can be committed:
    annotations.json   free-text notes, each with its quote and location
    patterns.json      the failure mode taxonomy as it develops
    suggestions.json   agent-proposed annotations, pending human accept or dismiss
    sample_manifest.json  which conversations are in the review set, and why
    labels/            one file per final mode (Part E)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent
REPO = APP.parents[1]
STATE = REPO / "analysis" / "state"
STATE.mkdir(parents=True, exist_ok=True)
(STATE / "labels").mkdir(exist_ok=True)

FILES = {
    "annotations": STATE / "annotations.json",
    "patterns": STATE / "patterns.json",
    "suggestions": STATE / "suggestions.json",
    "sample_manifest": STATE / "sample_manifest.json",
    # Review completion is tracked separately from notes. A conversation can be
    # finished-with-comments, or clean, or not yet read: three different facts.
    "review_status": STATE / "review_status.json",
}
DEFAULTS = {"annotations": [], "patterns": {}, "suggestions": [],
            "sample_manifest": {}, "review_status": {}}


def load(name: str):
    p = FILES[name]
    if not p.exists():
        return DEFAULTS[name]
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return DEFAULTS[name]


def save(name: str, data) -> None:
    FILES[name].write_text(json.dumps(data, indent=1) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send((APP / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/records":
            self._send((APP / "records.json").read_bytes(), "application/json")
        elif path.startswith("/api/") and path[5:] in FILES:
            self._json(load(path[5:]))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        name = path[5:]
        if not path.startswith("/api/") or name not in FILES:
            return self._json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if name == "annotations" and isinstance(data, list):
            for a in data:
                a.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        save(name, data)
        self._json({"ok": True, "saved": name,
                    "count": len(data) if isinstance(data, (list, dict)) else None})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8030)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"review app on http://localhost:{args.port}")
    print(f"state in {STATE}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
