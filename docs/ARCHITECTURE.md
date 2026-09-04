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
- SignalEmittedEvent
- IndicatorUpdatedEvent
- DrawingsEmitted

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
