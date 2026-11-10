"""Private per-user launcher control. Never expose this socket to the website."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct


def data_root() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "observa/studio"


def control_path(root: Path) -> Path:
    base = Path(os.environ["XDG_RUNTIME_DIR"]) if os.environ.get("XDG_RUNTIME_DIR") else root / "runtime"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = base.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Studio's runtime directory must be private and owned by your user.")
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]
    path = base / f"observa-{key}.sock"
    if len(os.fsencode(path)) >= 104:
        raise RuntimeError("Studio runtime path is too long; use a shorter private XDG_RUNTIME_DIR.")
    return path


def request(root: Path, action: str) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(control_path(root)))
        _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise RuntimeError("Studio control peer is not owned by your user.")
        client.sendall(json.dumps({"action": action}).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n") and len(data) < 4096:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        value = json.loads(data)
        if "error" in value:
            raise RuntimeError(value["error"])
        return value


async def serve(root: Path, studio, stop):
    """Caller must hold the data-directory instance lock until server closes."""
    path = control_path(root)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Refusing to replace an unexpected Studio control file.")
        path.unlink()  # Stale owned socket, protected by the acquired instance lock.

    async def handle(reader, writer):
        try:
            peer = writer.get_extra_info("socket")
            _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                return
            command = json.loads(await asyncio.wait_for(reader.readline(), 2))
            action = command.get("action")
            if action == "open" and not studio.shutting_down:
                value = {"url": studio.url + "/#token=" + studio.issue_launch_token(), "pid": os.getpid()}
            elif action == "status":
                value = {"url": studio.url, "pid": os.getpid(), "stopping": studio.shutting_down}
            elif action == "shutdown":
                value = {"ok": True}
                stop()
            else:
                value = {"error": "Unsupported Studio control action."}
            writer.write(json.dumps(value).encode() + b"\n")
            await writer.drain()
        except (ValueError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    server = await asyncio.start_unix_server(handle, path=str(path), limit=4096)
    path.chmod(0o600)
    return server, path
