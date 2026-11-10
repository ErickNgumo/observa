"""Actual local service launch/reopen/shutdown; no model calls or user data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

import httpx

from observa.studio.app import create_app
from observa.studio.launcher import desktop_quote, open_studio, validate_uri
from observa.studio.local_control import control_path, request
from observa.studio.store import Store


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="observa-launch-")
        self.root = Path(self.temp.name) / "data"
        self.environment = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(Path(self.temp.name) / "run")})
        self.environment.start()

    def tearDown(self):
        try:
            request(self.root, "shutdown")
            self.wait_closed()
        except (OSError, RuntimeError):
            pass
        self.environment.stop()
        self.temp.cleanup()

    def wait_closed(self):
        deadline = time.monotonic() + 10
        while control_path(self.root).exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(control_path(self.root).exists())

    def connect(self, launch):
        parsed = urlsplit(launch)
        client = httpx.Client(base_url=f"{parsed.scheme}://{parsed.netloc}", trust_env=False)
        token = parse_qs(parsed.fragment)["token"][0]
        response = client.post("/api/auth", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(client.cookies["observa_session"], token)
        return client, token

    def test_reopen_single_use_tokens_quit_and_history_restart(self):
        launch = open_studio(self.root, browser=False)
        first = request(self.root, "status")
        reopened = open_studio(self.root, browser=False)
        self.assertEqual(request(self.root, "status")["pid"], first["pid"])
        self.assertNotEqual(launch, reopened)
        client, token = self.connect(launch)
        with closing(client):
            self.assertEqual(client.post("/api/auth", headers={"Authorization": "Bearer " + token}).status_code, 401)
            self.assertEqual(client.post("/api/quit").status_code, 403)
            headers = {"X-Observa-Request": "1"}
            project = client.post("/api/projects", json={"name": "Saved research"}, headers=headers).json()
            self.assertEqual(client.post("/api/quit", headers=headers).status_code, 200)
        self.wait_closed()
        resumed, _ = self.connect(open_studio(self.root, browser=False))
        with closing(resumed):
            self.assertEqual(resumed.get("/api/state").json()["projects"][0]["id"], project["id"])
        self.assertNotEqual(request(self.root, "status")["pid"], first["pid"])

    def test_concurrent_launches_use_one_service(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            launches = list(pool.map(lambda _: open_studio(self.root, browser=False), range(3)))
        self.assertEqual(len({urlsplit(url).netloc for url in launches}), 1)
        self.assertEqual(len(set(launches)), 3)

    def test_stale_owned_socket_recovered_without_killing_other_processes(self):
        path = control_path(self.root)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(path))
        launch = open_studio(self.root, browser=False)
        self.assertTrue(launch.startswith("http://127.0.0.1:"))

    def test_crashed_service_reopens_and_settles_unfinished_history(self):
        open_studio(self.root, browser=False)
        pid = request(self.root, "status")["pid"]
        store = Store(self.root)
        try:
            store.put("project", {"id": "p", "name": "Crash recovery", "path": str(self.root)})
            store.put("conversation", {"id": "c", "project": "p", "title": "Preserved research",
                      "status": "running", "thread_id": "preserved-native-session", "turn_id": "unfinished"}, "p")
            store.put("item", {"id": "i", "type": "commandExecution", "status": "running"}, "c")
        finally:
            store.close()
        os.kill(pid, signal.SIGKILL)  # Only the disposable service this test started.
        deadline = time.monotonic() + 5
        while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(Path(f"/proc/{pid}").exists())
        client, _ = self.connect(open_studio(self.root, browser=False))
        with closing(client):
            snapshot = client.get("/api/conversations/c").json()
            self.assertEqual(snapshot["conversation"]["status"], "interrupted")
            self.assertEqual(snapshot["conversation"]["thread_id"], "preserved-native-session")
            self.assertIsNone(snapshot["conversation"]["turn_id"])
            self.assertEqual(snapshot["items"][0]["status"], "interrupted")

    def test_occupied_explicit_port_fails_without_modifying_data(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            result = subprocess.run([sys.executable, "-m", "observa.studio.cli", "--no-browser",
                                     "--data-dir", str(self.root), "--port", str(occupied.getsockname()[1])],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Cannot bind Studio", result.stderr)
        self.assertFalse(self.root.exists())

    def test_insecure_runtime_directory_is_rejected(self):
        path = Path(os.environ["XDG_RUNTIME_DIR"])
        path.mkdir(mode=0o755)
        path.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "private"):
            open_studio(self.root, browser=False)
        path.chmod(0o700)

    def test_unexpected_control_file_is_not_overwritten(self):
        path = control_path(self.root)
        path.write_text("keep this file")
        with self.assertRaises((OSError, RuntimeError)):
            open_studio(self.root, browser=False, timeout=4)
        self.assertEqual(path.read_text(), "keep this file")
        # Remove only our own test sentinel so teardown doesn't try to connect.
        path.unlink()

    def test_deep_link_accepts_only_fixed_open_action(self):
        validate_uri(None)
        validate_uri("observa://open")
        validate_uri("observa://open/")
        for uri in ("observa://open//", "observa://open?command=rm", "observa://open#token=secret",
                    "observa://project/tmp", "https://example.com", "observa://open\n--install-desktop"):
            with self.assertRaises(ValueError):
                validate_uri(uri)
        self.assertEqual(desktop_quote('/path/a b%/python'), '"/path/a b%%/python"')


class LaunchTokenTests(unittest.TestCase):
    def test_expired_token_cannot_authenticate_or_act_as_session_cookie(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as root:
            app = create_app(Path(root), "http://testserver", "bootstrap")
            with TestClient(app) as client:
                studio = app.state.studio
                studio.launch_tokens["bootstrap"] = time.monotonic() - 1
                self.assertEqual(client.post("/api/auth", headers={"Authorization": "Bearer bootstrap"}).status_code, 401)
                client.cookies.set("observa_session", "bootstrap")
                self.assertEqual(client.get("/api/state").status_code, 401)
                for _ in range(40):
                    studio.issue_launch_token()
                self.assertEqual(len(studio.launch_tokens), 32)


if __name__ == "__main__":
    unittest.main()
