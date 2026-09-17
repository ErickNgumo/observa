"""Local replay server for persisted canonical runs (installed-package mode).

A pip user does not need the repository, a Rust toolchain, or the workspace
CLI: this module serves the canonical replay frontend (bundled as package
data under ``observa/static``) plus the canonical ``/api/replay`` payload for
a persisted run directory created by :func:`observa.run(..., output=...)`.

The server is a thin presentation layer: the payload is built by the native
canonical loader and the frontend renders it. No economics are computed here.
"""

from __future__ import annotations

import errno
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import urlparse

from . import _observa
from .errors import coded


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
        suffix = ("." + relative.rsplit(".", 1)[-1]) if "." in relative else ""
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "application/javascript",
        }.get(suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_replay_payload(self):
        try:
            payload = _observa.replay_payload(self.server.run_dir)  # type: ignore[attr-defined]
        except Exception as exc:  # structured error surfaced to the user
            body = json.dumps({
                "error": str(exc),
                "code": getattr(exc, "code", None),
                "details": getattr(exc, "details", {}) or {},
            }).encode("utf-8")
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
        import sys

        sys.stderr.write("  [observa replay] %s\n" % (fmt % args))


class ReplayServer:
    """Handle for a non-blocking replay server.

    Attributes: ``url``, ``port``, ``run_dir``, ``is_running``.
    ``stop()`` is idempotent; the server can also be used as a context manager.
    """

    def __init__(self, httpd, thread, run_dir, port, url):
        self._httpd = httpd
        self._thread = thread
        self.run_dir = run_dir
        self.port = port
        self.url = url
        self._stopped = False

    @property
    def is_running(self) -> bool:
        return (not self._stopped) and self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        """Stops the server; safe to call more than once."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self._httpd.shutdown()
        finally:
            try:
                self._httpd.server_close()
            finally:
                if self._thread is not None and self._thread.is_alive():
                    self._thread.join(timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False

    def __repr__(self):  # pragma: no cover - display only
        state = "running" if self.is_running else "stopped"
        return "ReplayServer(url=%r, %s)" % (self.url, state)


def _bind(run_dir: str, port):
    """Binds the HTTP server; port=None asks the OS for a free port.

    Binding to port 0 directly avoids any probe-then-bind race (TOCTOU).
    """
    # Fail fast with stable codes before binding any port.
    import os

    run_path = os.path.abspath(str(run_dir))
    if not os.path.isfile(os.path.join(run_path, "run.json")):
        raise coded(
            FileNotFoundError("no persisted run found at %s (expected run.json)" % run_path),
            "REPLAY_RUN_NOT_FOUND",
            {"path": run_path},
        )
    if not os.path.isfile(os.path.join(run_path, "events.jsonl")):
        raise coded(
            ValueError("run artifacts at %s are incomplete: events.jsonl missing" % run_path),
            "REPLAY_ARTIFACTS_INVALID",
            {"path": run_path},
        )

    bind_port = 0 if port is None else int(port)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", bind_port), ReplayHandler)
    except OSError as exc:
        if port is not None and exc.errno == errno.EADDRINUSE:
            raise coded(
                OSError(
                    errno.EADDRINUSE,
                    "port %d is already in use; call observa.replay(..., port=None) "
                    "to choose a free port automatically, or pass another --port" % bind_port,
                ),
                "REPLAY_PORT_IN_USE",
                {"port": bind_port},
            ) from exc
        raise
    httpd.run_dir = run_path
    actual_port = httpd.server_address[1]
    return httpd, actual_port, run_path


def serve(run_dir: str, port=None, block: bool = True, open_browser: bool = False):
    """Starts the canonical replay server.

    * ``port=None`` (default) lets the OS choose a free port.
    * ``block=True`` (default) serves until interrupted and returns ``None``
      (the historical behavior of ``observa.replay(run_dir)``).
    * ``block=False`` returns a :class:`ReplayServer` immediately.
    """
    httpd, actual_port, run_path = _bind(run_dir, port)
    url = "http://127.0.0.1:%d" % actual_port
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if block:
        print()
        print("  Replaying canonical run: %s" % run_path)
        print("  Open %s in your browser" % url, flush=True)
        print("  Press Ctrl+C to stop")
        print()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
        return None

    thread = threading.Thread(target=httpd.serve_forever, name="observa-replay", daemon=True)
    thread.start()
    return ReplayServer(httpd, thread, run_path, actual_port, url)


__all__ = ["ReplayServer", "ReplayHandler", "serve"]
