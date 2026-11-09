"""Authenticated loopback application service; no public hosting mode."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import math
from pathlib import Path
import secrets
import shutil

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .providers import Agent, PROVIDERS, provider, create_agent
from .experiments import Experiments, TERMINAL, scoped_file
from .store import Store, encoded, new_id


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = ""


class ConversationInput(BaseModel):
    project: str
    title: str = Field(default="New research", max_length=200)
    provider: str = "codex"


class MessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=60000)


class DecisionInput(BaseModel):
    approved: bool
    snapshot_hash: str = ""
    answers: dict[str, str] | None = None


class AgentDecisionInput(BaseModel):
    approved: bool | None = None
    decision: str | dict | None = None
    scope: str = "turn"
    answers: dict[str, str] | None = None


def validate_artifact(value: dict) -> dict:
    if len(encoded(value)) > 2 * 1024**2:
        raise ValueError("Artifact exceeds 2 MiB.")
    if not isinstance(value.get("title"), str) or len(value["title"]) > 200:
        raise ValueError("Artifact requires a title up to 200 characters.")
    if not isinstance(value.get("description", ""), str) or len(value.get("description", "")) > 10000:
        raise ValueError("Artifact description must be text up to 10,000 characters.")
    references = value.get("experiment_ids", [])
    if not isinstance(references, list) or len(references) > 100 or not all(isinstance(r, str) for r in references):
        raise ValueError("experiment_ids must be a list of experiment identifiers.")
    kind = value.get("kind")
    if kind == "plot":
        if value.get("mark") not in ("line", "scatter", "bar", "heatmap"):
            raise ValueError("Unsupported plot mark.")
        points = value.get("data", [])
        if not isinstance(points, list) or len(points) > 10000:
            raise ValueError("Plots allow up to 10,000 points.")
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("Plot points must be objects with numeric coordinates.")
            for key in ("x", "y", *(["value"] if value["mark"] == "heatmap" else [])):
                if type(point.get(key)) not in (int, float) or not math.isfinite(point[key]):
                    raise ValueError("Plot coordinates must be finite numbers.")
        for label in ("x_label", "y_label"):
            if not isinstance(value.get(label, ""), str) or len(value.get(label, "")) > 200:
                raise ValueError("Plot labels must be text up to 200 characters.")
    elif kind == "table":
        columns, rows = value.get("columns"), value.get("rows")
        if not isinstance(columns, list) or not 1 <= len(columns) <= 30 or not all(isinstance(c, str) for c in columns):
            raise ValueError("Tables require 1–30 named columns.")
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("Tables allow up to 10,000 rows.")
        if any(not isinstance(row, list) or len(row) != len(columns) or
               any(cell is not None and not isinstance(cell, (str, int, float, bool)) for cell in row)
               for row in rows):
            raise ValueError("Invalid table cells.")
    elif kind == "markdown":
        if not isinstance(value.get("text"), str):
            raise ValueError("Markdown requires text.")
    else:
        raise ValueError("Unsupported artifact kind.")
    allowed = {"title", "description", "experiment_ids", "kind", "mark", "data",
               "x_label", "y_label", "columns", "rows", "text"}
    return {key: item for key, item in value.items() if key in allowed}


class Studio:
    def __init__(self, root: Path, url: str, token: str | None = None):
        self.store = Store(root)
        self.url = url.rstrip("/")
        self.token = token or secrets.token_urlsafe(32)
        self.experiments = Experiments(self.store)
        self.agents: dict[str, Agent] = {}
        self.turn_tasks: dict[str, asyncio.Task] = {}
        self.stop_locks: dict[str, asyncio.Lock] = {}
        self.shutting_down = False
        # Unfinished work is never automatically rerun after a restart.
        for conv in self.store.list("conversation"):
            if conv.get("status") in ("running", "connecting", "stopping") or conv.get("turn_id"):
                self.store.put("conversation", {**conv, "status": "interrupted", "turn_id": None,
                    "error": "Studio restarted. Send a message to resume your agent session."}, conv["project"])
            self.store.interrupt_activity(conv["id"])
        for job in self.store.list("experiment"):
            if job["status"] not in TERMINAL:
                self.experiments.update(job, status="interrupted",
                                        error="Studio restarted; prepare a new approval to run again.")
        for approval in self.store.list("approval"):
            if approval["status"] == "pending":
                self.store.put("approval", {**approval, "status": "expired"}, approval["conversation"])

    def snapshot(self, identifier: str):
        conv = self.store.require("conversation", identifier)
        return {
            "conversation": conv,
            "provider": provider(conv.get("provider")).describe() if conv.get("provider", "codex") in PROVIDERS else
                        {"id": conv.get("provider"), "label": conv.get("provider"), "capabilities": [], "installed": False},
            "items": self.store.list("item", identifier),
            "experiments": self.store.list("experiment", identifier),
            "approvals": self.store.list("approval", identifier),
            "artifacts": self.store.list("artifact", identifier),
            "cursor": self.store.db.execute("SELECT coalesce(max(seq),0) FROM events").fetchone()[0],
        }

    async def execute_turn(self, identifier: str, text: str):
        agent = self.agents.get(identifier)
        try:
            if not agent or not agent.usable:
                if agent:
                    await agent.close()
                agent = create_agent(self.store, identifier, self.url)
                self.agents[identifier] = agent
                await agent.start()
            await agent.turn(text)
        except Exception as exc:
            conv = self.store.require("conversation", identifier)
            conv = self.store.put("conversation", {**conv, "status": "error", "error": str(exc)}, conv["project"])
            self.store.emit(identifier, "conversation", conv)
            if agent:
                await agent.close()
                self.agents.pop(identifier, None)
        finally:
            self.turn_tasks.pop(identifier, None)

    def submit(self, identifier: str, text: str):
        conv = self.store.require("conversation", identifier)
        selected = provider(conv.get("provider"))
        if any(c["project"] == conv["project"] and (
               c.get("status") in ("connecting", "running", "stopping") or
               (c["id"] in self.stop_locks and self.stop_locks[c["id"]].locked()))
               for c in self.store.list("conversation")):
            raise ValueError(f"This project already has an active {selected.label} turn or another agent turn. Stop it or wait for it to finish.")
        item = self.store.put("item", {"id": new_id(), "type": "user", "text": text}, identifier)
        self.store.emit(identifier, "item", item)
        if conv["title"] == "New research":
            conv["title"] = text.strip()[:70]
        conv = self.store.put("conversation", {**conv, "status": "connecting", "error": None}, conv["project"])
        self.store.emit(identifier, "conversation", conv)
        self.turn_tasks[identifier] = asyncio.create_task(self.execute_turn(identifier, text))

    async def cancel(self, identifier):
        self.store.require("conversation", identifier)
        lock = self.stop_locks.setdefault(identifier, asyncio.Lock())
        async with lock:
            await self._cancel(identifier)

    async def _cancel(self, identifier):
        conv = self.store.require("conversation", identifier)
        conv = self.store.put("conversation", {**conv, "status": "stopping"}, conv["project"])
        self.store.emit(identifier, "conversation", conv)
        task = self.turn_tasks.get(identifier)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for job in self.store.list("experiment", identifier):
            if job["status"] not in TERMINAL:
                await self.experiments.cancel(job["id"])
        agent = self.agents.get(identifier)
        if agent:
            await agent.cancel()
            # A stopped conversation reconnects through native thread/resume.
            # Do not retain a process that may still own an unobserved command.
            await agent.close()
            self.agents.pop(identifier, None)
        self.store.interrupt_activity(identifier)
        conv = self.store.require("conversation", identifier)
        conv = self.store.put("conversation", {**conv, "status": "idle", "turn_id": None, "error": None}, conv["project"])
        self.store.emit(identifier, "conversation", conv)

    async def close(self):
        for task in list(self.turn_tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.turn_tasks.values()), return_exceptions=True)
        await self.experiments.close()
        await asyncio.gather(*(agent.close() for agent in self.agents.values()), return_exceptions=True)
        self.store.close()

    async def options(self, identifier):
        conv = self.store.require("conversation", identifier)
        catalog = create_agent(self.store, identifier, self.url, metadata_only=True)
        try:
            return {**await catalog.options(), "provider": provider(conv.get("provider")).describe()}
        finally:
            await catalog.close()

    async def probe(self, identifier):
        adapter = create_agent(self.store, identifier, self.url, metadata_only=True)
        try:
            return await asyncio.wait_for(adapter.probe(), 15)
        except asyncio.TimeoutError:
            return {"status": "unknown", "message": "The agent did not respond in time. Check its installation and retry."}
        except (RuntimeError, OSError):
            return {"status": "unknown", "message": "Could not connect to the native agent. Check its installation and authentication."}
        finally:
            await adapter.close()

    def require_idle(self, identifier):
        conv = self.store.require("conversation", identifier)
        if any(c["project"] == conv["project"] and (
               c.get("status") in ("connecting", "running", "stopping") or
               (c["id"] in self.stop_locks and self.stop_locks[c["id"]].locked()))
               for c in self.store.list("conversation")):
            raise ValueError("Stop the active project turn before changing agent settings.")
        return conv

    async def configure(self, identifier, value):
        initial = self.require_idle(identifier)
        settings = provider(initial.get("provider")).validate(value, await self.options(identifier))
        conv = self.require_idle(identifier)
        agent = self.agents.get(identifier)
        if agent:
            # Native thread/resume applies the new permission configuration.
            # Keep the project locked while closing its old idle connection.
            lock = self.stop_locks.setdefault(identifier, asyncio.Lock())
            async with lock:
                await agent.close()
                self.agents.pop(identifier, None)
        conv = self.store.put("conversation", {**conv, "settings": settings}, conv["project"])
        self.store.emit(identifier, "conversation", conv)
        return conv


def create_app(root: Path, url: str, token: str | None = None) -> FastAPI:
    studio = Studio(root, url, token)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await studio.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.studio = studio
    static = Path(__file__).resolve().parent.parent / "static"

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        expected_host = studio.url.split("://", 1)[1]
        if request.headers.get("host") != expected_host:
            return JSONResponse({"detail": "Invalid Host"}, 403)
        origin = request.headers.get("origin")
        if origin and origin != studio.url:
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, 403)
        path = request.url.path
        if path.startswith("/research/"):
            auth = request.headers.get("authorization", "").removeprefix("Bearer ")
            agent = next((a for a in studio.agents.values() if hmac.compare_digest(auth, a.token)), None)
            if not agent:
                return JSONResponse({"detail": "Invalid research credential"}, 401)
            request.state.conversation = agent.conversation
        elif path.startswith(("/api/", "/legacy/")) and path != "/api/auth":
            if not hmac.compare_digest(request.cookies.get("observa_session", ""), studio.token):
                return JSONResponse({"detail": "Open the local link printed by `observa studio`."}, 401)
            if request.method not in ("GET", "HEAD") and request.headers.get("x-observa-request") != "1":
                return JSONResponse({"detail": "Missing request header"}, 403)
        if request.headers.get("content-length") and int(request.headers["content-length"]) > 3 * 1024**2:
            return JSONResponse({"detail": "Request too large"}, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'" +
            (" 'unsafe-inline'" if path.startswith("/legacy/") else "") +
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        )
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, 404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, 400)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request, exc):
        return JSONResponse({"detail": str(exc)}, 400)

    @app.post("/api/auth")
    async def auth(request: Request):
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(bearer, studio.token):
            raise HTTPException(401, "Invalid launch token")
        response = JSONResponse({"ok": True})
        response.set_cookie("observa_session", studio.token, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/state")
    async def state(q: str = ""):
        conversations = studio.store.list("conversation")
        if q.strip():
            matched = set(studio.store.search(q))
            conversations = [c for c in conversations if c["id"] in matched or q.lower() in c["title"].lower()]
        return {"projects": studio.store.list("project"), "conversations": conversations,
                "providers": [p.describe() for p in PROVIDERS.values()],
                "codex_available": bool(PROVIDERS["codex"].executable()), "sandbox_available": bool(shutil.which("bwrap"))}

    @app.post("/api/projects")
    async def project(value: ProjectInput):
        if not value.name.strip():
            raise ValueError("Project name cannot be blank.")
        identifier = new_id()
        if value.path:
            path = Path(value.path).expanduser().resolve(strict=True)
            if not path.is_dir() or path == Path.home() or path == Path("/"):
                raise ValueError("Choose a dedicated project directory, not your home or filesystem root.")
            if studio.store.root.is_relative_to(path) or path.is_relative_to(studio.store.root):
                raise ValueError("Choose a directory separate from Studio's application storage.")
            for existing in studio.store.list("project"):
                existing_path = Path(existing["path"])
                if path.is_relative_to(existing_path) or existing_path.is_relative_to(path):
                    raise ValueError(f"This directory overlaps the existing project '{existing['name']}'.")
        else:
            path = studio.store.root.parent / "projects" / identifier
            path.mkdir(parents=True, mode=0o700)
        return studio.store.put("project", {"id": identifier, "name": value.name.strip(), "path": str(path)})

    @app.post("/api/conversations")
    async def conversation(value: ConversationInput):
        studio.store.require("project", value.project)
        selected = provider(value.provider)
        return studio.store.put("conversation", {
            "id": new_id(), "project": value.project, "title": value.title,
            "provider": selected.id, "status": "idle", "thread_id": None,
        }, value.project)

    @app.get("/api/conversations/{identifier}")
    async def detail(identifier: str):
        return studio.snapshot(identifier)

    @app.post("/api/conversations/{identifier}/messages")
    async def message(identifier: str, value: MessageInput):
        studio.submit(identifier, value.text)
        return {"ok": True}

    @app.post("/api/conversations/{identifier}/cancel")
    async def cancel(identifier: str):
        await studio.cancel(identifier)
        return {"ok": True}

    @app.get("/api/conversations/{identifier}/options")
    async def options(identifier: str):
        try:
            return await studio.options(identifier)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/conversations/{identifier}/probe")
    async def probe(identifier: str):
        return await studio.probe(identifier)

    @app.post("/api/conversations/{identifier}/settings")
    async def settings(identifier: str, value: dict):
        try:
            return await studio.configure(identifier, value)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/conversations/{identifier}/events")
    async def events(identifier: str, request: Request, after: int = 0):
        studio.store.require("conversation", identifier)
        cursor = max(after, int(request.headers.get("last-event-id", "0")))

        async def stream():
            nonlocal cursor
            ticks = 0
            while not studio.shutting_down and not await request.is_disconnected():
                for event in studio.store.events(identifier, cursor):
                    cursor = event["seq"]
                    yield f"id: {cursor}\ndata: {encoded(event)}\n\n"
                ticks += 1
                if ticks % 40 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.post("/api/approvals/{identifier}")
    async def approve(identifier: str, value: AgentDecisionInput):
        approval = studio.store.require("approval", identifier)
        agent = studio.agents.get(approval["conversation"])
        if not agent:
            raise ValueError("The agent is disconnected; this request has expired.")
        await agent.decide(identifier, value.approved, value.answers, decision=value.decision, scope=value.scope)
        return {"ok": True}

    @app.post("/api/experiments/{identifier}/decision")
    async def experiment_decision(identifier: str, value: DecisionInput):
        return studio.experiments.decide(identifier, value.approved, value.snapshot_hash)

    @app.post("/api/experiments/{identifier}/cancel")
    async def experiment_cancel(identifier: str):
        await studio.experiments.cancel(identifier)
        return {"ok": True}

    @app.get("/api/experiments/{identifier}/snapshot")
    async def snapshot_file(identifier: str, file: str):
        job = studio.store.require("experiment", identifier)
        if file not in job["manifest"]["hashes"]:
            raise HTTPException(404, "File is not part of this approved snapshot.")
        root = studio.store.root / "experiments" / identifier / "snapshot"
        path = scoped_file(root, file)
        return FileResponse(path, media_type="text/plain", filename=path.name)

    def result_path(identifier):
        job = studio.store.require("experiment", identifier)
        if job["status"] != "completed":
            raise ValueError("This experiment has no completed canonical result.")
        return studio.store.root / "experiments" / identifier / "output" / "run"

    @app.get("/api/experiments/{identifier}/replay")
    async def replay(identifier: str):
        from observa import _observa
        return await asyncio.to_thread(_observa.replay_payload, str(result_path(identifier)))

    @app.get("/api/experiments/{identifier}/trades")
    async def trades(identifier: str):
        from observa import inspect_run
        run = await asyncio.to_thread(inspect_run, result_path(identifier))
        return {"trades": run.trades(), "positions": run.positions(), "rejections": run.rejections()}

    @app.get("/legacy/{identifier}")
    async def legacy(identifier: str):
        result_path(identifier)
        html = (static / "index.html").read_text()
        # Relative assets resolve beneath this conversation-independent prefix.
        html = html.replace('src="/', 'src="/legacy-assets/').replace('href="/', 'href="/legacy-assets/')
        html = html.replace("</head>", f'<base href="/legacy-assets/"><meta name="studio-run" content="{identifier}"></head>')
        return HTMLResponse(html)

    @app.get("/legacy-assets/js/events.js")
    async def legacy_events():
        source = (static / "js/events.js").read_text()
        source = source.replace("'/api/replay'", "('/api/experiments/' + document.querySelector('meta[name=\"studio-run\"]').content + '/replay')")
        return HTMLResponse(source, media_type="application/javascript")

    @app.post("/research/{action}")
    async def research(action: str, request: Request):
        import observa
        identifier = request.state.conversation
        payload = await request.json()
        if action == "context":
            conv = studio.store.require("conversation", identifier)
            return {"project": studio.store.require("project", conv["project"]),
                    "contract": observa.agent_spec(),
                    "guide": Path(observa.agent_guide_path()).read_text(),
                    "example": Path(observa.agent_example_path()).read_text(),
                    "datasets": ["@sample", "@demo"],
                    "experiments": [{"id": j["id"], "title": j["title"], "status": j["status"]}
                                    for j in studio.store.list("experiment", identifier)]}
        if action == "prepare":
            if studio.store.require("conversation", identifier).get("status") != "running":
                raise ValueError("A running conversation is required to prepare an experiment.")
            return studio.experiments.prepare(identifier, payload)
        if action == "experiment":
            job = studio.store.require("experiment", payload["id"])
            if job["conversation"] != identifier:
                raise HTTPException(403, "Experiment belongs to another conversation.")
            result = {key: value for key, value in job.items() if key not in ("source_preview",)}
            if job["status"] == "completed":
                run = await asyncio.to_thread(observa.inspect_run, result_path(job["id"]))
                result.update(trades=run.trades(), rejections=run.rejections())
                if payload.get("position_id"):
                    result["position"] = run.position(payload["position_id"])
            return result
        if action == "artifact":
            artifact = validate_artifact(payload)
            for experiment_id in artifact.get("experiment_ids", []):
                if studio.store.require("experiment", experiment_id)["conversation"] != identifier:
                    raise ValueError("Artifact sources must belong to this conversation.")
            artifact = studio.store.put("artifact", {**artifact, "id": new_id(),
                "conversation": identifier, "provenance": "agent-generated"}, identifier)
            studio.store.emit(identifier, "artifact", artifact)
            return artifact
        raise HTTPException(404, "Unknown research operation")

    app.mount("/legacy-assets", StaticFiles(directory=static), name="legacy-assets")
    bundle = static / "studio"
    if bundle.exists():
        app.mount("/", StaticFiles(directory=bundle, html=True), name="studio")
    else:
        @app.get("/")
        async def missing_bundle():
            return HTMLResponse("Studio frontend is not built. Run npm ci && npm run build in studio/.", status_code=503)
    return app
