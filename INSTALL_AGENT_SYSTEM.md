# Install the Observa Agent System into the Observa repository

Assume:

```text
~/projects/observa/
```

is the root of your existing Observa git repository.

## Recommended method

Extract this package into a temporary directory, then copy `docs/`, `agent_system/`, and `AGENTS.md` into the repository root.

```bash
cd /path/to/observa
cp -R /path/to/observa-agent-bundle/docs ./
cp -R /path/to/observa-agent-bundle/agent_system ./
cp /path/to/observa-agent-bundle/AGENTS.md ./AGENTS.md
```

If `docs/` or `agent_system/` already exist, merge carefully rather than blindly overwriting them.

## Verify

```bash
cd /path/to/observa
python3 -m py_compile agent_system/orchestrator.py
python3 agent_system/orchestrator.py show OBS-0001
python3 agent_system/orchestrator.py run OBS-0001 --dry-run
```

## Run with DeepSeek Harness

Install/start the official harness as described by its documentation, then from the Observa root:

```bash
npx @deepseek-ai/dsh web
```

For unattended work, the Observa adapter uses the headless profile. DeepSeek Harness currently supports a headless one-shot coding agent and requires `DEEPSEEK_API_KEY` in the environment (or the harness-supported `.env`).

## Important

Do not copy the agent system into the DeepSeek Harness source repository. Keep it inside the Observa repository. DSH should treat Observa as the workspace; `agent_system/` is Observa's control plane for agent work.
