# DeepSeek Harness Integration

DeepSeek Harness (`dsh`) is the actual coding-agent runtime for Observa. The `agent_system/` directory is the Observa-specific orchestration layer: tickets, routing, context assembly, worktree policy, and handoffs.

## Install/run the harness

From the Observa repository root:

```bash
npx @deepseek-ai/dsh web
```

For unattended tasks, the official headless profile is used:

```bash
npx @deepseek-ai/dsh --profile headless "...task..."
```

DeepSeek Harness is currently in developer preview and may introduce compatibility-breaking changes. Keep the harness version controlled/known when possible.

## How Observa uses it

```text
Observa ticket
    ↓
agent_system/orchestrator.py
    ↓
role-specific context + ticket task file
    ↓
DeepSeek Harness headless profile
    ↓
isolated git worktree
    ↓
agent result
    ↓
QA / Finance / Architecture gates
```

The task passed to `dsh` is intentionally small. The agent reads `AGENTS.md` and the ticket/context files from the workspace. This avoids putting the entire repository knowledge base into every launcher command.

## Credentials

Use a gitignored `.env` or environment variables for `DEEPSEEK_API_KEY` and, when necessary, `DEEPSEEK_BASE_URL`. Never put keys in tickets, documentation, commits, or prompts.

## Cache-aware context

DeepSeek's API automatically caches matching input prefixes. Keep stable instructions and repeated project context stable, and put changing task-specific material after them. Do not assume every filesystem/tool read is cached: inspect actual usage telemetry where available.

## Recommended local layout

```text
Observa/
├── AGENTS.md
├── docs/
├── agent_system/
├── crates/ ...
├── frontend/ ...
└── .env              # gitignored; optional
```

## First task

Use `agent_system/tickets/OBS-0001.md`. It is a read-only baseline audit and should be run before production implementation tickets are created.
