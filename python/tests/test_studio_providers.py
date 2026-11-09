"""Provider routing and migrations; fake transports here never ship as agents."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from observa.studio.app import Studio, create_app
from observa.studio.codex import Codex
from observa.studio.migrations import MIGRATIONS, VERSION, _initial
from observa.studio.providers import PROVIDERS, Provider
from observa.studio.store import Store


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / "studio.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def legacy(self):
        db = sqlite3.connect(self.file)
        _initial(db)
        value = {"id": "c", "project": "p", "thread_id": "native", "settings": {"permissions": "automatic"}}
        db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", ("conversation", "c", "p", json.dumps(value), 10, 11))
        db.execute("INSERT INTO events(conversation,type,data) VALUES('c','notice','{}')")
        db.execute("INSERT INTO search VALUES('c','m','saved research')")
        db.execute("PRAGMA user_version=1")
        db.commit()
        db.close()

    def test_upgrade_preserves_history_identity_and_creates_consistent_backup(self):
        self.legacy()
        store = Store(self.root)
        try:
            self.assertEqual(store.require("conversation", "c"), {
                "id": "c", "project": "p", "thread_id": "native", "settings": {"permissions": "automatic"}, "provider": "codex"})
            self.assertEqual(store.search("saved"), ["c"])
            self.assertEqual(store.events("c", 0)[0]["seq"], 1)
            row = store.db.execute("SELECT created,updated FROM records").fetchone()
            self.assertEqual(tuple(row), (10, 11))
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], VERSION)
        finally:
            store.close()
        backup, = (self.root / "backups").glob("*.sqlite3")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertNotIn("provider", json.loads(db.execute("SELECT data FROM records").fetchone()[0]))
        Store(self.root).close()
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)

    def test_failure_rolls_back_data_and_version_and_can_retry(self):
        self.legacy()
        def fail(db):
            db.execute("DELETE FROM records")
            raise RuntimeError("interrupted migration")
        with patch.dict(MIGRATIONS, {2: fail}), self.assertRaisesRegex(RuntimeError, "interrupted"):
            Store(self.root)
        with closing(sqlite3.connect(self.file)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 1)
        Store(self.root).close()

    def test_newer_schema_is_refused_without_rewriting_database(self):
        self.legacy()
        with closing(sqlite3.connect(self.file)) as db:
            db.execute("PRAGMA user_version=999")
        before = self.file.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "requires schema 999"):
            Store(self.root)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse((self.root / "backups").exists())

    def test_empty_database_initializes_without_backup(self):
        store = Store(self.root)
        self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], VERSION)
        store.close()
        self.assertFalse((self.root / "backups").exists())


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.studio = Studio(Path(self.temp.name), "http://testserver")
        self.store = self.studio.store
        self.store.put("project", {"id": "p", "path": self.temp.name})
        self.store.put("conversation", {"id": "c", "project": "p", "provider": "other", "status": "idle"}, "p")

    async def asyncTearDown(self):
        await self.studio.close()
        self.temp.cleanup()

    def fake(self):
        agent = AsyncMock()
        agent.usable = True
        agent.options.return_value = {"models": [], "modes": [], "permissions": []}
        agent.probe.return_value = {"status": "sign_in_required"}
        self.agent = agent
        return Provider("other", "Other", lambda *a, **kw: agent,
                        lambda value, options: {"native": value["native"]},
                        lambda: "/example/other", ("stop", "resume"))

    async def test_dispatch_uses_native_adapter_not_codex_fields(self):
        with patch.dict(PROVIDERS, {"other": self.fake()}):
            await self.studio.execute_turn("c", "research")
            self.agent.start.assert_awaited_once()
            self.agent.turn.assert_awaited_once_with("research")
            await self.studio.execute_turn("c", "continue")
            self.assertEqual(self.agent.start.await_count, 1)
            result = await self.studio.options("c")
            self.assertEqual(result["provider"]["label"], "Other")
            result = await self.studio.configure("c", {"native": "custom"})
            self.assertEqual(result["settings"], {"native": "custom"})

    async def test_probe_closes_metadata_connection_and_preserves_conversation(self):
        before = self.store.require("conversation", "c")
        with patch.dict(PROVIDERS, {"other": self.fake()}):
            self.assertEqual(await self.studio.probe("c"), {"status": "sign_in_required"})
            self.agent.close.assert_awaited_once()
        self.assertEqual(self.store.require("conversation", "c"), before)

    async def test_unknown_provider_is_not_silently_codex_and_history_still_opens(self):
        with self.assertRaisesRegex(ValueError, "not supported"):
            self.studio.submit("c", "research")
        self.assertEqual(self.store.list("item", "c"), [])
        self.assertEqual(self.studio.snapshot("c")["provider"]["capabilities"], [])

    async def test_project_lock_includes_other_providers(self):
        with patch.dict(PROVIDERS, {"other": self.fake()}):
            self.store.put("conversation", {"id": "c2", "project": "p", "provider": "codex", "status": "running"}, "p")
            with self.assertRaisesRegex(ValueError, "active"):
                self.studio.submit("c", "research")
            self.assertEqual(self.store.list("item", "c"), [])

    async def test_native_probe_uses_account_not_inference_and_reports_signed_out(self):
        adapter = Codex(self.store, "c", self.studio.url, metadata_only=True)
        adapter.connect = AsyncMock()
        adapter.request = AsyncMock(return_value={"requiresOpenaiAuth": True, "account": None})
        with patch.object(Codex, "executable", return_value="/example/codex"):
            self.assertEqual((await adapter.probe())["status"], "sign_in_required")
        adapter.request.assert_awaited_once_with("account/read", {}, timeout=10)

    async def test_probe_timeout_reports_unknown_and_always_closes(self):
        with patch.dict(PROVIDERS, {"other": self.fake()}):
            self.agent.probe.side_effect = asyncio.TimeoutError
            self.assertEqual((await self.studio.probe("c"))["status"], "unknown")
            self.agent.close.assert_awaited_once()


class ProviderHttpTests(unittest.TestCase):
    def test_provider_selection_is_validated_and_settings_cannot_switch_session(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as root:
            app = create_app(Path(root), "http://testserver", "secret")
            with TestClient(app) as client:
                client.post("/api/auth", headers={"Authorization": "Bearer secret"})
                headers = {"X-Observa-Request": "1"}
                app.state.studio.store.put("project", {"id": "p", "path": root})
                self.assertEqual(client.post("/api/conversations", json={"project": "p", "provider": "fake"}, headers=headers).status_code, 400)
                value = client.post("/api/conversations", json={"project": "p"}, headers=headers).json()
                self.assertEqual(value["provider"], "codex")
                self.assertEqual(client.get("/api/state").json()["providers"][0]["id"], "codex")
                # No endpoint mutates the provider of an existing native thread.
                self.assertEqual(client.patch("/api/conversations/" + value["id"], json={"provider": "fake"}, headers=headers).status_code, 405)


if __name__ == "__main__":
    unittest.main()
