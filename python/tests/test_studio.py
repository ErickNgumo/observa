"""Studio application boundaries, durable state and actual engine execution.

Run: python -m unittest discover -s python/tests -p test_studio.py -v
No provider credentials or model calls are needed for this regression suite.
Real Codex verification is a separate opt-in harness.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import observa
from observa.studio.app import Studio, create_app, validate_artifact
from observa.studio.codex import Codex
from observa.studio.controls import approval_choices, permission_options, validate_settings
from observa.studio.experiments import Experiments, scoped_file
from observa.studio.store import Store

STRATEGY = '''
class Once:
    def initialize(self, params=None):
        self.entered = False
    def on_bar(self, bar, portfolio, history):
        if not self.entered and len(history) == 3:
            self.entered = True
            return [{"direction": "buy", "size": 0.01, "reason": "Enter after three bars"}]
        if len(history) == 8 and portfolio["has_open_position"]:
            pos = portfolio["open_positions"][0]
            return [{"direction": "close", "size": pos["size"], "ticket": pos["position_id"],
                     "reason": "Close after eight bars"}]
        return []
    def teardown(self):
        pass
'''


class TemporaryStore:
    def setup_store(self):
        self.temp = tempfile.TemporaryDirectory(prefix="observa-studio-test-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "strategy.py").write_text(STRATEGY)
        self.store = Store(self.root / "data")
        self.store.put("project", {"id": "p", "name": "Research", "path": str(self.project)})
        self.store.put("conversation", {"id": "c", "project": "p", "title": "Research", "status": "idle"}, "p")

    def cleanup_store(self):
        self.store.close()
        self.temp.cleanup()


class StoreTests(TemporaryStore, unittest.TestCase):
    def setUp(self):
        self.setup_store()

    def tearDown(self):
        self.cleanup_store()

    def test_reopen_search_and_cursor(self):
        self.store.put("item", {"id": "m", "type": "agentMessage", "text": "momentum on EURUSD"}, "c")
        first = self.store.emit("c", "item", {"id": "m"})
        second = self.store.emit("c", "notice", {"message": "done"})
        self.store.close()
        self.store = Store(self.root / "data")
        self.assertEqual(self.store.search("momentum EURUSD"), ["c"])
        self.assertEqual([e["seq"] for e in self.store.events("c", first)], [second])
        self.assertEqual(self.store.events("other", 0), [])
        # Replacement doesn't leave stale search matches.
        self.store.put("item", {"id": "m", "type": "agentMessage", "text": "mean reversion"}, "c")
        self.assertEqual(self.store.search("momentum"), [])
        self.assertEqual(self.store.search('mean OR "'), [])

    def test_scope_rejects_traversal_and_symlinks(self):
        secret = self.root / "secret.py"
        secret.write_text("private")
        (self.project / "link.py").symlink_to(secret)
        for name in ("../secret.py", str(secret), "link.py"):
            with self.assertRaises(ValueError):
                scoped_file(self.project, name)

    def test_codex_projection_preserves_stream_and_completion(self):
        adapter = Codex(self.store, "c", "http://127.0.0.1:1234")
        adapter._notification("item/started", {"item": {"id": "message", "type": "agentMessage", "text": ""}})
        adapter._notification("item/agentMessage/delta", {"itemId": "message", "delta": "Real "})
        adapter._notification("item/agentMessage/delta", {"itemId": "message", "delta": "response"})
        self.assertEqual(self.store.require("item", "c:message")["text"], "Real response")
        adapter._notification("item/completed", {"item": {"id": "message", "type": "agentMessage", "text": "Real response"}})
        self.assertEqual(len(self.store.list("item", "c")), 1)
        adapter._notification("turn/started", {"turn": {"id": "turn1"}})
        adapter._notification("turn/completed", {"turn": {"id": "turn1", "status": "completed"}})
        self.assertEqual(self.store.require("conversation", "c")["status"], "idle")
        self.assertIsNone(self.store.require("conversation", "c")["turn_id"])

    def test_command_output_stream_starts_from_null_empty_or_missing_output(self):
        adapter = Codex(self.store, "c", "http://127.0.0.1:1234")
        for index, initial in enumerate(({}, {"aggregatedOutput": None}, {"aggregatedOutput": ""})):
            with self.subTest(initial=initial):
                identifier = f"command-{index}"
                adapter._notification("item/started", {"item": {
                    "id": identifier, "type": "commandExecution", **initial}})
                expected = ""
                for chunk in ("project\n", "", "x" * 60000, "\nfinished"):
                    adapter._notification("item/commandExecution/outputDelta", {
                        "itemId": identifier, "delta": chunk})
                    expected = (expected + chunk)[-60000:]
                    self.assertEqual(self.store.require("item", "c:" + identifier)["aggregatedOutput"], expected)


class SettingsTests(unittest.TestCase):
    def options(self, requirements=None):
        return {"models": [{"model": "supported", "defaultReasoningEffort": "medium",
                    "supportedReasoningEfforts": [{"reasoningEffort": "medium"}, {"reasoningEffort": "high"}]}],
                "modes": [{"mode": "default"}, {"mode": "plan"}],
                "permissions": permission_options(requirements or {})}

    def test_validates_native_model_effort_mode_and_explicit_full_access(self):
        options = self.options()
        settings = validate_settings({"model": "supported"}, options)
        self.assertEqual(settings, {"model": "supported", "effort": "medium", "mode": "default", "permissions": "cautious"})
        for changes in [{"model": "invented"}, {"effort": "invented"}, {"mode": "invented"},
                        {"permissions": "invented"}, {"permissions": "full-access"}, {"unknown": True}]:
            with self.assertRaises(ValueError):
                validate_settings({**settings, **changes}, options)
        self.assertEqual(validate_settings({**settings, "permissions": "full-access", "confirm_full_access": True}, options)["permissions"], "full-access")

    def test_managed_requirements_cannot_be_overridden(self):
        for requirements in [{"allowedApprovalPolicies": ["untrusted"]},
                             {"allowedApprovalsReviewers": ["user"]},
                             {"featureRequirements": {"guardian_approval": False}}]:
            with self.assertRaises(ValueError):
                validate_settings({"model": "supported", "permissions": "automatic"}, self.options(requirements))
        with self.assertRaises(ValueError):
            validate_settings({"model": "supported", "permissions": "full-access", "confirm_full_access": True},
                              self.options({"allowedSandboxModes": ["read-only", "workspace-write"]}))


class WorkerTests(TemporaryStore, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_store()
        self.manager = Experiments(self.store)

    async def asyncTearDown(self):
        await self.manager.close()
        self.cleanup_store()

    def prepare(self, **extra):
        return self.manager.prepare("c", {"strategy_file": "strategy.py", "config": {"interval": "15m"}, **extra})

    async def test_approval_snapshot_actual_engine_and_determinism(self):
        job = self.prepare()
        self.assertFalse((self.store.root / "experiments" / job["id"] / "output").exists())
        # Editing the working tree after review must not alter execution.
        (self.project / "strategy.py").write_text("raise RuntimeError('new unapproved source')")
        with self.assertRaises(ValueError):
            self.manager.decide(job["id"], True, "wrong snapshot")
        self.manager.decide(job["id"], True, job["snapshot_hash"])
        with self.assertRaises(ValueError):
            self.manager.decide(job["id"], True, job["snapshot_hash"])
        await self.manager.tasks[job["id"]]
        completed = self.store.require("experiment", job["id"])
        self.assertEqual(completed["status"], "completed", completed.get("error"))
        run = observa.inspect_run(completed["run_dir"])
        self.assertEqual(completed["metrics"], run.metrics)
        self.assertEqual(len(run.trades()), 1)
        self.assertEqual(run.rejections(), [])
        self.assertTrue(completed["validation"]["valid"])
        # Same approved bytes in a second sandbox invocation -> same economics.
        from observa.studio.experiments import sandbox_command
        directory = self.store.root / "experiments" / job["id"]
        repeat = directory / "repeat"
        repeat.mkdir()
        process = await asyncio.create_subprocess_exec(
            *sandbox_command(directory / "snapshot", repeat),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await process.communicate()
        self.assertEqual(process.returncode, 0, err.decode())
        self.assertEqual((repeat / "run/events.jsonl").read_bytes(),
                         (Path(completed["run_dir"]) / "events.jsonl").read_bytes())
        self.assertEqual(json.loads((repeat / "run/metrics.json").read_text()), completed["metrics"])

    async def test_decline_and_cancel_never_start_a_queued_worker(self):
        job = self.prepare()
        self.manager.decide(job["id"], False, job["snapshot_hash"])
        self.assertEqual(self.store.require("experiment", job["id"])["status"], "declined")
        other = self.prepare()
        self.manager.decide(other["id"], True, other["snapshot_hash"])
        await self.manager.cancel(other["id"])
        self.assertEqual(self.store.require("experiment", other["id"])["status"], "cancelled")
        self.assertFalse((self.store.root / "experiments" / other["id"] / "output/run").exists())

    async def test_tampered_snapshot_rejected(self):
        job = self.prepare()
        source = self.store.root / "experiments" / job["id"] / "snapshot/strategy.py"
        source.chmod(0o600)
        source.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "Snapshot changed"):
            self.manager.decide(job["id"], True, job["snapshot_hash"])

    async def test_worker_cannot_read_ungranted_files_or_use_network(self):
        secret = self.root / "secret"
        secret.write_text("secret")
        probe = f'''
from pathlib import Path
import socket
assert not Path({str(secret)!r}).exists(), "Host private file was exposed"
assert not Path({str(self.project)!r}).exists(), "Project was exposed"
assert not __import__("os").environ.get("OBSERVA_STUDIO_TOKEN")
sock = socket.socket()
try:
    sock.connect(("1.1.1.1", 443))
except OSError:
    pass
else:
    raise RuntimeError("Worker network was available")
finally:
    sock.close()
'''
        (self.project / "strategy.py").write_text(probe + STRATEGY)
        job = self.prepare()
        self.manager.decide(job["id"], True, job["snapshot_hash"])
        await self.manager.tasks[job["id"]]
        result = self.store.require("experiment", job["id"])
        self.assertEqual(result["status"], "completed", result.get("error"))

    async def test_validation_error_has_no_success_metrics(self):
        (self.project / "strategy.py").write_text(STRATEGY.replace('return []', 'return None'))
        job = self.prepare()
        self.manager.decide(job["id"], True, job["snapshot_hash"])
        await self.manager.tasks[job["id"]]
        result = self.store.require("experiment", job["id"])
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("metrics", result)
        self.assertFalse(result["validation"]["valid"])

    async def test_nested_strategy_imports_only_snapshotted_support_files(self):
        (self.project / "strategies").mkdir()
        (self.project / "helper.py").write_text("ENTRY_BAR = 3\n")
        source = "from helper import ENTRY_BAR\n" + STRATEGY.replace("len(history) == 3", "len(history) == ENTRY_BAR")
        (self.project / "strategies/strategy.py").write_text(source)
        job = self.prepare(strategy_file="strategies/strategy.py", support_files=["helper.py"])
        (self.project / "helper.py").write_text("raise RuntimeError('unapproved change')")
        self.manager.decide(job["id"], True, job["snapshot_hash"])
        await self.manager.tasks[job["id"]]
        result = self.store.require("experiment", job["id"])
        self.assertEqual(result["status"], "completed", result.get("error"))
        self.assertIn("helper.py", result["manifest"]["hashes"])

    async def test_cancel_running_worker(self):
        (self.project / "strategy.py").write_text("import time\ntime.sleep(120)\n" + STRATEGY)
        job = self.prepare()
        self.manager.decide(job["id"], True, job["snapshot_hash"])
        for _ in range(100):
            if job["id"] in self.manager.processes:
                break
            await asyncio.sleep(.01)
        self.assertIn(job["id"], self.manager.processes)
        process = self.manager.processes[job["id"]]
        await self.manager.cancel(job["id"])
        self.assertIsNotNone(process.returncode)
        self.assertEqual(self.store.require("experiment", job["id"])["status"], "cancelled")


class ProtocolTests(TemporaryStore, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_store()
        self.adapter = Codex(self.store, "c", "http://127.0.0.1:1234")
        self.sent = []

        async def capture(message):
            self.sent.append(message)
        self.adapter.send = capture

    async def asyncTearDown(self):
        self.cleanup_store()

    async def test_native_decisions_preserve_scope_and_offered_rules(self):
        rule = {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["python", "inspect.py"]}}
        for method, params, decision, scope, expected in [
            ("item/commandExecution/requestApproval", {}, "acceptForSession", "turn", {"decision": "acceptForSession"}),
            ("item/fileChange/requestApproval", {}, "acceptForSession", "turn", {"decision": "acceptForSession"}),
            ("item/permissions/requestApproval", {"permissions": {"network": {"enabled": True}}}, "accept", "session",
             {"permissions": {"network": {"enabled": True}}, "scope": "session"}),
            ("item/commandExecution/requestApproval", {"availableDecisions": [rule, "decline"]}, rule, "turn", {"decision": rule}),
        ]:
            await self.adapter._server_request({"id": 71, "method": method, "params": params})
            approval = self.store.list("approval", "c")[-1]
            await self.adapter.decide(approval["id"], decision=decision, scope=scope)
            self.assertEqual(self.sent[-1], {"id": 71, "result": expected})
        await self.adapter._server_request({"id": 72, "method": "item/commandExecution/requestApproval",
            "params": {"availableDecisions": ["accept", "decline"]}})
        approval = self.store.list("approval", "c")[-1]
        with self.assertRaises(ValueError):
            await self.adapter.decide(approval["id"], decision="acceptForSession")
        self.assertEqual(self.store.require("approval", approval["id"])["status"], "pending")

    async def test_turn_forwards_native_model_mode_and_permission_presets(self):
        from observa.studio.controls import PERMISSIONS
        calls = []
        async def request(method, params, **kwargs):
            calls.append((method, params))
            return {"turn": {"id": "turn"}}
        self.adapter.request = request
        for preset, spec in PERMISSIONS.items():
            self.adapter.save(thread_id="thread", settings={"model": "supported", "effort": "high", "mode": "plan", "permissions": preset})
            await self.adapter.turn("Investigate")
            method, params = calls[-1]
            self.assertEqual(method, "turn/start")
            self.assertEqual(params["approvalPolicy"], spec["policy"])
            self.assertEqual(params["approvalsReviewer"], spec["reviewer"])
            self.assertEqual(params["collaborationMode"], {"mode": "plan", "settings": {"model": "supported", "reasoning_effort": "high", "developer_instructions": None}})
            expected = {"workspace-write": "workspaceWrite", "read-only": "readOnly", "danger-full-access": "dangerFullAccess"}[spec["sandbox"]]
            self.assertEqual(params["sandboxPolicy"]["type"], expected)

    async def test_metadata_connection_close_preserves_running_conversation(self):
        self.adapter.save(status="running", turn_id="live")
        self.store.put("item", {"id": "tool", "type": "commandExecution", "status": "running"}, "c")
        metadata = Codex(self.store, "c", "http://localhost", metadata_only=True)
        await metadata.close()
        self.assertEqual(self.adapter.conv()["status"], "running")
        self.assertEqual(self.store.require("item", "tool")["status"], "running")

    async def test_mcp_permission_is_explicit_once_and_uses_native_response(self):
        await self.adapter._server_request({"id": 71, "method": "mcpServer/elicitation/request",
            "params": {"serverName": "observa_studio", "mode": "form", "requestedSchema": {"properties": {}}}})
        self.assertEqual(self.sent, [])
        approval = self.store.list("approval", "c")[0]
        await self.adapter.decide(approval["id"], True)
        self.assertEqual(self.sent, [{"id": 71, "result": {"action": "accept", "content": {}}}])
        with self.assertRaises(ValueError):
            await self.adapter.decide(approval["id"], True)

    async def test_resolved_provider_request_cannot_be_approved_later(self):
        await self.adapter._server_request({"id": "native-request", "method": "item/commandExecution/requestApproval",
            "params": {"command": "python strategy.py"}})
        approval = self.store.list("approval", "c")[0]
        self.adapter._notification("serverRequest/resolved", {"requestId": "native-request", "threadId": "native"})
        with self.assertRaises(ValueError):
            await self.adapter.decide(approval["id"], True)
        self.assertEqual(self.store.require("approval", approval["id"])["status"], "expired")

    async def test_disconnect_fails_pending_requests_and_never_retries(self):
        from types import SimpleNamespace
        reader = asyncio.StreamReader()
        self.adapter.process = SimpleNamespace(stdout=reader, returncode=0)
        future = asyncio.get_running_loop().create_future()
        self.adapter.pending[1] = future
        reader.feed_eof()
        await self.adapter._read()
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            await future
        self.assertEqual(self.store.require("conversation", "c")["status"], "interrupted")
        self.assertEqual(self.sent, [])

    async def test_null_command_output_does_not_disconnect_the_jsonrpc_reader(self):
        from types import SimpleNamespace
        reader = asyncio.StreamReader()
        self.adapter.process = SimpleNamespace(stdout=reader, returncode=0)
        consumed = asyncio.get_running_loop().create_future()
        self.adapter.pending[99] = consumed
        command = {"type": "commandExecution", "id": "exec-1", "command": "pwd",
                   "aggregatedOutput": None, "exitCode": None, "durationMs": None}
        messages = [
            {"method": "turn/started", "params": {"turn": {"id": "turn-1"}}},
            {"method": "item/started", "params": {"item": command}},
            {"method": "item/commandExecution/outputDelta", "params": {"itemId": "exec-1", "delta": "/project"}},
            {"method": "item/commandExecution/outputDelta", "params": {"itemId": "exec-1", "delta": "\n"}},
            {"method": "item/completed", "params": {"item": {
                **command, "aggregatedOutput": "/project\n", "exitCode": 0, "durationMs": 12}}},
            {"method": "item/agentMessage/delta", "params": {"itemId": "reply", "delta": "Ready for approval."}},
            {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}},
            {"id": 99, "result": {}},
        ]
        for message in messages:
            reader.feed_data((json.dumps(message) + "\n").encode())
        task = asyncio.create_task(self.adapter._read())
        try:
            await asyncio.wait_for(consumed, 1)
            self.assertFalse(task.done(), "The reader must remain connected after processing output")
            item = self.store.require("item", "c:exec-1")
            self.assertEqual(item["aggregatedOutput"], "/project\n")
            self.assertEqual(item["status"], "completed")
            self.assertEqual(item["exitCode"], 0)
            self.assertEqual(self.store.require("item", "c:reply")["text"], "Ready for approval.")
            self.assertEqual(self.adapter.conv()["status"], "idle")
            self.assertIsNone(self.adapter.conv().get("error"))
        finally:
            self.adapter.closing = True
            reader.feed_eof()
            await task

    async def test_unknown_server_request_is_not_silently_approved(self):
        await self.adapter._server_request({"id": 9, "method": "future/unrecognized", "params": {}})
        self.assertEqual(self.sent[0]["error"]["code"], -32601)

    async def test_interrupt_waits_for_completion_and_declines_pending_permissions(self):
        self.adapter.save(thread_id="native-thread")
        self.adapter._notification("turn/started", {"turn": {"id": "native-turn"}})
        await self.adapter._server_request({"id": 71, "method": "item/commandExecution/requestApproval",
            "params": {"command": "python strategy.py"}})
        cancellation = asyncio.create_task(self.adapter.cancel())
        await asyncio.sleep(0)
        request = self.sent[0]
        self.assertEqual(request["method"], "turn/interrupt")
        self.assertEqual(request["params"], {"threadId": "native-thread", "turnId": "native-turn"})
        self.assertEqual(self.adapter.conv()["status"], "stopping")
        self.adapter.pending[request["id"]].set_result({})
        # Acknowledging the interrupt is not evidence that the turn has stopped.
        for _ in range(10):
            if len(self.sent) == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(self.sent[1], {"id": 71, "result": {"decision": "decline"}})
        self.assertFalse(cancellation.done())
        self.adapter._notification("turn/completed", {"turn": {"id": "native-turn", "status": "interrupted"}})
        await asyncio.wait_for(cancellation, 1)
        self.assertIsNone(self.adapter.conv()["turn_id"])
        self.assertEqual(self.adapter.conv()["status"], "stopping")

    async def test_reader_failure_terminates_process_and_settles_running_items(self):
        self.adapter.save(thread_id="native", turn_id="turn", status="running")
        self.store.put("item", {"id": "c:tool", "type": "commandExecution", "status": "running"}, "c")
        self.store.put("item", {"id": "c:done", "type": "commandExecution", "status": "completed"}, "c")
        await self.adapter._server_request({"id": 71, "method": "item/commandExecution/requestApproval", "params": {}})
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", "import time; print('invalid JSON'); time.sleep(120)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        self.adapter.process = process
        self.adapter.owns_process_group = True
        self.adapter.reader = asyncio.create_task(self.adapter._read())
        try:
            await asyncio.wait_for(self.adapter.reader, 10)
            self.assertIsNotNone(process.returncode)
            self.assertTrue(self.adapter.closing)
            self.assertEqual(self.adapter.conv()["status"], "interrupted")
            self.assertIsNone(self.adapter.conv()["turn_id"])
            self.assertEqual(self.store.require("item", "c:tool")["status"], "interrupted")
            self.assertEqual(self.store.require("item", "c:done")["status"], "completed")
            self.assertEqual(self.store.list("approval", "c")[0]["status"], "expired")
        finally:
            await self.adapter.close()

    async def test_stop_after_interrupt_rpc_failure_terminates_process(self):
        self.adapter.save(thread_id="native", turn_id="turn", status="running")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(120)", start_new_session=True)
        self.adapter.process = process
        self.adapter.owns_process_group = True
        async def broken_request(method, params, timeout):
            self.assertEqual(method, "turn/interrupt")
            self.assertLessEqual(timeout, 5)
            raise RuntimeError("transport unavailable")
        self.adapter.request = broken_request
        try:
            await asyncio.wait_for(self.adapter.cancel(), 10)
            self.assertIsNotNone(process.returncode)
        finally:
            await self.adapter.close()


class LifecycleTests(TemporaryStore, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_store()
        self.store.close()
        self.studio = Studio(self.root / "data", "http://testserver")
        self.store = self.studio.store

    async def asyncTearDown(self):
        await self.studio.close()
        self.temp.cleanup()

    async def test_settings_persist_and_reject_changes_during_active_project_work(self):
        from unittest.mock import AsyncMock
        self.studio.options = AsyncMock(return_value=SettingsTests().options())
        self.store.put("conversation", {"id": "other", "project": "p", "status": "running"}, "p")
        with self.assertRaisesRegex(ValueError, "active project"):
            await self.studio.configure("c", {"model": "supported"})
        self.studio.options.assert_not_awaited()
        self.store.put("conversation", {"id": "other", "project": "p", "status": "idle"}, "p")
        adapter = Codex(self.store, "c", self.studio.url)
        adapter.save(thread_id="native")
        self.studio.agents["c"] = adapter
        result = await self.studio.configure("c", {"model": "supported", "mode": "plan", "permissions": "automatic"})
        self.assertEqual(result["thread_id"], "native")
        self.assertEqual(result["settings"]["mode"], "plan")
        self.assertTrue(adapter.closing)
        self.assertNotIn("c", self.studio.agents)
        self.assertEqual(self.store.events("c", 0)[-1]["data"]["settings"], result["settings"])
        self.store.close()
        self.store = self.studio.store = Store(self.root / "data")
        self.assertEqual(self.store.require("conversation", "c")["settings"], result["settings"])

    async def test_settings_recheck_activity_after_catalog_read(self):
        async def catalog(identifier):
            self.store.put("conversation", {"id": "other", "project": "p", "status": "running"}, "p")
            return SettingsTests().options()
        self.studio.options = catalog
        with self.assertRaisesRegex(ValueError, "active project"):
            await self.studio.configure("c", {"model": "supported"})
        self.assertNotIn("settings", self.store.require("conversation", "c"))

    async def test_stop_reaps_agent_with_dead_reader_and_keeps_resumable_thread(self):
        adapter = Codex(self.store, "c", "http://testserver")
        self.studio.agents["c"] = adapter
        adapter.save(thread_id="native-thread", turn_id="stale-turn", status="interrupted")
        self.store.put("item", {"id": "tool", "status": "running", "type": "commandExecution"}, "c")
        adapter.process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(120)", start_new_session=True)
        adapter.owns_process_group = True
        adapter.reader = asyncio.create_task(asyncio.sleep(0))
        await adapter.reader
        process = adapter.process
        await asyncio.wait_for(self.studio.cancel("c"), 10)
        self.assertIsNotNone(process.returncode)
        self.assertNotIn("c", self.studio.agents)
        self.assertEqual(adapter.conv()["status"], "idle")
        self.assertEqual(adapter.conv()["thread_id"], "native-thread")
        self.assertIsNone(adapter.conv()["turn_id"])
        self.assertEqual(self.store.require("item", "tool")["status"], "interrupted")

    async def test_stop_cancels_pending_connection_before_it_can_start_a_turn(self):
        adapter = Codex(self.store, "c", "http://testserver")
        self.studio.agents["c"] = adapter
        adapter.save(status="connecting")
        task = asyncio.create_task(asyncio.sleep(120))
        self.studio.turn_tasks["c"] = task
        await self.studio.cancel("c")
        self.assertTrue(task.cancelled())
        self.assertNotIn("c", self.studio.agents)
        self.assertEqual(adapter.conv()["status"], "idle")

    async def test_project_cannot_start_a_turn_until_stop_cleanup_finishes(self):
        self.store.put("conversation", {"id": "other", "project": "p", "status": "idle"}, "p")
        self.studio.stop_locks["c"] = asyncio.Lock()
        # Even if a provider's final event already reported idle, process cleanup
        # may still be pending. A second tab cannot start a competing turn.
        async with self.studio.stop_locks["c"]:
            with self.assertRaisesRegex(ValueError, "active Codex turn"):
                self.studio.submit("other", "Start another turn")
        self.assertEqual(self.store.list("item", "other"), [])


class HttpTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "data", "http://testserver", "test-secret")
        self.client = TestClient(self.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        self.assertEqual(self.client.post("/api/auth", headers={"Authorization": "Bearer test-secret"}).status_code, 200)

    def test_host_origin_auth_and_csrf(self):
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.assertEqual(self.client.get("/api/state", headers={"Host": "attacker.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth", headers={"Origin": "https://attacker.example"}).status_code, 403)
        self.login()
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        self.assertEqual(self.client.post("/api/projects", json={"name": "Bad CSRF"}).status_code, 403)
        self.assertEqual(self.client.post("/research/context", json={}).status_code, 401)
        response = self.client.post("/api/projects", json={"name": "Research"}, headers={"X-Observa-Request": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Path(response.json()["path"]).is_dir())
        self.assertIn("HttpOnly", self.client.post("/api/auth", headers={"Authorization": "Bearer test-secret"}).headers["set-cookie"])

    def test_restart_marks_unfinished_work_interrupted(self):
        store = self.app.state.studio.store
        store.put("project", {"id": "p"})
        store.put("conversation", {"id": "c", "project": "p", "status": "running", "thread_id": "native-thread"}, "p")
        store.put("experiment", {"id": "e", "conversation": "c", "status": "running"}, "c")
        store.put("approval", {"id": "a", "conversation": "c", "status": "pending"}, "c")
        store.put("item", {"id": "tool", "type": "commandExecution", "status": "running"}, "c")
        store.put("conversation", {"id": "old-error", "project": "p", "status": "interrupted"}, "p")
        store.put("item", {"id": "stale", "type": "commandExecution", "status": "running"}, "old-error")
        restarted = Studio(Path(self.temp.name) / "data", "http://testserver")
        try:
            self.assertEqual(restarted.store.require("conversation", "c")["status"], "interrupted")
            self.assertEqual(restarted.store.require("conversation", "c")["thread_id"], "native-thread")
            self.assertEqual(restarted.store.require("experiment", "e")["status"], "interrupted")
            self.assertEqual(restarted.store.require("approval", "a")["status"], "expired")
            self.assertEqual(restarted.store.require("item", "tool")["status"], "interrupted")
            self.assertEqual(restarted.store.require("item", "stale")["status"], "interrupted")
        finally:
            restarted.store.close()

    def test_stop_clears_stale_activity_even_without_a_live_adapter(self):
        self.login()
        store = self.app.state.studio.store
        store.put("conversation", {"id": "c", "project": "p", "status": "interrupted",
                  "thread_id": "native", "turn_id": "stale-turn", "error": "old error"}, "p")
        store.put("item", {"id": "tool", "type": "commandExecution", "status": "running"}, "c")
        store.put("approval", {"id": "a", "conversation": "c", "status": "pending"}, "c")
        store.put("experiment", {"id": "e", "conversation": "c", "status": "awaiting_approval"}, "c")
        response = self.client.post("/api/conversations/c/cancel", json={}, headers={"X-Observa-Request": "1"})
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.client.get("/api/conversations/c").json()
        self.assertEqual(snapshot["conversation"]["status"], "idle")
        self.assertIsNone(snapshot["conversation"]["turn_id"])
        self.assertIsNone(snapshot["conversation"]["error"])
        self.assertEqual(snapshot["conversation"]["thread_id"], "native")
        self.assertEqual(snapshot["items"][0]["status"], "interrupted")
        self.assertEqual(snapshot["approvals"][0]["status"], "expired")
        self.assertEqual(snapshot["experiments"][0]["status"], "cancelled")

    def test_research_credential_cannot_cross_conversations_or_approve(self):
        studio = self.app.state.studio
        studio.store.put("project", {"id": "p", "path": self.temp.name, "name": "Test"})
        studio.store.put("conversation", {"id": "c", "project": "p", "status": "running"}, "p")
        studio.store.put("experiment", {"id": "other", "conversation": "different", "status": "completed"}, "different")
        adapter = Codex(studio.store, "c", "http://testserver")
        studio.agents["c"] = adapter
        headers = {"Authorization": "Bearer " + adapter.token}
        self.assertEqual(self.client.post("/research/experiment", json={"id": "other"}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/auth", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/api/experiments/other/decision", json={"approved": True}, headers=headers).status_code, 401)

    def test_snapshot_download_is_exact_and_cannot_escape_manifest(self):
        self.login()
        studio = self.app.state.studio
        project = Path(self.temp.name) / "project"
        project.mkdir()
        (project / "strategy.py").write_text(STRATEGY)
        studio.store.put("project", {"id": "p", "path": str(project), "name": "Test"})
        studio.store.put("conversation", {"id": "c", "project": "p"}, "p")
        job = studio.experiments.prepare("c", {"strategy_file": "strategy.py"})
        (project / "strategy.py").write_text("changed")
        response = self.client.get(f"/api/experiments/{job['id']}/snapshot", params={"file": "strategy.py"})
        self.assertEqual(response.text, STRATEGY)
        self.assertTrue(response.headers["content-disposition"].startswith("attachment"))
        response = self.client.get(f"/api/experiments/{job['id']}/snapshot", params={"file": "../../studio.sqlite3"})
        self.assertEqual(response.status_code, 404)

    def test_artifact_rejects_active_content_and_bad_data(self):
        with self.assertRaises(ValueError):
            validate_artifact({"title": "Unsafe", "kind": "html", "html": "<script>bad()</script>"})
        with self.assertRaises(ValueError):
            validate_artifact({"title": "Bad", "kind": "plot", "mark": "line", "data": [{"x": 1, "y": "invented"}]})
        validate_artifact({"title": "Research", "kind": "plot", "mark": "scatter", "data": [{"x": 1, "y": 2}]})
        with self.assertRaises(ValueError):
            validate_artifact({"title": "Bad", "kind": "plot", "mark": "line", "data": [1]})
        with self.assertRaises(ValueError):
            validate_artifact({"title": "Bad", "kind": "markdown", "text": "note", "description": {"invalid": True}})
        cleaned = validate_artifact({"title": "Note", "kind": "markdown", "text": "hello", "created": 1})
        self.assertNotIn("created", cleaned)


if __name__ == "__main__":
    unittest.main()
