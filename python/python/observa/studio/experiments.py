"""Approval-bound snapshots and isolated canonical execution."""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import sys

from .store import Store, encoded, new_id

TERMINAL = {"completed", "failed", "cancelled", "declined", "interrupted"}


def scoped_file(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Use a project-relative file path.")
    path = (root / candidate).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("File must stay inside the selected project.")
    return path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sandbox_command(snapshot: Path, output: Path) -> list[str]:
    """No host home, project, credentials, network, or writable runtime mounts."""
    if sys.platform != "linux" or not shutil.which("bwrap"):
        raise RuntimeError("Studio backtests require Linux and bubblewrap (bwrap).")
    import observa
    roots = [Path(p) for p in ("/usr", "/bin", "/lib", "/lib64") if Path(p).exists()]
    # Include the interpreter, its virtualenv and the installed package. This
    # also permits editable development installs without exposing the project.
    roots += [Path(sys.base_prefix).resolve(), Path(sys.prefix).absolute(),
              Path(observa.__file__).resolve().parent]
    if str(Path(sys.base_prefix).resolve()).startswith("/home/linuxbrew/.linuxbrew/"):
        roots.append(Path("/home/linuxbrew/.linuxbrew"))
    unique = []
    for root in sorted(set(roots), key=lambda p: len(str(p))):
        if not any(root.is_relative_to(parent) for parent in unique):
            unique.append(root)
    cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for root in unique:
        cmd += ["--ro-bind", str(root), str(root)]
    if Path("/etc/ld.so.cache").exists():
        cmd += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    cmd += ["--ro-bind", str(snapshot), str(snapshot),
            "--bind", str(output), str(output), "--chdir", str(snapshot),
            "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "HOME", "/tmp", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONUNBUFFERED", "1",
            "--setenv", "PYTHONPATH", str(Path(observa.__file__).resolve().parent.parent),
            str(Path(sys.executable).absolute()), "-m", "observa.studio.worker",
            str(snapshot / "manifest.json"), str(output)]
    return cmd


class Experiments:
    def __init__(self, store: Store):
        self.store = store
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    def update(self, job: dict, **changes) -> dict:
        job = self.store.put("experiment", {**job, **changes}, job["conversation"])
        self.store.emit(job["conversation"], "experiment", job)
        return job

    def prepare(self, conversation: str, request: dict) -> dict:
        import observa
        conv = self.store.require("conversation", conversation)
        project = self.store.require("project", conv["project"])
        root = Path(project["path"])
        source = scoped_file(root, request["strategy_file"])
        if source.suffix != ".py":
            raise ValueError("Strategy must be a Python file.")
        config = request.get("config") or {}
        allowed = {f.name for f in dataclasses.fields(observa.Config)} - {
            "dataset_source", "strategy_source"}
        if set(config) - allowed:
            raise ValueError("Unsupported configuration fields: " + ", ".join(set(config) - allowed))
        # Dataclass construction is side-effect free. Engine validates economics.
        full_config = dataclasses.asdict(observa.Config(**config))
        full_config.pop("strategy_source", None)
        full_config.pop("dataset_source", None)
        identifier = new_id()
        directory = self.store.root / "experiments" / identifier
        snapshot = directory / "snapshot"
        snapshot.mkdir(parents=True)
        try:
            files = list(dict.fromkeys([request["strategy_file"], *request.get("support_files", [])]))
            if len(files) > 100:
                raise ValueError("At most 100 explicit source/support files per experiment.")
            total = 0
            for name in files:
                src = scoped_file(root, name)
                if name in ("manifest.json", "dataset.csv") or Path(name).name.startswith("."):
                    raise ValueError("Reserved or hidden snapshot file.")
                total += src.stat().st_size
                if total > 20 * 1024**2:
                    raise ValueError("Source snapshot exceeds 20 MiB.")
                dest = snapshot / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
            dataset_name = request.get("dataset_file", "@sample")
            if dataset_name == "@sample":
                dataset = Path(observa.sample_data_path())
            elif dataset_name == "@demo":
                dataset = Path(observa.demo_data_path())
            else:
                dataset = scoped_file(root, dataset_name)
            if dataset.suffix != ".csv" or dataset.stat().st_size > 256 * 1024**2:
                raise ValueError("Select a CSV dataset no larger than 256 MiB.")
            shutil.copyfile(dataset, snapshot / "dataset.csv")
            files.append("dataset.csv")
            manifest = {
                "version": 1, "strategy_file": request["strategy_file"],
                "class_name": request.get("class_name"), "config": full_config,
                "dataset_origin": dataset_name,
                "hashes": {name: digest(snapshot / name) for name in sorted(files)},
                "environment": {
                    "python": sys.version, "platform": sys.platform,
                    "packages": sorted((d.metadata["Name"], d.version)
                                       for d in importlib.metadata.distributions()
                                       if d.metadata["Name"]),
                },
            }
            (snapshot / "manifest.json").write_text(encoded(manifest))
            snapshot_hash = digest(snapshot / "manifest.json")
            for path in snapshot.rglob("*"):
                if path.is_file():
                    path.chmod(0o400)
            return self.update({
                "id": identifier, "conversation": conversation, "project": project["id"],
                "status": "awaiting_approval", "manifest": manifest,
                "snapshot_hash": snapshot_hash, "title": request.get("title") or source.stem,
                "source_preview": (snapshot / request["strategy_file"]).read_text()[:60000],
                "source_truncated": (snapshot / request["strategy_file"]).stat().st_size > 60000,
            })
        except BaseException:
            shutil.rmtree(directory)
            raise

    def decide(self, identifier: str, approved: bool, snapshot_hash: str) -> dict:
        job = self.store.require("experiment", identifier)
        if job["status"] != "awaiting_approval":
            raise ValueError("This experiment has already been decided.")
        if snapshot_hash != job["snapshot_hash"]:
            raise ValueError("Approval does not match the displayed snapshot.")
        if not approved:
            return self.update(job, status="declined")
        snapshot = self.store.root / "experiments" / identifier / "snapshot"
        if digest(snapshot / "manifest.json") != snapshot_hash or any(
            digest(snapshot / name) != value for name, value in job["manifest"]["hashes"].items()
        ):
            raise ValueError("Snapshot changed; prepare a new experiment.")
        job = self.update(job, status="queued")
        self.tasks[identifier] = asyncio.create_task(self.run(identifier))
        return job

    async def run(self, identifier: str):
        job = self.store.require("experiment", identifier)
        directory = self.store.root / "experiments" / identifier
        output = directory / "output"
        try:
            output.mkdir()
            command = sandbox_command(directory / "snapshot", output)
            # Regular file avoids pipe deadlocks and bounds output via RLIMIT_FSIZE.
            with (output / "worker.log").open("wb") as log:
                process = await asyncio.create_subprocess_exec(
                    *command, stdout=log, stderr=log, start_new_session=True)
                self.processes[identifier] = process
                job = self.update(job, status="running")
                try:
                    await asyncio.wait_for(process.wait(), timeout=600)
                except asyncio.TimeoutError:
                    self._kill(process)
                    await process.wait()
                    raise RuntimeError("Backtest exceeded the 10 minute MVP execution limit.")
            if process.returncode:
                tail = (output / "worker.log").read_text(errors="replace")[-12000:]
                raise RuntimeError(tail or f"Worker exited with status {process.returncode}")
            from observa import inspect_run
            run = await asyncio.to_thread(inspect_run, output / "run")
            validation = json.loads((output / "validation.json").read_text())
            self.update(job, status="completed", metrics=run.metrics, run=run.meta,
                        validation=validation, run_dir=str(output / "run"))
        except asyncio.CancelledError:
            if identifier in self.processes:
                self._kill(self.processes[identifier])
                await self.processes[identifier].wait()
            self.update(job, status="cancelled")
        except Exception as exc:
            validation = None
            if (output / "validation.json").exists():
                try:
                    validation = json.loads((output / "validation.json").read_text())
                except ValueError:
                    pass
            self.update(job, status="failed", error=str(exc), validation=validation)
        finally:
            self.processes.pop(identifier, None)
            self.tasks.pop(identifier, None)

    @staticmethod
    def _kill(process):
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def cancel(self, identifier: str):
        job = self.store.require("experiment", identifier)
        task = self.tasks.get(identifier)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            current = self.store.require("experiment", identifier)
            if current["status"] not in TERMINAL:
                self.update(current, status="cancelled")
        elif job["status"] not in TERMINAL:
            self.update(job, status="cancelled")

    async def close(self):
        for identifier in list(self.tasks):
            await self.cancel(identifier)
