#!/usr/bin/env python3
"""DeepSeek Harness adapter for the Observa orchestrator."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--workdir', required=True)
    p.add_argument('--task-file', required=True)
    p.add_argument('--events-file', required=True)
    p.add_argument('--final-file', required=True)
    args = p.parse_args()

    workdir = Path(args.workdir).resolve()
    task_file = Path(args.task_file).resolve()
    task = (
        "Work on the Observa task described in the file "
        f"{task_file.relative_to(workdir)}. "
        "Read that task file first, then perform only the assigned work. "
        "Follow the repository AGENTS.md and the role instructions referenced by the ticket. "
        "Return a concise final report with files changed, checks run, results, and blockers."
    )

    bin_name = os.environ.get('OBSERVA_DSH_BIN', 'npx')
    if bin_name == 'npx':
        cmd = ['npx', '--yes', '@deepseek-ai/dsh', '--profile', 'headless', task]
    else:
        cmd = [bin_name, '--profile', 'headless', task]

    env = os.environ.copy()
    env.setdefault('DSH_CWD', str(workdir))

    proc = subprocess.run(
        cmd,
        cwd=workdir,
        text=True,
        capture_output=True,
        env=env,
    )

    Path(args.events_file).write_text(proc.stdout, encoding='utf-8')
    Path(args.final_file).write_text(proc.stderr if proc.stderr else proc.stdout, encoding='utf-8')
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
