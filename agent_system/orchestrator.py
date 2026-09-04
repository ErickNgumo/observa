#!/usr/bin/env python3
"""Provider-agnostic coordinator for the Observa agent workflow."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "agent_system"
PROVIDERS = RUNTIME / "providers.yaml"
TICKETS = RUNTIME / "tickets"
RUNS = RUNTIME / "runs"
WORKTREES = RUNTIME / "worktrees"

ROLE_DOCS = {
    "research": ROOT / "docs/agents/RESEARCH.md",
    "architecture": ROOT / "docs/agents/ARCHITECTURE.md",
    "developer": ROOT / "docs/agents/DEVELOPER.md",
    "qa": ROOT / "docs/agents/QA.md",
    "finance": ROOT / "docs/agents/FINANCE.md",
    "release": ROOT / "docs/agents/RELEASE.md",
}

DOMAIN_DOCS = {
    "product": ["docs/PROJECT.md", "docs/MVP.md"],
    "architecture": ["docs/ARCHITECTURE.md", "docs/DECISIONS.md", "docs/DOMAIN_MODEL.md"],
    "strategy": ["docs/STRATEGY_API.md", "docs/DOMAIN_MODEL.md"],
    "execution": ["docs/domain/EXECUTION.md", "docs/domain/PORTFOLIO.md"],
    "portfolio": ["docs/domain/PORTFOLIO.md"],
    "metrics": ["docs/domain/METRICS.md"],
    "data": ["docs/domain/DATA.md"],
    "visualization": ["docs/domain/VISUALIZATION.md"],
    "testing": ["docs/engineering/TESTING.md"],
    "packaging": ["docs/engineering/PACKAGING.md"],
    "development": ["docs/engineering/DEVELOPMENT.md"],
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ticket_path(ticket_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", ticket_id)
    path = TICKETS / f"{safe}.md"
    if not path.exists():
        raise SystemExit(f"Ticket not found: {ticket_id}")
    return path


def get_front_matter(text: str) -> dict[str, str | bool]:
    if not text.startswith("---"):
        raise SystemExit("Ticket is missing YAML front matter")
    end = text.find("\n---", 3)
    if end == -1:
        raise SystemExit("Ticket front matter is not closed")
    result: dict[str, str | bool] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.lower() in {"true", "false"}:
            result[key.strip()] = value.lower() == "true"
        else:
            result[key.strip()] = value
    return result


def update_status(path: Path, status: str) -> None:
    text = read(path)
    text = re.sub(r"(?m)^status:\s*.+$", f"status: {status}", text, count=1)
    path.write_text(text, encoding="utf-8")


def route(meta: dict[str, str | bool]) -> list[str]:
    size = str(meta.get("size", "small"))
    base = {
        "small": ["developer", "qa"],
        "medium": ["architecture", "developer", "qa"],
        "large": ["research", "architecture", "developer", "qa"],
    }.get(size)
    if base is None:
        raise SystemExit(f"Invalid size: {size}")
    roles = list(base)
    if bool(meta.get("financial")) and "finance" not in roles:
        insert_at = roles.index("qa") if "qa" in roles else len(roles)
        roles.insert(insert_at, "finance")
    if bool(meta.get("release")):
        roles.append("release")
    return roles


def git(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)


def ensure_worktree(ticket_id: str) -> Path:
    branch = f"agent/{ticket_id.lower()}"
    target = WORKTREES / ticket_id
    if target.exists():
        return target
    result = git("worktree", "add", "-b", branch, str(target), "HEAD")
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Unable to create git worktree")
    return target


def context_for(ticket_id: str, role: str) -> str:
    ticket = ticket_path(ticket_id)
    parts = [
        "# OBSERVA AGENT CONTEXT",
        "You are operating under docs/engineering/AGENT_WORKFLOW.md.",
        f"Ticket: {ticket_id}",
        f"Role: {role}",
        "",
        "## Required project context",
        read(ROOT / "docs/README.md"),
        read(ROOT / "docs/CURRENT_STATE.md"),
        "## Ticket",
        read(ticket),
        "## Agent role instructions",
        read(ROLE_DOCS[role]),
    ]
    for doc in DOMAIN_DOCS.get(_domain_hint(read(ticket)), []):
        path = ROOT / doc
        if path.exists():
            parts.append(f"## {doc}\n{read(path)}")
    return "\n\n".join(parts)


def _domain_hint(ticket_text: str) -> str:
    lower = ticket_text.lower()
    for key in ["metrics", "execution", "portfolio", "strategy", "visualization", "packaging", "testing", "data", "architecture"]:
        if key in lower:
            return key
    return "development"


def provider_name() -> str:
    return os.environ.get("OBSERVA_AGENT_PROVIDER", "deepseek")


def invoke_agent(ticket_id: str, role: str, workdir: Path, previous: str = "") -> int:
    provider = provider_name()
    if provider != "deepseek":
        print(f"Unsupported provider: {provider}. Available provider: deepseek", file=sys.stderr)
        return 2

    run_dir = RUNS / ticket_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stable_file = run_dir / f"{role}.stable.md"
    task_file = run_dir / f"{role}.task.md"
    final_file = run_dir / f"{role}.final.md"
    events_file = run_dir / f"{role}.events.jsonl"
    usage_file = run_dir / f"{role}.usage.json"
    previous_file = run_dir / "previous.final.md"

    ticket_file = ticket_path(ticket_id)
    previous_file.write_text(previous, encoding="utf-8")
    builder = RUNTIME / "context" / "builder.py"
    build_cmd = [sys.executable, str(builder), "--role", role, "--ticket", ticket_id, "--ticket-file", str(ticket_file), "--stable-out", str(stable_file), "--task-out", str(task_file)]
    if previous:
        build_cmd.extend(["--previous-file", str(previous_file)])
    built = subprocess.run(build_cmd, text=True, capture_output=True)
    if built.returncode != 0:
        print(built.stderr.strip() or "Failed to build context", file=sys.stderr)
        return built.returncode

    adapter = RUNTIME / "adapters" / "dsh.py"
    cmd = [
        sys.executable, str(adapter),
        "--workdir", str(workdir),
        "--role", role,
        "--task-file", str(task_file),
        "--final-file", str(final_file),
        "--events-file", str(events_file),
    ]
    print(f"Context: {stable_file} + {task_file}")
    with events_file.with_suffix(".runner.log").open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, text=True, stdout=log, stderr=subprocess.STDOUT)
    if usage_file.exists():
        print(usage_file.read_text(encoding="utf-8").strip())
    return proc.returncode


def show(ticket_id: str) -> None:
    path = ticket_path(ticket_id)
    meta = get_front_matter(read(path))
    print(f"Ticket: {ticket_id}")
    print(f"Status: {meta.get('status')}")
    print(f"Size: {meta.get('size')}")
    print(f"Financial: {meta.get('financial')}")
    print(f"Release: {meta.get('release')}")
    print("Route:", " -> ".join(route(meta)))


def run(ticket_id: str, dry_run: bool) -> int:
    path = ticket_path(ticket_id)
    meta = get_front_matter(read(path))
    roles = route(meta)
    if dry_run:
        workdir = ROOT
        print(f"Dry-run workdir: {workdir}")
    else:
        workdir = ensure_worktree(ticket_id)
        print(f"Worktree: {workdir}")
    for role in roles:
        print(f"\n=== {role.upper()} ===")
        if dry_run:
            print("DRY RUN: context would be assembled and agent invoked here.")
            continue
        meta = get_front_matter(read(path))
        status_before = str(meta.get("status", "PROPOSED"))
        # Leadership explicitly starts a task in the appropriate state.
        # Research and architecture can advance that state; developer/QA/finance
        # may only work after the preceding gate has been cleared.
        if role == "research":
            update_status(path, "SPECIFIED")
        elif role == "architecture":
            if status_before not in {"SPECIFIED", "READY_FOR_REVIEW"}:
                print(f"Cannot run architecture from state {status_before}; leadership must authorize the review.", file=sys.stderr)
                return 2
        elif role == "developer":
            if status_before not in {"APPROVED", "CHANGES_REQUESTED"}:
                print(f"Cannot run developer from state {status_before}; ticket must be APPROVED or CHANGES_REQUESTED.", file=sys.stderr)
                return 2
            update_status(path, "IN_PROGRESS")
        elif role in {"qa", "finance"}:
            if status_before not in {"READY_FOR_QA", "IN_PROGRESS"}:
                print(f"Cannot run {role} from state {status_before}; ticket must be ready for verification.", file=sys.stderr)
                return 2
            update_status(path, "READY_FOR_QA")
        elif role == "release":
            if status_before != "ACCEPTED":
                print(f"Cannot run release from state {status_before}; ticket must be ACCEPTED.", file=sys.stderr)
                return 2
        previous = ""
        prior_final = RUNS / ticket_id / f"{role}.final.md"
        if prior_final.exists():
            previous = prior_final.read_text(encoding="utf-8")
        rc = invoke_agent(ticket_id, role, workdir, previous=previous)
        if rc != 0:
            update_status(path, "BLOCKED")
            print(f"{role} exited with status {rc}; ticket marked BLOCKED.")
            return rc
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Observa agent workflow coordinator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pshow = sub.add_parser("show")
    pshow.add_argument("ticket")
    prun = sub.add_parser("run")
    prun.add_argument("ticket")
    prun.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cmd == "show":
        show(args.ticket)
        return 0
    if args.cmd == "run":
        return run(args.ticket, args.dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
