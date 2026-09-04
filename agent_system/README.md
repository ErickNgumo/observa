# Observa Agent System

This directory is the project-specific orchestration layer for Observa's AI-assisted engineering workflow.

**DeepSeek Harness (`dsh`) is the actual agent runtime.** Observa owns the team model, tickets, routing, context rules, worktree policy, review gates, and run artifacts. DSH owns the model/tool execution.

## First task

Start with the read-only baseline audit:

```bash
python3 agent_system/orchestrator.py show OBS-0001
python3 agent_system/orchestrator.py run OBS-0001 --dry-run
```

For a real run, execute the orchestrator from a clean git checkout of Observa with DeepSeek Harness available.

## Key files

- `agents.yaml` — role definitions and routing.
- `orchestrator.py` — coordinator.
- `context/` — context assembly.
- `adapters/dsh.py` — bridge to DeepSeek Harness headless mode.
- `tickets/` — durable tasks and handoffs.
- `runs/` — local run artifacts; gitignored.
- `worktrees/` — isolated implementation worktrees; gitignored.
