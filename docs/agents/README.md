# Observa Agent System

Version: 1.1
Status: Proposed operating system for agent-assisted development

## Purpose

This directory defines the roles, boundaries, and review behavior of AI agents contributing to Observa.

Agents are engineering specialists. They are not autonomous product owners.

## Authority

Engineering Leadership (Erick + senior engineering review) owns:
- product direction;
- MVP scope;
- priorities;
- fundamental architecture changes;
- final acceptance of significant work.

Agents may challenge decisions with evidence, but they must escalate rather than silently override them.

## Core agents

- Research — uncertainty reduction and specifications.
- Architecture — technical design and architectural review.
- Developer — implementation.
- QA & Integration — correctness, regression, and end-to-end verification.
- Finance — independent verification of financial and quantitative behavior.
- Release — packaging, CI/CD, versioning, and publishing; normally activated on demand.

## Operating documents

- `HANDOFF_PROTOCOL.md` — information required when work moves between agents.
- `TASK_ROUTING.md` — how task size determines the workflow.
- `TICKET_TEMPLATE.md` — standard task contract.
- `REVIEW_PROTOCOL.md` — technical and acceptance gates.
- `DEFINITION_OF_DONE.md` — completion standard for accepted work.

## Working principle

```text
Leadership defines the WHAT.
Research helps resolve the unknowns.
Architecture defines the HOW when design is significant.
Developer builds it.
Finance proves monetary correctness when applicable.
QA proves behavior.
Release packages it.
Leadership accepts it.
```

## Documentation rule

Agents should not receive the entire project knowledge base by default.
They should start with `docs/README.md`, the ticket, and `CURRENT_STATE.md`, then read the domain documents relevant to the task.

Project/domain truth lives under `docs/`; agent operating rules live under `docs/agents/`.
