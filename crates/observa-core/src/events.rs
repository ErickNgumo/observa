//! The complete event taxonomy for Observa.
//!
//! Every meaningful occurrence in the system emits one of these events.
//! Events are immutable once created — they are the system of record.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use crate::bar::Bar;
use crate::types::{Direction, LotSize, Price};

// ── Market Events ─────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BarReceivedEvent {
    pub event_id: Uuid,
    pub run_id:   Uuid,
    pub bar:      Bar,
}

impl BarReceivedEvent {
    pub fn new(run_id: Uuid, bar: Bar) -> Self {
        Self { event_id: Uuid::new_v4(), run_id, bar }
    }
}

// ── Strategy Events ───────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalEmittedEvent {
    pub event_id:       Uuid,
    pub run_id:         Uuid,
    pub timestamp:      DateTime<Utc>,
    pub signal_id:      Uuid,
    pub direction:      Direction,
    pub size:           LotSize,
    pub intended_price: Price,
    pub sl:             Option<Price>,
    pub tp:             Option<Price>,
    pub reason:         String,
}

// ── Order Events ──────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderIntentCreatedEvent {
    pub event_id:       Uuid,
    pub run_id:         Uuid,
    pub timestamp:      DateTime<Utc>,
    pub order_id:       Uuid,
    pub signal_id:      Uuid,
    pub direction:      Direction,
    pub size:           LotSize,
    pub intended_price: Price,
    pub sl:             Option<Price>,
    pub tp:             Option<Price>,
    pub reason:         String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderSubmittedEvent {
    pub event_id:  Uuid,
    pub run_id:    Uuid,
    pub timestamp: DateTime<Utc>,
    pub order_id:  Uuid,
    pub signal_id: Uuid,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderFilledEvent {
    pub event_id:       Uuid,
    pub run_id:         Uuid,
    pub timestamp:      DateTime<Utc>,
    pub order_id:       Uuid,
    pub signal_id:      Uuid,
    pub intended_price: Price,
    pub executed_price: Price,
    pub slippage:       Price,
    pub spread_cost:    Price,
    pub commission:     Price,
    pub size:           LotSize,
    pub direction:      Direction,
    pub reason:         String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RejectionReason {
    InvalidStop,
    InvalidTp,
    InvalidSize,
    InsufficientCapital,
    PriceOutOfRange,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRejectedEvent {
    pub event_id:         Uuid,
    pub run_id:           Uuid,
    pub timestamp:        DateTime<Utc>,
    pub order_id:         Uuid,
    pub signal_id:        Uuid,
    pub rejection_reason: RejectionReason,
    pub rejection_detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum CancellationReason {
    InsufficientFunds,
    CancelledByStrategy,
    Expired,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderCancelledEvent {
    pub event_id:            Uuid,
    pub run_id:              Uuid,
    pub timestamp:           DateTime<Utc>,
    pub order_id:            Uuid,
    pub signal_id:           Uuid,
    pub cancellation_reason: CancellationReason,
    pub cancellation_detail: String,
}

// ── Position Events ───────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionOpenedEvent {
    pub event_id:    Uuid,
    pub run_id:      Uuid,
    pub timestamp:   DateTime<Utc>,
    pub position_id: Uuid,
    pub order_id:    Uuid,
    pub direction:   Direction,
    pub size:        LotSize,
    pub entry_price: Price,
    pub sl:          Option<Price>,
    pub tp:          Option<Price>,
    pub pnl:         f64,
    pub pct_equity:  f64,
    pub pct_balance: f64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum UpdateType {
    SlAdjusted,
    TpAdjusted,
    PartialClose,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionUpdatedEvent {
    pub event_id:    Uuid,
    pub run_id:      Uuid,
    pub timestamp:   DateTime<Utc>,
    pub position_id: Uuid,
    pub update_type: UpdateType,
    pub previous_sl: Option<Price>,
    pub new_sl:      Option<Price>,
    pub previous_tp: Option<Price>,
    pub new_tp:      Option<Price>,
    pub size:        LotSize,
    pub pnl:         f64,
    pub pct_equity:  f64,
    pub pct_balance: f64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExitReason {
    TakeProfit,
    StopLoss,
    Signal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionClosedEvent {
    pub event_id:    Uuid,
    pub run_id:      Uuid,
    pub timestamp:   DateTime<Utc>,
    pub position_id: Uuid,
    pub order_id:    Uuid,
    pub direction:   Direction,
    pub size:        LotSize,
    pub entry_price: Price,
    pub exit_price:  Price,
    pub exit_reason: ExitReason,
    pub pnl:         f64,
    pub pct_equity:  f64,
    pub pct_balance: f64,
}

// ── Portfolio Events ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortfolioSnapshotEvent {
    pub event_id:       Uuid,
    pub run_id:         Uuid,
    pub timestamp:      DateTime<Utc>,
    pub balance:        f64,
    pub equity:         f64,
    pub margin:         f64,
    pub free_margin:    f64,
    pub unrealised_pnl: f64,
    pub realised_pnl:   f64,
    pub open_positions: u32,
}

// ── Run Events ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunConfiguration {
    pub spread:          f64,
    pub slippage:        f64,
    pub commission:      f64,
    pub initial_balance: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunStartedEvent {
    pub event_id:         Uuid,
    pub run_id:           Uuid,
    pub timestamp:        DateTime<Utc>,
    pub strategy_name:    String,
    pub strategy_version: String,
    pub dataset_name:     String,
    pub dataset_hash:     String,
    pub start_time:       DateTime<Utc>,
    pub end_time:         DateTime<Utc>,
    pub initial_balance:  f64,
    pub configuration:    RunConfiguration,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunCompletedEvent {
    pub event_id:      Uuid,
    pub run_id:        Uuid,
    pub timestamp:     DateTime<Utc>,
    pub start_time:    DateTime<Utc>,
    pub end_time:      DateTime<Utc>,
    pub total_bars:    u64,
    pub total_trades:  u64,
    pub final_balance: f64,
    pub final_equity:  f64,
    pub realised_pnl:  f64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ErrorType {
    StrategyException,
    DataCorruption,
    EngineFault,
    ResourceLimitExceeded,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunErrorEvent {
    pub event_id:      Uuid,
    pub run_id:        Uuid,
    pub timestamp:     DateTime<Utc>,
    pub error_type:    ErrorType,
    pub error_message: String,
    pub stack_trace:   String,
    pub last_bar:      Option<Bar>,
}

// ── Annotation Events ─────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnnotationSource { Strategy, Ui }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JournalEntryAddedEvent {
    pub event_id:          Uuid,
    pub run_id:            Uuid,
    pub timestamp:         DateTime<Utc>,
    pub annotation_id:     Uuid,
    pub target_event_id:   Option<Uuid>,
    pub target_time_start: Option<DateTime<Utc>>,
    pub target_time_end:   Option<DateTime<Utc>>,
    pub text:              String,
    pub source:            AnnotationSource,
}

// ── The Event Enum ────────────────────────────────────────────────

/// Every event in Observa wrapped in one enum.
/// The Event Bus routes values of this type.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Event {
    BarReceived(BarReceivedEvent),
    SignalEmitted(SignalEmittedEvent),
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
    pub fn run_id(&self) -> Uuid {
        match self {
            Event::BarReceived(e)        => e.run_id,
            Event::SignalEmitted(e)      => e.run_id,
            Event::OrderIntentCreated(e) => e.run_id,
            Event::OrderSubmitted(e)     => e.run_id,
            Event::OrderFilled(e)        => e.run_id,
            Event::OrderRejected(e)      => e.run_id,
            Event::OrderCancelled(e)     => e.run_id,
            Event::PositionOpened(e)     => e.run_id,
            Event::PositionUpdated(e)    => e.run_id,
            Event::PositionClosed(e)     => e.run_id,
            Event::PortfolioSnapshot(e)  => e.run_id,
            Event::RunStarted(e)         => e.run_id,
            Event::RunCompleted(e)       => e.run_id,
            Event::RunError(e)           => e.run_id,
            Event::JournalEntryAdded(e)  => e.run_id,
        }
    }
}
