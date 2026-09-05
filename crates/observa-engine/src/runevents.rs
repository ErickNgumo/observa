//! Canonical ordered runtime event model (OBS-0008).
//!
//! The Engine is the single authoritative producer of these events; they are
//! recorded in the Engine's own chronology and persisted as `events.jsonl`.
//!
//! * [`event_schema_version`] identifies the persisted event schema.
//! * [`EngineEvent`] is the envelope: a strictly increasing `event_seq` plus a
//!   typed, internally-tagged payload (`"type": "order_created", ...`).

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use observa_core::types::{Direction, ExitReason, OrderKind};

/// Version of the persisted event schema.
pub const EVENT_SCHEMA_VERSION: u32 = 1;

/// Version of the persisted run description (`run.json`).
pub const RUN_SCHEMA_VERSION: u32 = 1;

/// Version of the persisted metrics schema (`metrics.json`).
pub const METRICS_SCHEMA_VERSION: u32 = 1;

/// Structured category for order rejections (OBS-0008 §46).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RejectionCategory {
    /// Execution-domain validation failure (quantity, price, levels, model).
    ExecutionDomain,
    /// Financial/portfolio rejection (e.g. insufficient margin).
    Financial,
    /// Strategy/runtime failure surfaced on an order path.
    Runtime,
}

/// Structured category for run-level failures.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunFailureCategory {
    Configuration,
    Data,
    Strategy,
    Execution,
    Portfolio,
    Runtime,
}

/// One canonical event in a run's history.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EngineEvent {
    /// Strictly increasing, engine-assigned total event sequence.
    pub event_seq: u64,
    /// Typed payload (serialized flat beside `event_seq`).
    #[serde(flatten)]
    pub payload: EngineEventPayload,
}

/// Typed event payloads for the MVP runtime (OBS-0008 §4).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum EngineEventPayload {
    /// The run started (resolved config is persisted separately in run.json).
    RunStarted { strategy_name: String },
    /// The run completed successfully.
    RunCompleted {
        total_bars: usize,
        final_balance: f64,
        final_equity: f64,
        open_positions_remaining: usize,
    },
    /// The run failed after starting (persisted in failure artifacts).
    RunFailed {
        category: RunFailureCategory,
        message: String,
    },
    /// Strategy initialization succeeded.
    StrategyInitialized {},
    /// A strategy lifecycle error was observed (run will fail).
    StrategyError { message: String },
    /// Strategy teardown finished.
    StrategyTeardown {},
    /// A bar entered the replay chronology (dataset reference, not a copy of
    /// the OHLC series).
    BarProcessed {
        bar_index: usize,
        timestamp: DateTime<Utc>,
    },
    /// The strategy returned N signals for a bar.
    StrategyDecision {
        bar_index: usize,
        signal_count: usize,
    },
    /// A strategy-generated order was created.
    OrderCreated {
        order_seq: u64,
        order_type: OrderKind,
        side: Direction,
        quantity_lots: f64,
        created_bar: usize,
    },
    /// A created order is now waiting (queued market or resting limit/stop).
    OrderPending { order_seq: u64 },
    /// A resting order's trigger condition was met.
    OrderTriggered { order_seq: u64, bar_index: usize },
    /// An order filled (market entries/exits, resting entries).
    OrderFilled {
        order_seq: u64,
        side: Direction,
        quantity_lots: f64,
        raw_reference: f64,
        executed_price: f64,
        spread_applied: f64,
        slippage_applied: f64,
        commission_amount: f64,
        bar_index: usize,
        timestamp: DateTime<Utc>,
    },
    /// An order was rejected with a structured category and reason.
    OrderRejected {
        order_seq: u64,
        category: RejectionCategory,
        reason: String,
        bar_index: usize,
    },
    /// An unfilled order expired at dataset end.
    OrderExpired { order_seq: u64 },
    /// A position was opened.
    PositionOpened {
        position_id: Uuid,
        order_seq: Option<u64>,
        side: Direction,
        quantity_lots: f64,
        entry_price: f64,
        stop_loss: Option<f64>,
        take_profit: Option<f64>,
        bar_index: usize,
        timestamp: DateTime<Utc>,
    },
    /// A position was fully closed.
    PositionClosed {
        position_id: Uuid,
        side: Direction,
        quantity_lots: f64,
        entry_price: f64,
        exit_price: f64,
        exit_reason: ExitReason,
        gross_realized_pnl: f64,
        total_commission: f64,
        net_realized_pnl: f64,
        bar_index: usize,
        timestamp: DateTime<Utc>,
    },
    /// End-of-bar mark-to-market portfolio state (all open positions).
    PortfolioSnapshot {
        bar_index: usize,
        timestamp: DateTime<Utc>,
        balance: f64,
        equity: f64,
        used_margin: f64,
        free_margin: f64,
        unrealised_pnl: f64,
        realised_pnl: f64,
        commissions_paid: f64,
        open_positions: usize,
    },
}
