"""Linux application-menu entry point using the installed Observa runtime."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import urllib.request
import webbrowser

from .local_control import data_root, request


def validate_uri(value: str | None):
    # GIO normalizes the authority-only URI to include a root slash.
    if value not in (None, "observa://open", "observa://open/"):
        raise ValueError("This launch link is not supported. Open Observa Studio from your application menu.")


def open_studio(root: Path, *, timeout=25, browser=True) -> str:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    process = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = request(root, "status")
            url = state["url"]
            parsed = urlsplit(url)
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
                raise RuntimeError("Invalid local Studio address.")
            if state.get("stopping"):
                raise RuntimeError("Studio is shutting down. Reopen it after shutdown finishes.")
            # Ignore proxy environment settings for the private loopback service.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url + "/", timeout=2) as response:
                if response.status != 200:
                    raise RuntimeError("Studio's interface did not become ready.")
            launch = request(root, "open")["url"]
            if browser and not webbrowser.open(launch):
                raise RuntimeError("No browser could be opened. Set a default web browser and retry.")
            return launch
        except (FileNotFoundError, ConnectionRefusedError):
            if process is None:
                # No shell, activated environment or repository cwd is required.
                # The server uses the same interpreter as this installed launcher.
                log_path = root / "studio-startup.log"
                if log_path.exists() and log_path.stat().st_size > 1024 * 1024:
                    log_path.replace(root / "studio-startup.previous.log")
                fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "ab") as log:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "observa.studio.cli", "--no-browser", "--quiet-launch",
                         "--data-dir", str(root)], cwd=str(root), stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, start_new_session=True,
                    )
                # Retain/reap the child when used from an embedding process.
                # The desktop launcher itself may exit while Studio continues.
                threading.Thread(target=process.wait, daemon=True).start()
            elif process.poll() not in (None, 0):
                # Another simultaneous launcher may have won the lock. Give its
                # readiness socket a bounded chance to appear before reporting.
                if time.monotonic() > deadline - max(1, timeout - 3):
                    raise RuntimeError("Studio could not start. Check the installation, data directory and runtime permissions. "
                                       f"Local diagnostics: {root / 'studio-startup.log'}")
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Studio did not become ready in time. Reopen the application to retry.")


def desktop_quote(value: str) -> str:
    # Desktop Exec uses its own quoting grammar, not shell quoting.
    return '"' + value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'


def install_desktop() -> Path:
    directory = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "applications"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "org.observa.Studio.desktop"
    marker = "# Managed by Observa Studio"
    if path.exists() and not path.read_text().startswith(marker):
        raise RuntimeError("An unrelated desktop entry already uses Observa's filename.")
    path.write_text(
        marker + "\n[Desktop Entry]\nType=Application\nName=Observa Studio\n"
        "Comment=Local quantitative research\nTerminal=false\nIcon=utilities-system-monitor\n"
        "Categories=Science;\nMimeType=x-scheme-handler/observa;\n"
        f"Exec={desktop_quote(sys.executable)} -m observa.studio.launcher %u\n"
    )
    path.chmod(0o644)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(directory)], check=True, timeout=15)
    if shutil.which("xdg-mime"):
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).mkdir(
            parents=True, exist_ok=True, mode=0o700)
        subprocess.run(["xdg-mime", "default", path.name, "x-scheme-handler/observa"], check=True, timeout=15)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the local Observa Studio application")
    parser.add_argument("uri", nargs="?")
    parser.add_argument("--data-dir", type=Path, default=data_root())
    parser.add_argument("--install-desktop", action="store_true")
    args = parser.parse_args(argv)
    while True:
        try:
            validate_uri(args.uri)
            if args.install_desktop:
                print(install_desktop())
            else:
                open_studio(args.data_dir)
            return 0
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            message = str(exc)
            if shutil.which("zenity"):
                result = subprocess.run(["zenity", "--question", "--no-markup", "--title=Observa Studio",
                                        "--text=" + message, "--ok-label=Retry", "--cancel-label=Close"])
                if result.returncode == 0:
                    continue
            else:
                print("Observa Studio: " + message, file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
