"""Run from the repository root: python -m analysis.review_app.server."""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from analysis.helpers._state import read_json, state_root
from analysis.helpers.langfuse_io import _client
from analysis.helpers.normalization import _metadata
from analysis.review_app.data import ReviewStore, build_turn, group_sessions
from observability.instrument import load_env
from scenarios.export_langfuse import _jsonable

HERE = Path(__file__).resolve().parent


def load_live(timeout=30):
    client = _client()

    def read(operation, description, *args, **kwargs):
        for attempt in range(3):
            try:
                return operation(*args, **kwargs, request_options={
                    "timeout_in_seconds": timeout, "max_retries": 0,
                })
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Could not load {description} from Langfuse after 3 attempts "
                        f"({timeout}s timeout per request). Check LANGFUSE_HOST and "
                        "that Langfuse is running and reachable. Try a larger "
                        "--langfuse-timeout, or use --source with an existing full "
                        "trace export for offline review."
                    ) from exc
                print(f"Langfuse read failed for {description}; retrying ({attempt + 2}/3)…", flush=True)
                time.sleep(2 ** attempt)

    summaries, page = [], 1
    while True:
        print(f"Listing Langfuse traces, page {page}…", flush=True)
        batch = list(read(client.api.trace.list, f"trace page {page}", page=page, limit=100).data or [])
        summaries.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    print(f"Loading {len(summaries)} trace records from Langfuse…", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(lambda s: _jsonable(read(client.api.trace.get, "trace " + s.id, s.id)), summaries))
    return [r for r in records if _metadata(r).get("cartwheel.scenario_id")]


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, address, records, root, source, *, sync=None):
        super().__init__(address, ReviewHandler)
        self.records = {r["id"]: r for r in records}
        if len(self.records) != len(records):
            raise ValueError("Duplicate trace IDs in source")
        scenario_path = HERE.parents[1] / "scenarios" / "support_scenarios.jsonl"
        scenarios = [json.loads(line) for line in scenario_path.read_text().splitlines() if line.strip()] if scenario_path.exists() else []
        self.sessions = group_sessions(records, scenarios)
        self.source = source
        self.langfuse_host = os.environ.get("LANGFUSE_HOST", "").rstrip("/") if sync is None else ""
        self.namespace = ":".join(sorted({str(r.get("projectId", "offline")) for r in records})) or "empty"
        self.store = ReviewStore(root, set(self.records), **({"sync": sync} if sync else {}))
        self.legacy_notes = read_json(root / "annotations.json", [])
        if isinstance(self.legacy_notes, dict):
            self.legacy_notes = self.legacy_notes.get("annotations", [])
        for session in self.sessions:
            for trace in session["traces"]:
                obs = self.records[trace["id"]].get("observations") or []
                trace["tools"] = sorted({o["name"] for o in obs if o.get("type") == "TOOL"})


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, *_):
        pass

    def respond(self, value, status=200, content_type="application/json"):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            self.respond({"error": "Use the localhost review address"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed}:
            self.respond({"error": "Cross-origin access is not allowed"}, 403)
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        url = urlsplit(self.path)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/sampling.js": ("sampling.js", "text/javascript; charset=utf-8"),
                  "/review-controls.js": ("review-controls.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if url.path in static:
            filename, mime = static[url.path]
            self.respond((HERE / filename).read_bytes(), content_type=mime)
        elif url.path == "/api/catalog":
            self.respond({"sessions": self.server.sessions, "source": self.server.source,
                          "namespace": self.server.namespace,
                          "langfuse_host": self.server.langfuse_host,
                          "legacy_annotations": self.server.legacy_notes,
                          "sample_manifest": read_json(self.server.store.root / "sample_manifest.json", {})})
        elif url.path == "/api/state":
            self.respond(self.server.store.read())
        elif url.path == "/api/session":
            sid = parse_qs(url.query).get("id", [""])[0]
            session = next((s for s in self.server.sessions if s["id"] == sid), None)
            if not session:
                self.respond({"error": "Session not found"}, 404)
                return
            self.respond({"id": sid, "turns": [build_turn(self.server.records[t["id"]]) for t in session["traces"]]})
        elif url.path == "/favicon.ico":
            self.respond(b"", 204, "image/x-icon")
        else:
            self.respond({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.local_request():
            return
        if self.path != "/api/action":
            self.respond({"error": "Not found"}, 404)
            return
        if self.headers.get_content_type() != "application/json":
            self.respond({"error": "Expected application/json"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000:
                raise ValueError("Invalid request size")
            event = json.loads(self.rfile.read(size))
            if not isinstance(event, dict):
                raise ValueError("Expected a review action object")
            self.respond(self.server.store.apply(event))
        except (ValueError, TypeError) as exc:
            self.respond({"error": str(exc)}, 409 if "changed" in str(exc) else 400)
        except Exception:
            self.respond({"error": "Could not save review state; your browser draft is retained."}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--state-dir", type=Path, help="Override analysis state (use a temporary directory for testing)")
    parser.add_argument("--source", type=Path, help="Explicit offline JSON export; live Langfuse is the default")
    parser.add_argument("--langfuse-timeout", type=int, default=30, metavar="SECONDS",
                        help="Timeout per live trace request (default: 30; up to 3 attempts)")
    args = parser.parse_args()
    if args.langfuse_timeout <= 0:
        parser.error("--langfuse-timeout must be positive")
    load_env()
    if args.source:
        records = json.loads(args.source.read_text())
        if isinstance(records, dict):
            records = records.get("traces", records.get("data", []))
        source = "Offline export — Langfuse synchronization pending"
        def offline_sync(*_):
            raise RuntimeError("Offline mode")
        sync = offline_sync
    else:
        try:
            records = load_live(timeout=args.langfuse_timeout)
        except RuntimeError as exc:
            parser.exit(1, f"{exc}\n")
        source, sync = "Live Langfuse · " + os.environ.get("LANGFUSE_HOST", ""), None
    server = ReviewServer(("127.0.0.1", args.port), records, args.state_dir or state_root(), source, sync=sync)
    print(f"Review {len(records)} traces in {len(server.sessions)} conversations at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
