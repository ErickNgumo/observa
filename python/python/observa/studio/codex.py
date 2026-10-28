"""Codex App Server adapter. Transport and provider items stay at this boundary.

Supported protocol: codex-cli 0.154.x, stdio JSON-RPC. The app never implements
planning, command execution, context management, or provider authentication.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys

from .store import Store, encoded, new_id
from .controls import PERMISSIONS, approval_choices, permission_options

INSTRUCTIONS = """You are the research assistant in Observa Studio.
Use the observa_studio MCP tools to discover the canonical Observa contract.
Develop strategy files inside this project's working directory using your normal
file tools. Do not change the Observa engine or install the unrelated PyPI observa.
For every backtest use prepare_backtest. It snapshots code/data/config and waits
for the human's explicit Studio approval before validation and execution. Never
run backtests or import strategy code through shell tools to bypass this workflow.
Use @sample or @demo for bundled CSV data, or a project-relative CSV. Explicitly
list any required support files. Jobs use the Studio Python environment.
Only report financial numbers returned by canonical Observa run inspection.
Read rejections and include experiment identifiers. No fabricated progress,
metrics or evidence. State research assumptions. A failed job is not a result.
For strategies using indicators, emit their per-bar values through the documented
drawings series contract so the replay can show the same values the strategy saw.
You may publish typed research artifacts with publish_artifact; these are labeled
as agent-generated interpretations, not verified financial metrics.
When asked to inspect a previous result, use get_experiment.
"""


class Codex:
    def __init__(self, store: Store, conversation: str, base_url: str, on_exit=None, *, metadata_only=False):
        self.store = store
        self.conversation = conversation
        self.base_url = base_url
        self.token = secrets.token_urlsafe(32)
        self.process = None
        self.pending = {}
        self.approvals = {}
        self.reader = None
        self.stderr_task = None
        self.stderr_tail = ""
        self.serial = 0
        self.closing = False
        self.on_exit = on_exit
        self.turn_done = asyncio.Event()
        self.turn_done.set()
        self.owns_process_group = False
        self.metadata_only = metadata_only

    async def connect(self):
        binary = shutil.which(os.environ.get("OBSERVA_CODEX_BIN", "codex"))
        if not binary:
            raise RuntimeError("Codex CLI is not installed. Install Codex, then run `codex login`.")
        project = self.store.require("project", self.conv()["project"])
        self.process = await asyncio.create_subprocess_exec(
            binary, "app-server", "--listen", "stdio://",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=project["path"], limit=8 * 1024**2,
            start_new_session=True,
        )
        self.owns_process_group = True
        self.reader = asyncio.create_task(self._read())
        self.stderr_task = asyncio.create_task(self._stderr())
        await self.request("initialize", {
            "clientInfo": {"name": "observa_studio", "title": "Observa Studio", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        })
        await self.send({"method": "initialized", "params": {}})

    async def options(self):
        await self.connect()
        models, cursor = [], None
        while True:
            page = await self.request("model/list", {"cursor": cursor, "limit": 100})
            models.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        modes = await self.request("collaborationMode/list", {})
        requirements = await self.request("configRequirements/read", {})
        return {"models": models, "modes": modes["data"],
                "permissions": permission_options(requirements.get("requirements") or {})}

    def settings(self):
        return self.conv().get("settings") or {}

    def permissions(self):
        return PERMISSIONS[self.settings().get("permissions", "cautious")]

    async def start(self):
        await self.connect()
        project = self.store.require("project", self.conv()["project"])
        account = await self.request("account/read", {})
        if account.get("requiresOpenaiAuth") and not account.get("account"):
            raise RuntimeError("Codex is signed out. Run `codex login` in a terminal, then retry.")
        # Disable inherited MCP services for this research session. Do not change
        # the user's config file, authentication or ordinary Codex sessions.
        configuration = await self.request("config/read", {"includeLayers": False})
        inherited = (configuration.get("config") or {}).get("mcp_servers") or {}
        config = {f"mcp_servers.{name}.enabled": False for name in inherited if name != "observa_studio"}
        config.update({
            "mcp_servers.observa_studio": {
                "enabled": True,
                "required": True,
                "enabled_tools": ["get_project_context", "prepare_backtest", "get_experiment", "publish_artifact"],
                "command": sys.executable,
                "args": ["-m", "observa.studio.research_mcp"],
                "env": {
                    "OBSERVA_STUDIO_URL": self.base_url,
                    "OBSERVA_STUDIO_TOKEN": self.token,
                    "OBSERVA_STUDIO_CONVERSATION": self.conversation,
                },
                "tool_timeout_sec": 1800,
                # These application-owned tools are scoped to this conversation.
                # prepare_backtest has its own immutable, mandatory human gate.
                "default_tools_approval_mode": "approve",
            },
            "features.apps": False,
        })
        permission = self.permissions()
        if permission["reviewer"] == "auto_review":
            config["features.guardian_approval"] = True
        params = {
            "cwd": project["path"], "approvalPolicy": permission["policy"],
            "approvalsReviewer": permission["reviewer"], "sandbox": permission["sandbox"],
            "developerInstructions": INSTRUCTIONS, "config": config,
        }
        conv = self.conv()
        if self.settings().get("model"):
            params["model"] = self.settings()["model"]
        elif conv.get("model"):
            params["model"] = conv["model"]
        if conv.get("thread_id"):
            params["threadId"] = conv["thread_id"]
            response = await self.request("thread/resume", params, timeout=90)
        else:
            response = await self.request("thread/start", params, timeout=90)
        self.save(thread_id=response["thread"]["id"], model=response.get("model"),
                  status="idle", error=None)
        # Reconcile persisted provider items after a lost connection. Never
        # resubmit a turn; only copy evidence already returned by Codex.
        for turn in response["thread"].get("turns", []):
            for item in turn.get("items", []):
                self._notification("item/completed", {"item": item})
        return response

    def conv(self):
        return self.store.require("conversation", self.conversation)

    def save(self, **changes):
        value = self.store.put("conversation", {**self.conv(), **changes}, self.conv()["project"])
        self.store.emit(self.conversation, "conversation", value)
        return value

    async def send(self, value):
        if self.closing or not self.process or self.process.returncode is not None:
            raise RuntimeError("Codex connection is closed.")
        self.process.stdin.write((encoded(value) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params, timeout=45):
        self.serial += 1
        identifier = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self.send({"id": identifier, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Codex timed out during {method}. The request was not retried.") from exc
        finally:
            self.pending.pop(identifier, None)

    async def turn(self, text):
        conv = self.conv()
        settings, permission = self.settings(), self.permissions()
        self.turn_done.clear()
        self.save(status="running", error=None)
        try:
            params = {
                "threadId": conv["thread_id"],
                "input": [{"type": "text", "text": text}],
                "approvalPolicy": permission["policy"], "approvalsReviewer": permission["reviewer"],
                "sandboxPolicy": {
                    "type": "workspaceWrite",
                    "writableRoots": [self.store.require("project", conv["project"])["path"]],
                    "networkAccess": False, "excludeSlashTmp": True, "excludeTmpdirEnvVar": True,
                },
            }
            if permission["sandbox"] == "read-only":
                params["sandboxPolicy"] = {"type": "readOnly"}
            elif permission["sandbox"] == "danger-full-access":
                params["sandboxPolicy"] = {"type": "dangerFullAccess"}
            if settings:
                params.update(model=settings["model"], effort=settings["effort"], collaborationMode={
                    "mode": settings["mode"], "settings": {"model": settings["model"],
                    "reasoning_effort": settings["effort"], "developer_instructions": None}})
            response = await self.request("turn/start", params)
            # A very short turn may complete before its response reaches us.
            if self.conv()["status"] == "running":
                self.save(turn_id=response["turn"]["id"])
        except Exception as exc:
            self.save(status="error", error=str(exc))
            raise

    async def cancel(self):
        conv = self.conv()
        self.save(status="stopping")
        if self.closing or (self.reader and self.reader.done()) or not conv.get("turn_id"):
            await self.close()
            return
        try:
            await self.request("turn/interrupt", {
                "threadId": conv["thread_id"], "turnId": conv["turn_id"]}, timeout=5)
            for identifier in list(self.approvals):
                if identifier in self.approvals:
                    await self.decide(identifier, False)
            await asyncio.wait_for(self.turn_done.wait(), timeout=10)
        except (asyncio.TimeoutError, RuntimeError, OSError, ValueError):
            # An unresponsive/broken transport must not disable the stop action.
            await self.close()

    async def decide(self, identifier, approved=None, answers=None, *, decision=None, scope="turn"):
        approval = self.store.require("approval", identifier)
        if identifier not in self.approvals or approval["status"] != "pending":
            raise ValueError("This request is no longer pending.")
        method = approval["method"]
        params = approval["params"]
        choices = approval_choices(method, params)
        decision = decision if decision is not None else "accept" if approved else "decline"
        native_approval = method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval")
        if native_approval and not any(c["decision"] == decision and c.get("scope", "turn") == scope for c in choices):
            raise ValueError("This decision was not offered by Codex.")
        approved = decision in ("accept", "acceptForSession") if isinstance(decision, str) else True
        if method == "item/tool/requestUserInput":
            result = {"answers": {q["id"]: {"answers": [str((answers or {}).get(q["id"], ""))]}
                                  for q in params.get("questions", [])}}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": params.get("permissions", {}) if approved else {}, "scope": scope}
        elif method == "mcpServer/elicitation/request":
            if approved and (params.get("mode") != "form" or
                             params.get("requestedSchema", {}).get("properties")):
                raise ValueError("This MCP form is not supported; decline and continue in chat.")
            content = dict(answers or {})
            for key, schema in (params.get("requestedSchema", {}).get("properties", {})).items():
                if key in content and schema.get("type") == "boolean":
                    content[key] = content[key] == "true"
            result = {"action": "accept" if approved else "decline", "content": content if approved else None}
        else:
            result = {"decision": decision}
        await self.send({"id": self.approvals.pop(identifier), "result": result})
        approval = self.store.put("approval", {**approval, "status": "accepted" if approved else "declined", "decision": decision, "scope": scope},
                                  self.conversation)
        self.store.emit(self.conversation, "approval", approval)

    async def _read(self):
        failure = "Codex disconnected. Resume with a new message; the previous turn was not retried."
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" not in message:
                    future = self.pending.get(message.get("id"))
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(message["error"].get("message", str(message["error"]))))
                        else:
                            future.set_result(message.get("result", {}))
                    continue
                if "id" in message:
                    await self._server_request(message)
                else:
                    self._notification(message["method"], message.get("params", {}))
        except Exception as exc:
            failure = f"Codex connection failed: {exc}"
        finally:
            unexpected = not self.closing
            if unexpected:
                # No reader means no approvals or reliable turn control. Stop
                # our owned process before reporting this session interrupted.
                await self.close()
            self.turn_done.set()
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(RuntimeError(failure))
            for identifier in self.approvals:
                approval = self.store.require("approval", identifier)
                approval = self.store.put("approval", {**approval, "status": "expired"}, self.conversation)
                self.store.emit(self.conversation, "approval", approval)
            self.approvals.clear()
            if unexpected and not self.metadata_only:
                self.save(status="interrupted", turn_id=None, error=failure)
                if self.on_exit:
                    self.on_exit(self)

    async def _stderr(self):
        while chunk := await self.process.stderr.read(4096):
            self.stderr_tail = (self.stderr_tail + chunk.decode(errors="replace"))[-16000:]

    async def _server_request(self, message):
        method = message["method"]
        if method in (
            "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
            "item/permissions/requestApproval", "item/tool/requestUserInput",
            "mcpServer/elicitation/request",
        ):
            approval = self.store.put("approval", {
                "id": new_id(), "conversation": self.conversation, "method": method,
                "params": message.get("params", {}), "status": "pending",
                "choices": approval_choices(method, message.get("params", {})),
            }, self.conversation)
            self.approvals[approval["id"]] = message["id"]
            self.store.emit(self.conversation, "approval", approval)
        else:
            await self.send({"id": message["id"], "error": {
                "code": -32601, "message": "This server request is not supported by Observa Studio."}})
            self.store.emit(self.conversation, "notice", {"message": f"Unsupported Codex request: {method}"})

    def _notification(self, method, params):
        if method in ("item/started", "item/completed"):
            item = dict(params["item"])
            if item["type"] == "userMessage":
                return  # The submitted message is already durable before turn/start.
            item["provider_id"] = item["id"]
            item["id"] = self.conversation + ":" + item["id"]
            item["status"] = "completed" if method == "item/completed" else "running"
            old = self.store.get("item", item["id"]) or {}
            item = self.store.put("item", {**old, **item}, self.conversation)
            self.store.emit(self.conversation, "item", item)
        elif method in ("item/agentMessage/delta", "item/commandExecution/outputDelta"):
            identifier = self.conversation + ":" + params["itemId"]
            item = self.store.get("item", identifier) or {
                "id": identifier, "type": "agentMessage" if "agentMessage" in method else "commandExecution",
                "status": "running",
            }
            field = "text" if "agentMessage" in method else "aggregatedOutput"
            # Command items can start with aggregatedOutput: null. dict.get's
            # default only handles missing keys, not this valid pending state.
            item[field] = (item.get(field) or "") + params.get("delta", "")
            # Bound displayed command output; never truncate assistant research text.
            if field == "aggregatedOutput":
                item[field] = item[field][-60000:]
            item = self.store.put("item", item, self.conversation)
            self.store.emit(self.conversation, "item", item)
        elif method == "turn/started":
            self.turn_done.clear()
            self.save(status="running", turn_id=params["turn"]["id"])
        elif method == "turn/completed":
            self.turn_done.set()
            turn = params["turn"]
            error = turn.get("error")
            self.store.interrupt_activity(self.conversation)
            self.approvals.clear()
            self.save(status="stopping" if self.conv().get("status") == "stopping" else
                      "error" if error else "idle", turn_id=None,
                      error=error.get("message", str(error)) if error else None)
        elif method == "error":
            error = params.get("error", {})
            self.store.emit(self.conversation, "notice", {"message": error.get("message", str(error))})
        elif method == "serverRequest/resolved":
            for identifier, request_id in list(self.approvals.items()):
                if request_id == params["requestId"]:
                    self.approvals.pop(identifier)
                    approval = self.store.require("approval", identifier)
                    approval = self.store.put("approval", {**approval, "status": "expired"}, self.conversation)
                    self.store.emit(self.conversation, "approval", approval)

    async def close(self):
        self.closing = True
        process = self.process
        if process and process.returncode is None:
            try:
                if self.owns_process_group:
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                try:
                    if self.owns_process_group:
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        # Also reap same-group descendants if the parent exited first. Only
        # groups created by this adapter are ever signalled.
        if process and self.owns_process_group:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.owns_process_group = False
        for task in (self.reader, self.stderr_task):
            if task and task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)
        if not self.metadata_only:
            self.store.interrupt_activity(self.conversation)
        self.approvals.clear()
