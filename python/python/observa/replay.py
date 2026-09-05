"""Local replay server for persisted canonical runs (installed-package mode).

A pip user does not need the repository, a Rust toolchain, or the workspace
CLI: this module serves the canonical replay frontend (bundled as package
data under ``observa/static``) plus the canonical ``/api/replay`` payload for
a persisted run directory created by :func:`observa.run(..., output=...)`.

The server is a thin presentation layer: the payload is built by the native
canonical loader and the frontend renders it. No economics are computed here.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import urlparse

from . import _observa


def _static_root():
    return resources.files("observa") / "static"


class ReplayHandler(BaseHTTPRequestHandler):
    """Serves static assets + the canonical /api/replay payload."""

    server_version = "ObservaReplay/0.1"

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/replay":
            self._serve_replay_payload()
            return
        if path in ("/", ""):
            relative = "index.html"
        elif path.startswith("/css/") or path.startswith("/js/") or path.startswith("/vendor/"):
            relative = path.lstrip("/")
        else:
            self.send_error(404, "Not found")
            return
        try:
            data = (_static_root() / relative).read_bytes()
        except (OSError, FileNotFoundError):
            self.send_error(404, "Asset not found (is the frontend bundled in this install?)")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "application/javascript",
        }.get(("." + relative.rsplit(".", 1)[-1]) if "." in relative else "", "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_replay_payload(self):
        try:
            payload = _observa.replay_payload(self.server.run_dir)  # type: ignore[attr-defined]
        except Exception as exc:  # structured error surfaced to the user
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep console quiet
        sys.stderr.write("  [observa replay] %s\n" % (fmt % args))


def serve(run_dir: str, port: int = 7878) -> None:
    """Blocks, serving the replay for ``run_dir`` until Ctrl+C."""
    server = ThreadingHTTPServer(("127.0.0.1", port), ReplayHandler)
    server.run_dir = run_dir  # type: ignore[attr-defined]
    print()
    print("  Replaying canonical run: %s" % run_dir)
    print("  Open http://localhost:%d in your browser" % port)
    print("  Press Ctrl+C to stop")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        server.server_close()
