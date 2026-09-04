# Ticket Schema

Each ticket is a Markdown file under `agent_system/tickets/`.

Required front matter:

```yaml
id: OBS-0001
title: Short title
size: small | medium | large
status: PROPOSED
financial: false
release: false
owner: leadership
```

Required sections:

- Objective
- Why it matters
- Scope
- Non-goals
- Acceptance criteria
- Verification plan
- Relevant docs
- Dependencies
- Decision log
- Agent reports

A ticket is the unit of work and the durable handoff record. Agents must not rely on chat history as the only source of task requirements.
