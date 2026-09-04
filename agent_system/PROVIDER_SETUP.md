# DeepSeek Harness Setup

DeepSeek Harness (`dsh`) is the runtime used by Observa agents. The official harness currently provides a headless profile suitable for unattended coding tasks:

```bash
npx @deepseek-ai/dsh --profile headless "Inspect this repository and report the result."
```

Run the command from the repository/workspace that should be exposed to the agent. The headless profile creates a fresh persisted session and prints the final assistant text.

## Credentials

Set `DEEPSEEK_API_KEY` in the environment or in the harness-supported gitignored `.env`. Never commit credentials.

## Observa integration

The Observa adapter invokes the headless profile with a short launcher instruction. The actual ticket/context lives in the repository worktree, which avoids putting a huge task blob in the process command line.

```text
Observa ticket
    ↓
orchestrator
    ↓
role-specific context file
    ↓
DSH headless session
    ↓
worktree changes / report
```

## Harness status

DeepSeek Harness is currently a developer preview and its interfaces can change. Keep the project-specific orchestration layer independent so a harness upgrade does not require redesigning the Observa team model.
