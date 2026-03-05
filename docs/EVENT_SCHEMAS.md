# Observa — Event Schemas

> Every meaningful occurrence in Observa emits a named, timestamped,
> immutable event. This document defines the complete schema for every
> event in the system — its fields, producer, consumers, and invariants.
>
> These events are the system of record. Everything else is derived.

---

## Baseline Fields

Every single event in Observa carries these three fields.
They are never omitted.

| Field | Type | Description |
|---|---|---|
| `event_id` | `UUID` | Unique identifier for this specific event |
| `run_id` | `UUID` | The run this event belongs to |
| `timestamp` | `DateTime` | Exact time this event occurred |

The schemas below show only fields **beyond** the baseline.

---

## The Traceable Chain

Every trade is fully traceable from signal to close through linked IDs:

```
SignalEmittedEvent        (signal_id)
  ↓
OrderIntentCreatedEvent   (order_id, signal_id)
  ↓
OrderSubmittedEvent       (order_id, signal_id)
  ↓
OrderFilledEvent          (order_id, signal_id)
  ↓
PositionOpenedEvent       (position_id, order_id)
  ↓
PositionClosedEvent       (position_id, order_id)
```

From any single event you can trace the entire journey
forwards and backwards.

---

## Market Events

---

### `BarReceivedEvent`

A new bar arrived from the dataset and entered the engine.

**Producer:** Replay Engine
**Consumers:** Strategy Sandbox, Visualization Layer, Event Log

| Field | Type | Description |
|---|---|---|
| `open` | `float` | Opening price |
| `high` | `float` | Highest price |
| `low` | `float` | Lowest price |
| `close` | `float` | Closing price |
| `volume` | `float?` | Volume — nullable, not all datasets include it |

**Invariants:**
- `high` must be >= `open`, `close`, and `low`
- `low` must be <= `open`, `close`, and `high`
- `timestamp` must be strictly greater than the previous bar's timestamp
- `volume` must be >= 0 if present

---

## Strategy Events

---

### `SignalEmittedEvent`

The strategy detected a condition and declared trading intent.
This is not an order — it is an expression of intent.

**Producer:** Strategy Sandbox
**Consumers:** Replay Engine, Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `signal_id` | `UUID` | Unique ID for this signal |
| `direction` | `Direction` | `BUY` or `SELL` |
| `size` | `float` | Requested lot size |
| `intended_price` | `float` | Price the strategy wants to fill at |
| `sl` | `float?` | Stop loss price — optional |
| `tp` | `float?` | Take profit price — optional |
| `reason` | `string` | Why the strategy signalled — appears on chart tooltip |

**Invariants:**
- `size` must be > 0
- If `sl` is present, it must be on the correct side of `intended_price`
- If `tp` is present, it must be on the correct side of `intended_price`
- `reason` must not be empty

---

### `IndicatorUpdatedEvent`

An indicator value was recalculated for the current bar.

**Producer:** Strategy Sandbox
**Consumers:** Visualization Layer, Event Log

| Field | Type | Description |
|---|---|---|
| `indicator_name` | `string` | Name given to this indicator at registration |
| `indicator_type` | `string` | e.g. `EMA`, `RSI`, `BollingerBands` |
| `values` | `map` | Key-value pairs of output names to values |
| `is_ready` | `bool` | Whether the indicator has enough history to be valid |

**Invariants:**
- `values` must not be empty
- If `is_ready` is false, consumers must not use the values for decisions

---

## Order Events

---

### `OrderIntentCreatedEvent`

The Replay Engine converted a signal into a structured order request.

**Producer:** Replay Engine
**Consumers:** Execution Model, Event Log

| Field | Type | Description |
|---|---|---|
| `order_id` | `UUID` | Unique ID for this order |
| `signal_id` | `UUID` | Links back to the signal that caused this |
| `direction` | `Direction` | `BUY` or `SELL` |
| `size` | `float` | Lot size |
| `intended_price` | `float` | Requested fill price |
| `sl` | `float?` | Stop loss — optional |
| `tp` | `float?` | Take profit — optional |
| `reason` | `string` | Carried forward from the signal |

**Invariants:**
- `order_id` must be unique across the entire run
- `signal_id` must reference an existing `SignalEmittedEvent`
- `size` must be > 0

---

### `OrderSubmittedEvent`

The Execution Model accepted the order intent and it is now active.

**Producer:** Execution Model
**Consumers:** Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `order_id` | `UUID` | Which order was submitted |
| `signal_id` | `UUID` | Which signal caused this order |

**Invariants:**
- `order_id` must reference an existing `OrderIntentCreatedEvent`

---

### `OrderFilledEvent`

An order was executed. Capital moved. This is the moment of truth.

**Producer:** Execution Model
**Consumers:** Portfolio Manager, Strategy Sandbox, Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `order_id` | `UUID` | Which order was filled |
| `signal_id` | `UUID` | Which signal caused this order |
| `intended_price` | `float` | Price the strategy requested |
| `executed_price` | `float` | Price actually filled at after slippage |
| `slippage` | `float` | Difference between intended and executed |
| `spread_cost` | `float` | Cost of spread applied at fill |
| `commission` | `float` | Broker commission charged |
| `size` | `float` | Lot size filled |
| `direction` | `Direction` | `BUY` or `SELL` |
| `reason` | `string` | Carried forward from the signal |

**Invariants:**
- `slippage` must equal `executed_price` minus `intended_price`
- `spread_cost` must be >= 0
- `commission` must be >= 0
- `size` must be > 0

---

### `OrderRejectedEvent`

The Execution Model refused the order before it became active.

**Producer:** Execution Model
**Consumers:** Strategy Sandbox, Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `order_id` | `UUID` | Which order was rejected |
| `signal_id` | `UUID` | Which signal caused this order |
| `rejection_reason` | `RejectionReason` | Structured rejection code |
| `rejection_detail` | `string` | Human readable explanation for chart tooltip |

**`RejectionReason` codes:**

| Code | Meaning |
|---|---|
| `INVALID_STOP` | SL is too close to entry price |
| `INVALID_TP` | TP is too close to entry price |
| `INVALID_SIZE` | Lot size below minimum or above maximum |
| `INSUFFICIENT_CAPITAL` | Account balance too low to open position |
| `PRICE_OUT_OF_RANGE` | Requested price unreachable from current market |

**Invariants:**
- `rejection_reason` must be a valid `RejectionReason` code
- `rejection_detail` must not be empty

---

### `OrderCancelledEvent`

An active order was cancelled before it was filled.

**Producer:** Execution Model
**Consumers:** Strategy Sandbox, Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `order_id` | `UUID` | Which order was cancelled |
| `signal_id` | `UUID` | Which signal caused this order |
| `cancellation_reason` | `CancellationReason` | Structured cancellation code |
| `cancellation_detail` | `string` | Human readable explanation |

**`CancellationReason` codes:**

| Code | Meaning |
|---|---|
| `INSUFFICIENT_FUNDS` | Balance dropped below required margin |
| `CANCELLED_BY_STRATEGY` | Strategy explicitly cancelled the order |
| `EXPIRED` | Order reached its expiry time unfilled |

---

## Position Events

---

### `PositionOpenedEvent`

A new position was opened following an order fill.

**Producer:** Portfolio Manager
**Consumers:** Strategy Sandbox, Event Log, Visualization Layer, Metrics Layer

| Field | Type | Description |
|---|---|---|
| `position_id` | `UUID` | Unique ID for this position |
| `order_id` | `UUID` | Which fill opened this position |
| `direction` | `Direction` | `BUY` or `SELL` |
| `size` | `float` | Lot size |
| `entry_price` | `float` | Price at which position opened |
| `sl` | `float?` | Initial stop loss |
| `tp` | `float?` | Initial take profit |
| `pnl` | `float` | Always 0.0 at open — included for consistency |
| `pct_equity` | `float` | Position size as % of total equity |
| `pct_balance` | `float` | Position size as % of total balance |

**Invariants:**
- `pnl` must be 0.0 at open
- `position_id` must be unique across the entire run
- `order_id` must reference an existing `OrderFilledEvent`

---

### `PositionUpdatedEvent`

An open position was modified — stop adjusted, TP adjusted,
or partially closed.

**Producer:** Portfolio Manager
**Consumers:** Strategy Sandbox, Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `position_id` | `UUID` | Which position was updated |
| `update_type` | `UpdateType` | What kind of update occurred |
| `previous_sl` | `float?` | Stop loss before update |
| `new_sl` | `float?` | Stop loss after update |
| `previous_tp` | `float?` | Take profit before update |
| `new_tp` | `float?` | Take profit after update |
| `size` | `float` | Current size after update |
| `pnl` | `float` | Unrealised PnL at time of update |
| `pct_equity` | `float` | Position size as % of equity |
| `pct_balance` | `float` | Position size as % of balance |

**`UpdateType` codes:**

| Code | Meaning |
|---|---|
| `SL_ADJUSTED` | Stop loss was moved |
| `TP_ADJUSTED` | Take profit was moved |
| `PARTIAL_CLOSE` | Part of the position was closed |

---

### `PositionClosedEvent`

A position was fully closed. PnL is now realised.

**Producer:** Portfolio Manager
**Consumers:** Strategy Sandbox, Event Log, Visualization Layer, Metrics Layer

| Field | Type | Description |
|---|---|---|
| `position_id` | `UUID` | Which position closed |
| `order_id` | `UUID` | Which fill closed this position |
| `direction` | `Direction` | `BUY` or `SELL` |
| `size` | `float` | Lot size closed |
| `entry_price` | `float` | Where position was opened |
| `exit_price` | `float` | Where position was closed |
| `exit_reason` | `ExitReason` | How the position closed |
| `pnl` | `float` | Realised PnL for this trade |
| `pct_equity` | `float` | As % of equity at close time |
| `pct_balance` | `float` | As % of balance at close time |

**`ExitReason` codes:**

| Code | Meaning |
|---|---|
| `TP` | Take profit was hit |
| `SL` | Stop loss was hit |
| `SIGNAL` | Strategy called `self.close()` |

**Invariants:**
- `exit_price` must be a valid market price
- `pnl` must equal `(exit_price - entry_price) * size * direction_multiplier - costs`

---

## Portfolio Events

---

### `PortfolioSnapshotEvent`

A complete snapshot of the account's financial state at a point in time.
Emitted after every fill and at the end of every bar.

**Producer:** Portfolio Manager
**Consumers:** Metrics Layer, Visualization Layer, Event Log

| Field | Type | Description |
|---|---|---|
| `balance` | `float` | Total account balance |
| `equity` | `float` | Balance plus unrealised PnL |
| `margin` | `float` | Margin currently in use |
| `free_margin` | `float` | Equity minus margin |
| `unrealised_pnl` | `float` | Total floating PnL across all open positions |
| `realised_pnl` | `float` | Total closed PnL so far in this run |
| `open_positions` | `int` | Number of positions currently open |

**Invariants:**
- `equity` must equal `balance` + `unrealised_pnl`
- `free_margin` must equal `equity` - `margin`
- `open_positions` must be >= 0

---

## Run Events

---

### `RunStartedEvent`

A run began. Everything needed to reproduce this run exactly
is captured in this single event.

**Producer:** Replay Engine
**Consumers:** Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `strategy_name` | `string` | Name of the strategy class |
| `strategy_version` | `string` | Hash of the strategy file |
| `dataset_name` | `string` | Name of the CSV file |
| `dataset_hash` | `string` | Hash of the data file |
| `start_time` | `DateTime` | First bar timestamp in dataset |
| `end_time` | `DateTime` | Last bar timestamp in dataset |
| `initial_balance` | `float` | Starting capital |
| `configuration` | `map` | Full config snapshot — spread, slippage, commission |

**Invariants:**
- `initial_balance` must be > 0
- `start_time` must be before `end_time`
- `strategy_version` and `dataset_hash` must be valid file hashes
- `configuration` must be complete and frozen — no fields missing

---

### `RunCompletedEvent`

The run finished successfully. All bars were processed.

**Producer:** Replay Engine
**Consumers:** Event Log, Visualization Layer, Metrics Layer

| Field | Type | Description |
|---|---|---|
| `start_time` | `DateTime` | When the run began |
| `end_time` | `DateTime` | When the run ended |
| `total_bars` | `int` | Total bars processed |
| `total_trades` | `int` | Total trades completed |
| `final_balance` | `float` | Ending account balance |
| `final_equity` | `float` | Ending equity |
| `realised_pnl` | `float` | Total PnL for the entire run |

**Invariants:**
- `total_bars` must be > 0
- `end_time` must be after `start_time`
- `realised_pnl` must equal `final_balance` minus `initial_balance`

---

### `RunErrorEvent`

The run was interrupted by an error.

**Producer:** Replay Engine
**Consumers:** Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `error_type` | `ErrorType` | Structured error code |
| `error_message` | `string` | Human readable description |
| `stack_trace` | `string` | Full technical error detail |
| `last_bar` | `BarReceivedEvent` | The bar being processed when the error occurred |

**`ErrorType` codes:**

| Code | Meaning |
|---|---|
| `STRATEGY_EXCEPTION` | User strategy code threw an exception |
| `DATA_CORRUPTION` | Dataset contained invalid or malformed data |
| `ENGINE_FAULT` | Internal engine error |
| `RESOURCE_LIMIT_EXCEEDED` | Strategy exceeded time or memory limits |

**Invariants:**
- `error_message` must not be empty
- `last_bar` must reference the most recently processed bar

---

## Annotation Events

---

### `JournalEntryAddedEvent`

A user attached a journal note to a specific event or time range.
Annotations never influence execution — they are metadata only.

**Producer:** Strategy Sandbox or UI
**Consumers:** Event Log, Visualization Layer

| Field | Type | Description |
|---|---|---|
| `annotation_id` | `UUID` | Unique ID for this annotation |
| `target_event_id` | `UUID?` | The event this note is attached to — optional |
| `target_time_start` | `DateTime?` | Start of time range — optional |
| `target_time_end` | `DateTime?` | End of time range — optional |
| `text` | `string` | The note content |
| `source` | `AnnotationSource` | `STRATEGY` or `UI` |

**Invariants:**
- At least one of `target_event_id` or `target_time_start` must be present
- `text` must not be empty
- Annotations never affect replay, execution, or metrics

---

## Complete Event Reference

| Event | Producer | Primary Consumers |
|---|---|---|
| `BarReceivedEvent` | Replay Engine | Strategy, Visualization, Event Log |
| `SignalEmittedEvent` | Strategy Sandbox | Replay Engine, Visualization, Event Log |
| `IndicatorUpdatedEvent` | Strategy Sandbox | Visualization, Event Log |
| `OrderIntentCreatedEvent` | Replay Engine | Execution Model, Event Log |
| `OrderSubmittedEvent` | Execution Model | Event Log, Visualization |
| `OrderFilledEvent` | Execution Model | Portfolio Manager, Strategy, Visualization, Event Log |
| `OrderRejectedEvent` | Execution Model | Strategy, Visualization, Event Log |
| `OrderCancelledEvent` | Execution Model | Strategy, Visualization, Event Log |
| `PositionOpenedEvent` | Portfolio Manager | Strategy, Visualization, Metrics, Event Log |
| `PositionUpdatedEvent` | Portfolio Manager | Strategy, Visualization, Event Log |
| `PositionClosedEvent` | Portfolio Manager | Strategy, Visualization, Metrics, Event Log |
| `PortfolioSnapshotEvent` | Portfolio Manager | Metrics, Visualization, Event Log |
| `RunStartedEvent` | Replay Engine | Event Log, Visualization |
| `RunCompletedEvent` | Replay Engine | Event Log, Visualization, Metrics |
| `RunErrorEvent` | Replay Engine | Event Log, Visualization |
| `JournalEntryAddedEvent` | Strategy or UI | Event Log, Visualization |

---

*Event schemas are frozen for MVP. New fields are additive only —
existing fields are never removed or renamed.*