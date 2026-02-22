# Observa — Domain Model

> This document defines the language of Observa. Every concept here means
> one thing and one thing only. When in doubt, return to these definitions.

---

## Core Concepts

### Run
A complete, isolated execution of a Strategy against a Dataset using a
fixed Configuration. Every event that occurs belongs to exactly one Run.
Same inputs always produce the same outputs. A Run is the unit of
reproducibility in Observa.

---

### Event
An immutable record of something meaningful that occurred during a Run,
at a specific point in time. Events are never edited or deleted — they
are the source of truth from which everything in Observa is derived.

---

### Bar
A single row of OHLCV data representing price activity over a fixed time
period — one minute, one hour, one day. A Bar is the primary unit of
market data in Observa.

---

### Tick
The smallest recorded price movement in a market. A Tick has no duration
— only a timestamp and a price. Bars are derived from Ticks.

---

### Signal
An instruction emitted by a Strategy indicating that a condition has been
met and an action should be considered. A Signal is not an Order — it is
an expression of intent that the execution layer may or may not act on.

---

### Order Intent
A structured request from a Strategy to enter or exit a position,
including direction, size, and type. An Order Intent is not yet an Order
— it is waiting to be validated and accepted by the execution engine.

---

### Order
A validated Order Intent that has been accepted by the execution engine
and is now active in the market simulation — either pending, partially
filled, or cancelled.

---

### Fill
The execution of an Order at a specific price and time. A Fill is the
moment capital actually moves. It records the executed price, quantity,
slippage incurred, and spread paid.

---

### Position
An active exposure in the market resulting from one or more Fills. A
Position tracks entry price, current size, unrealised PnL, and direction.
It exists until fully closed.

---

### Portfolio
The complete financial state of a Run at any point in time — including
capital, open Positions, realised PnL, and exposure. The Portfolio is a
derived view, always calculated from events, never directly mutated.

---

### Strategy
The user-provided logic that defines when to enter, manage, and exit
trades. A Strategy receives market data one Bar at a time, maintains its
own private state, and emits Signals. It cannot directly place orders or
access future data.

---

### Indicator
A value or series of values derived from market data, calculated
incrementally one Bar at a time. Indicators are owned by the Strategy
and can be plotted on the chart for visual inspection.

---

### Dataset
The historical market data — Bar or Tick — provided as input to a Run.
A Dataset has a defined symbol, timeframe, and time range. It is
read-only during a Run.

---

### Configuration
The fixed set of parameters defining how a Run behaves — including
execution model settings, spread, slippage, commission, and strategy
parameters. Configuration is frozen at the start of a Run and cannot
change during execution.

---

### Annotation / Journal Entry
A piece of user-written metadata attached to a specific Event, time
range, or trade. Annotations are stored separately from the event log
and keyed by Run ID, Event ID, or timestamp range. They do not influence
execution in any way.

---

### Spread
The difference between the bid and ask price at any moment. In Observa,
spread is applied at Fill time to simulate real broker conditions.

---

### Slippage
The difference between the intended execution price of an Order Intent
and the actual price of the Fill. Slippage can be positive or negative
and is applied by the execution model.

---

### Commission
A cost charged per trade by the simulated broker, deducted at Fill time.
Commission reduces realised PnL and is part of the execution realism
layer.

---

### Execution Model
The pluggable module that sits between an Order Intent and a Fill. It
applies spread, slippage, commission, latency, and fill logic to simulate
realistic broker behaviour. Strategies never interact with the Execution
Model directly.

---

## Event Taxonomy

Every meaningful occurrence in Observa emits a named, time-stamped,
immutable event. These events are the backbone of replay, visualization,
debugging, and metrics.

### Market Events
Events produced by the market data feed.

| Event | Description |
|---|---|
| `BarReceivedEvent` | A new bar arrived from the dataset |
| `TickReceivedEvent` | A new tick arrived from the dataset |

### Strategy Events
Events produced by the strategy's internal logic.

| Event | Description |
|---|---|
| `SignalEmittedEvent` | Strategy emitted a buy or sell signal |
| `IndicatorUpdatedEvent` | An indicator value was recalculated for this bar |

### Order Events
Events covering the full lifecycle of an order.

| Event | Description |
|---|---|
| `OrderIntentCreatedEvent` | Strategy requested an order |
| `OrderSubmittedEvent` | Execution engine accepted the order |
| `OrderFilledEvent` | Order was executed at a price |
| `OrderCancelledEvent` | Order was cancelled before execution |
| `OrderRejectedEvent` | Order was rejected (e.g. stop too close to entry) |

### Position Events
Events covering the lifecycle of an open trade.

| Event | Description |
|---|---|
| `PositionOpenedEvent` | A new position was opened |
| `PositionUpdatedEvent` | Position size or stop was modified |
| `PositionClosedEvent` | Position was fully closed |

### Portfolio Events
Events reflecting the overall financial state.

| Event | Description |
|---|---|
| `PortfolioSnapshotEvent` | Capital and exposure recorded at a point in time |

### Run Events
Events covering the lifecycle of a full run.

| Event | Description |
|---|---|
| `RunStartedEvent` | A run began with a fixed configuration |
| `RunCompletedEvent` | A run finished successfully |
| `RunErrorEvent` | A run was interrupted by an error |

### Annotation Events
Events related to user journaling.

| Event | Description |
|---|---|
| `JournalEntryAddedEvent` | A journal annotation was attached to an event or time range |

---

## State Ownership Rules

Each component owns its state exclusively. No other component may read
or mutate another's state directly — all communication happens through
events.

| Component | Owns | Cannot Touch |
|---|---|---|
| **Strategy** | Its own internal variables and indicator values | Orders, fills, portfolio, capital |
| **Execution Engine** | Order lifecycle from intent to fill | Strategy state, portfolio capital |
| **Portfolio Manager** | Capital, open positions, realised PnL | Order logic, strategy logic |
| **Event Bus** | The ordered, immutable event log | Nothing — it only routes |
| **Metrics Layer** | Derived statistics calculated from events | Raw state of any component |
| **Visualization Layer** | Display state only | Nothing — it only subscribes to events |
| **Journal / Annotations** | User metadata keyed to events | Execution, strategy, or portfolio state |

### The Golden Rule
> The UI computes nothing about truth.
> The Strategy decides nothing about execution.
> The Execution Engine knows nothing about portfolio state.
> Everything communicates through events.

---

*This document is a living reference. Definitions are refined as the
system evolves, but the Golden Rule is immutable.*