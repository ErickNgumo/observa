from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import secrets
import socket
import sys
import webbrowser


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="observa studio", description="Local Observa Studio (Linux + Codex)")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; default chooses an available port")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get(
        "XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "observa/studio")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Studio currently supports Linux only.")
    try:
        import uvicorn
        from .app import create_app
    except ImportError as exc:
        print(f"Studio dependencies are missing: {exc}\n"
              "Install this repository's wheel with its [studio] extra. "
              "Do not install the unrelated PyPI observa project.", file=sys.stderr)
        return 2
    # Retain the bound socket so choosing a free port has no race.
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError as exc:
        print(f"Cannot bind Studio: {exc}", file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    os.umask(0o077)
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (args.data_dir / "studio.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Studio is already running with this data directory.", file=sys.stderr)
        lock.close()
        sock.close()
        return 2
    app = create_app(args.data_dir, url, token)
    launch = url + "/#token=" + token
    print(f"Observa Studio\nLocal data: {args.data_dir}\nOpen: {launch}", flush=True)
    if not args.no_browser:
        webbrowser.open(launch)

    class LocalServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            # End long-lived SSE responses before Uvicorn waits for connections;
            # lifespan shutdown can then stop agent/worker subprocesses cleanly.
            app.state.studio.shutting_down = True
            super().handle_exit(sig, frame)

    try:
        LocalServer(uvicorn.Config(app, log_level="warning", access_log=False,
                                  timeout_graceful_shutdown=10)).run(sockets=[sock])
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGINT after lifespan shutdown. Ctrl-C is a normal
        # local-app exit, not a failed research session with a traceback.
        pass
    finally:
        sock.close()
        lock.close()
    return 0
