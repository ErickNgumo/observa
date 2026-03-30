use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::bar::Bar;
use crate::types::{
    AnnotationSource, CancellationReason, Direction,
    ErrorType, ExitReason, RejectionReason, UpdateType,
};

// ────────────────────────────────────────────────
// EventMetadata — shared baseline for all events
// ────────────────────────────────────────────────

/// Fields present on every event in Observa.
/// Embedded in every event struct via #[serde(flatten)].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventMetadata {
    /// Unique identifier for this specific event
    pub event_id: Uuid,

    /// The run this event belongs to
    pub run_id: Uuid,

    /// Exact time this event occurred
    pub timestamp: DateTime<Utc>,
}

impl EventMetadata {
    /// Creates new metadata with a fresh random event_id
    pub fn new(run_id: Uuid, timestamp: DateTime<Utc>) -> Self {
        Self {
            event_id: Uuid::new_v4(),
            run_id,
            timestamp,
        }
    }
}

// ────────────────────────────────────────────────
// Market Events
// ────────────────────────────────────────────────

/// A new bar arrived from the dataset.
/// This is the heartbeat of the system — everything
/// starts here.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarReceivedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// The full bar data
    pub bar: Bar,
}

// ────────────────────────────────────────────────
// Strategy Events
// ────────────────────────────────────────────────

/// The strategy detected a condition and declared
/// trading intent. Not an order — an expression
/// of intent.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalEmittedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Unique ID for this signal
    pub signal_id: Uuid,

    /// Buy or Sell
    pub direction: Direction,

    /// Requested lot size
    pub size: f64,

    /// Price the strategy wants to fill at
    pub intended_price: f64,

    /// Stop loss price — optional
    pub sl: Option<f64>,

    /// Take profit price — optional
    pub tp: Option<f64>,

    /// Why the strategy signalled — shown on chart tooltip
    pub reason: String,
}

/// An indicator value was recalculated for this bar.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorUpdatedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Name given to this indicator at registration
    pub indicator_name: String,

    /// Type of indicator e.g. "EMA", "RSI"
    pub indicator_type: String,

    /// Whether indicator has enough history to be valid
    pub is_ready: bool,

    /// Current value — None if not ready
    pub value: Option<f64>,
}

// ────────────────────────────────────────────────
// Order Events
// ────────────────────────────────────────────────

/// The Replay Engine converted a signal into a
/// structured order request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderIntentCreatedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Unique ID for this order
    pub order_id: Uuid,

    /// Links back to the signal that caused this
    pub signal_id: Uuid,

    /// Buy or Sell
    pub direction: Direction,

    /// Lot size
    pub size: f64,

    /// Requested fill price
    pub intended_price: f64,

    /// Stop loss — optional
    pub sl: Option<f64>,

    /// Take profit — optional
    pub tp: Option<f64>,

    /// Carried forward from the signal
    pub reason: String,
}

/// The Execution Model accepted the order —
/// it is now active.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderSubmittedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which order was submitted
    pub order_id: Uuid,

    /// Which signal caused this order
    pub signal_id: Uuid,
}

/// An order was executed. Capital moved.
/// This is the moment of truth.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderFilledEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which order was filled
    pub order_id: Uuid,

    /// Which signal caused this order
    pub signal_id: Uuid,

    /// Price the strategy requested
    pub intended_price: f64,

    /// Price actually filled at after slippage
    pub executed_price: f64,

    /// Difference between intended and executed
    pub slippage: f64,

    /// Cost of spread applied at fill
    pub spread_cost: f64,

    /// Broker commission charged
    pub commission: f64,

    /// Lot size filled
    pub size: f64,

    /// Buy or Sell
    pub direction: Direction,

    /// Carried forward from the signal
    pub reason: String,
}

/// The Execution Model refused the order.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRejectedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which order was rejected
    pub order_id: Uuid,

    /// Which signal caused this order
    pub signal_id: Uuid,

    /// Structured rejection code
    pub rejection_reason: RejectionReason,

    /// Human readable explanation for chart tooltip
    pub rejection_detail: String,
}

/// An active order was cancelled before it filled.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderCancelledEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which order was cancelled
    pub order_id: Uuid,

    /// Which signal caused this order
    pub signal_id: Uuid,

    /// Why it was cancelled
    pub cancellation_reason: CancellationReason,

    /// Human readable explanation
    pub cancellation_detail: String,
}

// ────────────────────────────────────────────────
// Position Events
// ────────────────────────────────────────────────

/// A new position was opened following an order fill.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionOpenedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Unique ID for this position
    pub position_id: Uuid,

    /// Which fill opened this position
    pub order_id: Uuid,

    /// Buy or Sell
    pub direction: Direction,

    /// Lot size
    pub size: f64,

    /// Price at which position opened
    pub entry_price: f64,

    /// Initial stop loss
    pub sl: Option<f64>,

    /// Initial take profit
    pub tp: Option<f64>,

    /// Always 0.0 at open — included for consistency
    pub pnl: f64,

    /// Position size as % of total equity
    pub pct_equity: f64,

    /// Position size as % of total balance
    pub pct_balance: f64,
}

/// An open position was modified.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionUpdatedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which position was updated
    pub position_id: Uuid,

    /// What kind of update occurred
    pub update_type: UpdateType,

    /// Stop loss before update
    pub previous_sl: Option<f64>,

    /// Stop loss after update
    pub new_sl: Option<f64>,

    /// Take profit before update
    pub previous_tp: Option<f64>,

    /// Take profit after update
    pub new_tp: Option<f64>,

    /// Current size after update
    pub size: f64,

    /// Unrealised PnL at time of update
    pub pnl: f64,

    /// Position size as % of equity
    pub pct_equity: f64,

    /// Position size as % of balance
    pub pct_balance: f64,
}

/// A position was fully closed. PnL is now realised.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionClosedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Which position closed
    pub position_id: Uuid,

    /// Which fill closed this position
    pub order_id: Uuid,

    /// Buy or Sell
    pub direction: Direction,

    /// Lot size closed
    pub size: f64,

    /// Where position was opened
    pub entry_price: f64,

    /// Where position was closed
    pub exit_price: f64,

    /// How the position closed
    pub exit_reason: ExitReason,

    /// Realised PnL for this trade
    pub pnl: f64,

    /// As % of equity at close time
    pub pct_equity: f64,

    /// As % of balance at close time
    pub pct_balance: f64,
}

// ────────────────────────────────────────────────
// Portfolio Events
// ────────────────────────────────────────────────

/// Complete snapshot of account financial state.
/// Emitted after every fill and at end of every bar.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortfolioSnapshotEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Total account balance
    pub balance: f64,

    /// Balance plus unrealised PnL
    pub equity: f64,

    /// Margin currently in use
    pub margin: f64,

    /// Equity minus margin
    pub free_margin: f64,

    /// Total floating PnL across all open positions
    pub unrealised_pnl: f64,

    /// Total closed PnL so far in this run
    pub realised_pnl: f64,

    /// Number of positions currently open
    pub open_positions: u32,
}

// ────────────────────────────────────────────────
// Run Events
// ────────────────────────────────────────────────

/// A run began. Everything needed to reproduce
/// this run exactly is captured here.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunStartedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Name of the strategy class
    pub strategy_name: String,

    /// Hash of the strategy file — ensures reproducibility
    pub strategy_version: String,

    /// Name of the CSV file
    pub dataset_name: String,

    /// Hash of the data file — ensures reproducibility
    pub dataset_hash: String,

    /// First bar timestamp in dataset
    pub data_start: DateTime<Utc>,

    /// Last bar timestamp in dataset
    pub data_end: DateTime<Utc>,

    /// Starting capital
    pub initial_balance: f64,

    /// Full config snapshot serialised as JSON string
    pub configuration: String,
}

/// The run finished successfully.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunCompletedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// When the run began
    pub start_time: DateTime<Utc>,

    /// When the run ended
    pub end_time: DateTime<Utc>,

    /// Total bars processed
    pub total_bars: u64,

    /// Total trades completed
    pub total_trades: u64,

    /// Ending account balance
    pub final_balance: f64,

    /// Ending equity
    pub final_equity: f64,

    /// Total PnL for the entire run
    pub realised_pnl: f64,
}

/// The run was interrupted by an error.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunErrorEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Structured error code
    pub error_type: ErrorType,

    /// Human readable description
    pub error_message: String,

    /// Full technical error detail
    pub stack_trace: String,

    /// The bar being processed when error occurred
    pub last_bar: Bar,
}

// ────────────────────────────────────────────────
// Annotation Events
// ────────────────────────────────────────────────

/// A user attached a journal note to an event
/// or time range. Never influences execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JournalEntryAddedEvent {
    #[serde(flatten)]
    pub metadata: EventMetadata,

    /// Unique ID for this annotation
    pub annotation_id: Uuid,

    /// The event this note is attached to — optional
    pub target_event_id: Option<Uuid>,

    /// Start of time range — optional
    pub target_time_start: Option<DateTime<Utc>>,

    /// End of time range — optional
    pub target_time_end: Option<DateTime<Utc>>,

    /// The note content
    pub text: String,

    /// Where this annotation came from
    pub source: AnnotationSource,
}

// ────────────────────────────────────────────────
// Master Event enum
// ────────────────────────────────────────────────

/// Every possible event in Observa wrapped in one type.
/// This is what the Event Bus passes around.
/// Components pattern match on this to handle
/// only the events they care about.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "event_type")]
pub enum Event {
    BarReceived(BarReceivedEvent),
    SignalEmitted(SignalEmittedEvent),
    IndicatorUpdated(IndicatorUpdatedEvent),
    OrderIntentCreated(OrderIntentCreatedEvent),
    OrderSubmitted(OrderSubmittedEvent),
    OrderFilled(OrderFilledEvent),
    OrderRejected(OrderRejectedEvent),
    OrderCancelled(OrderCancelledEvent),
    PositionOpened(PositionOpenedEvent),
    PositionUpdated(PositionUpdatedEvent),
    PositionClosed(PositionClosedEvent),
    PortfolioSnapshot(PortfolioSnapshotEvent),
    RunStarted(RunStartedEvent),
    RunCompleted(RunCompletedEvent),
    RunError(RunErrorEvent),
    JournalEntryAdded(JournalEntryAddedEvent),
}

impl Event {
    /// Returns the metadata from any event variant
    /// without needing to know the specific type
    pub fn metadata(&self) -> &EventMetadata {
        match self {
            Event::BarReceived(e)        => &e.metadata,
            Event::SignalEmitted(e)      => &e.metadata,
            Event::IndicatorUpdated(e)   => &e.metadata,
            Event::OrderIntentCreated(e) => &e.metadata,
            Event::OrderSubmitted(e)     => &e.metadata,
            Event::OrderFilled(e)        => &e.metadata,
            Event::OrderRejected(e)      => &e.metadata,
            Event::OrderCancelled(e)     => &e.metadata,
            Event::PositionOpened(e)     => &e.metadata,
            Event::PositionUpdated(e)    => &e.metadata,
            Event::PositionClosed(e)     => &e.metadata,
            Event::PortfolioSnapshot(e)  => &e.metadata,
            Event::RunStarted(e)         => &e.metadata,
            Event::RunCompleted(e)       => &e.metadata,
            Event::RunError(e)           => &e.metadata,
            Event::JournalEntryAdded(e)  => &e.metadata,
        }
    }

    /// Convenience — get event_id from any event
    pub fn event_id(&self) -> Uuid {
        self.metadata().event_id
    }

    /// Convenience — get run_id from any event
    pub fn run_id(&self) -> Uuid {
        self.metadata().run_id
    }

    /// Convenience — get timestamp from any event
    pub fn timestamp(&self) -> DateTime<Utc> {
        self.metadata().timestamp
    }
}

