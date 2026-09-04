# Agent Context Rules

## Context tiers

### Tier 1 — Always

- `docs/README.md`
- `docs/CURRENT_STATE.md`
- active ticket
- role instructions

### Tier 2 — Task-specific

Load only the relevant domain and engineering documents.

### Tier 3 — On demand

- `docs/DECISIONS.md`
- unrelated domain docs
- historical notes
- archived material

An agent should request Tier 3 context only when the task requires it.

## Ground truth order

1. Runtime code and executable tests
2. Current authoritative contracts
3. Approved ticket
4. Architecture and domain documentation
5. Historical decisions

When a conflict is discovered, the agent must stop and report it rather than silently choosing a side.
