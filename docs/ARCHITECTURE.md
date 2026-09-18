# Observa Architecture

> Status: current as of the MVP release candidate (OBS-0011). The repository
> is the source of truth; this document describes the canonical runtime.

## 0. Canonical pipeline (what a run actually is)

```text
Python API / CLI (user surfaces)
        ↓
Canonical Engine (single replay loop)
        ↓
OBS-0006 Execution semantics ─┐
OBS-0005 Portfolio authority ─┴─ (no other component computes economics)
        ↓
Canonical events (EventSeq)   ← authoritative history
        ↓
Persistence (run.json / events.jsonl / metrics.json)
        ↓
Replay adapter → frontend (a view of canonical events; never an authority)
```

Key ownership rules (verified by integration QA):

* **One engine.** The canonical Rust Engine is the only backtest loop for the
  Python package, the CLI, and the replay.
* **One history.** The canonical ordered event stream is the source of truth;
  the frontend never reconstructs fills, P&L, SL/TP outcomes, or position
  pairing.
* **Metrics are derived**, never authoritative. Balance/equity come from the
  Engine result.
* **Python specifies intent**; execution/portfolio/event semantics are Rust.
* **Replay is a view.** It consumes canonical events through a pure reducer.

# Observa Architecture

## 1. Architectural style

Observa is designed as an event-sourced, component-isolated system.

Every meaningful state change emits an immutable event. Components communicate through the event architecture rather than sharing hidden mutable state.

## 2. Golden rules

These are the core architectural invariants carried forward from the source knowledge base:

1. The UI computes nothing about system truth.
2. The Strategy decides nothing about execution.
3. The Execution Engine knows nothing about portfolio state.
4. Components communicate through events.

## 3. Additional invariants

- Every state-changing operation emits an event.
- Same inputs produce the same outputs.
- Economic object identity is deterministic and run-local, so a repeated run
  reproduces `events.jsonl`, `run.json` and `metrics.json` byte-for-byte
  (see §6b).
- Future data is structurally unavailable to the strategy.
- Execution realism is applied in the execution model / approved portfolio logic, not in presentation code.
- Portfolio snapshots are emitted on every bar so the equity curve is mark-to-market.

## 4. Runtime flow

```text
CSV
 ↓
observa-data
 ↓
observa-cli / replay orchestration
 ├─ bar received
 ├─ strategy.on_bar() through PyO3
 ├─ signal → order intent
 ├─ execution model → fill or rejection
 ├─ portfolio manager → position / PnL events
 ├─ portfolio snapshot every bar
 └─ drawings/events
 ↓
HTTP server
 ↓
Browser frontend
 ↓
TradingView Lightweight Charts
```

## 5. Crates

```text
observa-core
  Shared Bar, events, enums, drawings, InstrumentSpec

observa-data
  CSV loading and validation

observa-engine
  Event bus, Strategy trait, signals, portfolio view, replay loop

observa-execution
  ExecutionModel, configuration, fill calculation, validation

observa-portfolio
  PortfolioManager, positions, SL/TP, equity

observa-metrics
  EquityCurve, drawdown, trade statistics, MetricsEngine

observa-python
  PyO3 bridge, strategy loading, conversion, drawings

observa-cli
  CLI, configuration, orchestration, HTTP serving

observa-runner
  Earlier prototype; largely superseded

observa-server
  Earlier prototype; retained mainly for development testing
```

## 6. Event taxonomy

### Market
- BarReceivedEvent

### Strategy
- `strategy_decision` carries `bar_index`, `signal_count` and — when at least
  one signal supplied one — an index-aligned `signals` array of
  `{signal_index, reason}` records (OBS-SCHEMA-01). The field is omitted
  entirely when no reason exists.
- StrategyDecisionEvent (per-bar signal count)
- DrawingsEmittedEvent (strategy annotations; canonical `drawings_emitted`)

### Order
- OrderIntentCreatedEvent
- OrderSubmittedEvent
- OrderFilledEvent
- OrderRejectedEvent
- OrderCancelledEvent

### Position
- PositionOpenedEvent
- PositionUpdatedEvent
- PositionClosedEvent

### Portfolio
- PortfolioSnapshotEvent

### Run
- RunStartedEvent
- RunCompletedEvent
- RunErrorEvent

### Annotation
- JournalEntryAddedEvent

## 6a. Strategy annotations (OBS-AI-02)

- Annotations are **descriptive only**: they never influence order creation,
  fills, spread/slippage, SL/TP, margin, portfolio accounting, metrics or
  event ordering.
- They are recorded on the single canonical timeline as `drawings_emitted`
  events (normal EventSeq) and appear **only** when a strategy returned at
  least one instruction, so a strategy that draws nothing adds no events (the
  deterministic no-drawing baseline is byte-identical).
- Replay reconstructs annotation state from canonical events; there is no
  second timeline and no `drawings.jsonl`, and the replay payload's `drawings`
  array is derived from those events.
- Observa renders generic primitives (series, hline, line, rectangle, region,
  marker, label) and never interprets strategy concepts such as "FVG"/"POC".
- Malformed annotations fail the run with a coded error (`DRAWING_*`); they are
  never silently discarded.

## 6b. Deterministic economic object identity (OBS-DET-01)

- Orders, fills and positions are referenced by deterministic identifiers:
  `order_seq` (a run-local counter) and `position_id` (a run-local identifier).
- `position_id` is a UUIDv5 derived from a **fixed Observa namespace** and the
  1-based ordinal of the position's open order within the run. It never depends
  on random entropy, the machine, wall-clock time, or the random session
  `run_id`.
- The ordinal advances **only** when a position is actually created: rejected
  entries, failed margin checks, invalid orders and closes never consume one.
- Identity is referential metadata only. It never influences execution
  ordering, acceptance/rejection, prices, spread/slippage, commission, SL/TP,
  margin, P&L, metrics, `EventSeq` or `OrderSeq`. Nothing orders or sorts by
  identifier value.
- Uniqueness is guaranteed **within a run**, not globally across runs. Two
  different runs may reuse the same ids.
- Identifiers remain opaque strings at every boundary (persisted events, Python
  API, replay frontend). Historical UUIDv4 runs from 0.1.1 stay readable with no
  migration, and the wire type is unchanged.
- Because identity is deterministic, a repeated run with identical dataset,
  config and strategy reproduces `events.jsonl`, `run.json` and `metrics.json`
  byte-for-byte.

## 6c. Run inspection (OBS-AI-03)

- `observa.inspect_run(run_dir)` returns a read-only `PersistedRun` over a
  **persisted** run: the programmatic way to ask what canonical history
  contains without re-running the engine.
- Inspection reads only the persisted artifacts (`run.json`, `events.jsonl`,
  `metrics.json`). It never requires the strategy code, never executes a
  strategy, and never writes to the run directory.
- It **organizes** canonical evidence; it never recomputes economics, never
  infers missing facts and never fabricates strategy reasoning. Where the
  canonical model has no value, the API returns `None`/`[]`.
- Events are parsed once and indexed by `event_seq`, bar chronology bucket,
  `position_id` and `order_seq`. `bar_index` queries use the same
  chronology-bucket attribution the replay frontend uses — events belong to the
  bar whose `bar_processed` is open — so `events(bar_index=n)` and
  `bar(n)["events"]` always agree.
- Canonical ordering (`event_seq` ascending) is preserved everywhere; nothing is
  ordered by identifier text or hash iteration.
- The strategy's own per-signal `reason` is persisted on `strategy_decision`
  (OBS-SCHEMA-01) as an optional, index-aligned `signals` array that is omitted
  when no signal supplied one, so reason-less decisions stay byte-identical.
  Reasons are descriptive only and never influence execution.
- A remaining canonical-data limitation is reported rather than papered over: a
  position's closing order is not derivable because `position_closed` carries no
  `order_seq` (OBS-SCHEMA-02).

## 7. Traceability

The intended chain for a normal trade is:

```text
SignalEmittedEvent
  ↓
OrderIntentCreatedEvent
  ↓
OrderFilledEvent / OrderRejectedEvent
  ↓
PositionOpenedEvent
  ↓
PositionClosedEvent
```

The event IDs and run ID provide traceability across the chain.

## 8. Financial execution invariants

- Calculate actual fill price before validating SL/TP distance.
- SL exits receive slippage because they represent market execution.
- TP exits do not receive slippage because they represent limit execution.
- Portfolio equity includes unrealised PnL.
- Portfolio snapshots are emitted for every bar.
- InstrumentSpec is the intended source for monetary exposure calculations.

## 9. Important implementation constraint

The CLI currently depends on the concrete `PyStrategy` type when it needs access to `pending_drawings`. `pending_drawings` is not available through `dyn Strategy`.

This is an implementation constraint, not a general architectural principle that every future component must copy.

## 10. Architecture review rule

An old architectural decision may be changed when there is a documented reason. The architecture document describes current approved invariants; historical rationale belongs in `DECISIONS.md`.
