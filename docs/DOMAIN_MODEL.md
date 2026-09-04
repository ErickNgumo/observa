# Observa Domain Model

## Core concepts

### Run
A complete, isolated execution of a strategy against a dataset. The reproducibility unit.

### Bar
One OHLCV candle representing market activity over a fixed period.

### Tick
A timestamped price movement. Not implemented in the MVP.

### Signal
Strategy expression of intent that a condition has been met. It is not an executed order.

### Order Intent
Structured request created from a signal and passed into execution.

### Fill
Actual execution of an order at a specific price and time. This is when capital moves.

### Position
Market exposure from entry fill to exit fill.

### Ticket
UUID identifying a position for targeted closing.

### Event Bus
Message router. It routes events; it does not contain business truth.

### Event Log
Immutable record of a Run's events and the source of truth.

### Replay Engine
Controls chronological progression through bars and coordinates strategy invocation and signal processing.

### Execution Model
Applies the approved execution assumptions such as spread, slippage, commission, and validation.

### Portfolio Manager
Tracks balance, positions, equity, and PnL; checks SL/TP.

### Strategy Sandbox
Environment where Python strategy code receives bar/portfolio/history and emits signals/drawings without direct access to order execution.

### InstrumentSpec
Contract specification used to convert quantities into monetary exposure and risk values.

### DrawingInstruction
Visual instruction emitted by a strategy and applied by the visualization layer.

### Mark-to-market
Equity calculated using current price and unrealised PnL.

## Core entities

### Bar
- timestamp
- open
- high
- low
- close
- volume

### Position
- position_id
- order_id
- direction
- size
- entry_price
- sl
- tp
- opened_at
- closed_at
- exit_price
- exit_reason
- status
- realised_pnl

### InstrumentSpec
- symbol
- contract_size
- pip_value
- price_decimals
- margin_rate

### EventMetadata
- event_id
- run_id
- timestamp

## Relationships

```text
Run 1 → many Events
Signal → Order Intent
Order Intent → Fill or Rejection
Fill → Position entry or close
Position → PositionOpened + PositionClosed
```

## Core invariant

The system should make it possible to trace a user-visible result from the event log back through the event chain that produced it.
