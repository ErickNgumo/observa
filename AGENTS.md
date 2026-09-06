# Observa Agent Instructions

You are working in the Observa repository — either implementing **Observa
itself** or a **user trading strategy on top of Observa**. Read this file, and
`llms-full.txt` where relevant, before making changes.

## Before changing anything
Read:
1. `llms-full.txt` (official agent & integration guide — canonical API,
   signals, execution semantics, common mistakes, agent rules).
2. `docs/PROJECT.md` when product context is needed.
3. `docs/MVP.md` when deciding scope.
4. `docs/CURRENT_STATE.md` for the current implementation baseline.
5. `docs/ARCHITECTURE.md` for architectural invariants.
6. The task ticket under `agent_system/tickets/`.
7. Your role instructions under `docs/agents/`.

## Authority
- Current code is runtime truth.
- `docs/MVP.md` controls MVP scope.
- `docs/ARCHITECTURE.md` controls architectural invariants.
- `docs/DECISIONS.md` records historical decisions; it does not override
  current code or approved scope.
- Never invent undocumented APIs when the repository can be inspected.

## Canonical architecture (non-negotiable)
- The Rust **Engine** is the canonical runtime and the only backtest loop.
- **Canonical events** are the authoritative history.
- The **frontend is presentation only** — it never computes financial truth.
- **Python specifies intent** (signals); the Engine determines execution
  (fills, spread/slippage, SL/TP outcomes, P&L).
- Execution applies spread/slippage according to the accepted execution rules.
- Equity/account snapshots are sampled per bar.
- Determinism is required; no wall-clock/UUID/hash ordering of economics.
- Future data must be structurally inaccessible to strategies.
- Positions are closed by explicit tickets; never invent FIFO behavior.
- Financial/economic changes require independent Finance/QA verification.

## Two roles — keep them separate

### If implementing a USER trading strategy (examples/, ai_starter/, user code)
- Do **not** modify the Observa engine or its semantics.
- Use the canonical Observa Python API (`initialize`/`on_bar`/`teardown`,
  signal dicts, explicit-ticket closes).
- Never implement fills, portfolio P&L, SL/TP outcomes, or a second replay
  loop yourself.

### If implementing OBSERVA ITSELF
- Follow the repository architecture and invariants above.
- Run relevant tests before claiming success.

## Agent behavior
- Work only on the assigned ticket.
- Do not silently expand scope.
- Report uncertainty instead of guessing.
- Run relevant tests/checks after changes.
- Do not claim success unless the code actually ran when execution access
  exists.
- Record important findings in the ticket/run artifacts.
