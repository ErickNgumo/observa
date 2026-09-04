# Observa Agent Instructions

You are working in the Observa repository.

## Before changing anything
Read:
1. `docs/PROJECT.md` when product context is needed.
2. `docs/MVP.md` when deciding scope.
3. `docs/CURRENT_STATE.md` for the current implementation baseline.
4. `docs/ARCHITECTURE.md` for architectural invariants.
5. The task ticket under `agent_system/tickets/`.
6. Your role instructions under `docs/agents/`.
7. Relevant domain/engineering documents referenced by the ticket.

## Authority
- Current code is runtime truth.
- `docs/MVP.md` controls MVP scope.
- `docs/ARCHITECTURE.md` controls architectural invariants.
- `docs/DECISIONS.md` records historical decisions; it does not override current code or approved scope.
- Never invent undocumented APIs when the repository can be inspected.

## Non-negotiable Observa invariants
- Event log is the source of truth.
- Visualization does not compute financial truth.
- Strategy emits intent/signals; execution determines fills.
- Execution applies spread/slippage according to the execution rules.
- Equity snapshots are sampled per bar for mark-to-market metrics.
- Determinism is required.
- Future data must be structurally inaccessible to strategies.
- Financial changes require independent Finance/QA verification.

## Agent behavior
- Work only on the assigned ticket.
- Do not silently expand scope.
- Report uncertainty instead of guessing.
- Run relevant tests/checks after changes.
- Record important findings in the ticket/run artifacts.
