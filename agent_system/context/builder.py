#!/usr/bin/env python3
"""Build stable-prefix + variable-suffix contexts for DeepSeek cache reuse."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_DOCS = ROOT.parent / "docs" / "agents"
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


def domain_hint(ticket: str) -> str:
    lower = ticket.lower()
    for key in DOMAIN_DOCS:
        if key in lower:
            return key
    return "development"


def build(root: Path, role: str, ticket_text: str, previous: str = "") -> tuple[str, str]:
    docs_root = root.parent
    role_file = docs_root / "docs" / "agents" / f"{role.upper()}.md"
    stable = [
        "# OBSERVA STABLE AGENT CONTEXT",
        "This prefix is intentionally stable across tasks. Do not add ticket-specific content here.",
        "## Project",
        read(docs_root / "README.md"),
        "## Current State",
        read(docs_root / "docs/CURRENT_STATE.md"),
        "## Agent Role",
        read(role_file),
    ]
    for doc in DOMAIN_DOCS.get(domain_hint(ticket_text), []):
        path = docs_root / doc
        if path.exists():
            stable.append(f"## {doc}\n{read(path)}")

    variable = [
        "# OBSERVA TASK CONTEXT",
        "## Ticket",
        ticket_text,
    ]
    if previous:
        variable.extend(["## Previous Agent Output", previous])
    return "\n\n".join(stable), "\n\n".join(variable)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--ticket-file", required=True)
    parser.add_argument("--stable-out", required=True)
    parser.add_argument("--task-out", required=True)
    parser.add_argument("--previous-file")
    args = parser.parse_args()
    root = ROOT
    ticket_text = Path(args.ticket_file).read_text(encoding="utf-8")
    previous = Path(args.previous_file).read_text(encoding="utf-8") if args.previous_file else ""
    stable, task = build(root, args.role, ticket_text, previous)
    Path(args.stable_out).write_text(stable, encoding="utf-8")
    Path(args.task_out).write_text(task, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
