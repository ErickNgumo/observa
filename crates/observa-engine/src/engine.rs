//! The canonical Observa replay engine (OBS-0007).
//!
//! `observa-engine` is the **single authoritative owner of the backtest
//! runtime loop**. The Engine coordinates, in a fixed deterministic per-bar
//! chronology, the three verified authorities:
//!
//! * configuration/domain vocabulary — `observa_core::config` (OBS-0004);
//! * financial/position accounting — `observa_portfolio` (OBS-0005);
//! * order/execution semantics — `observa_execution::semantics` (OBS-0006).
//!
//! The Engine itself performs **no** independent economic math: it asks the
//! execution semantics layer what price/result occurred, then asks the
//! PortfolioManager what that means financially. The CLI and future
//! Python/Jupyter layers invoke [`Engine::run`]; they do not reproduce the
//! loop.

use chrono::{DateTime, Utc};
use uuid::Uuid;

use observa_core::bar::Bar;
use observa_core::config::{BacktestConfig, CommissionConfig, FillMode, InstrumentConfig};
use observa_core::drawings::DrawingInstruction;
use observa_core::types::{Direction, ExitReason, OrderKind, OrderState};
use observa_execution::semantics::{
    self, ExecutionSettings, OrderSpec, Outcome, ProtectiveLevels, ProtectiveOutcome,
};
use observa_portfolio::portfolio::{
    ClosePositionReport, EndOfRunState, OpenPositionRequest, PortfolioManager, PortfolioSettings,
    PortfolioSnapshot,
};

use crate::error::EngineError;
use crate::runevents::{EngineEvent, EngineEventPayload, RejectionCategory, RunFailureCategory};
use crate::strategy::{OpenPositionView, PortfolioView, Strategy, StrategySignal};

// ────────────────────────────────────────────────
// Runtime records
// ────────────────────────────────────────────────

/// Why a fill occurred. Strategy order kinds are MARKET/LIMIT/STOP; protective
/// SL/TP are position-attached instructions (conceptually separate from
/// generic orders, OBS-0006 §19).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FillReason {
    MarketEntry,
    MarketClose,
    LimitEntry,
    StopEntry,
    StopLoss,
    TakeProfit,
}

/// One execution fill, in deterministic chronological order.
#[derive(Debug, Clone)]
pub struct RuntimeFill {
    /// Bar on which the fill occurred.
    pub bar_index: usize,
    /// Strategy-order sequence (present for strategy-generated orders;
    /// `None` for protective SL/TP executions which are ordered by the fixed
    /// per-bar protective stage).
    pub order_seq: Option<u64>,
    /// Why this fill happened.
    pub reason: FillReason,
    /// Execution side (entry side for opens; exit side for closes).
    pub side: Direction,
    /// Quantity in lots.
    pub quantity_lots: f64,
    /// Raw reference price before adjustments.
    pub raw_reference: f64,
    /// Final executed price (includes spread/slippage where applicable).
    pub executed_price: f64,
    /// Half-spread applied (market-style only).
    pub spread_applied: f64,
    /// Adverse slippage applied (market-style only).
    pub slippage_applied: f64,
    /// Commission amount supplied to the portfolio for this fill.
    pub commission_amount: f64,
    /// Position affected (opened for entries; closed for exits).
    pub position_id: Option<Uuid>,
    /// Market timestamp of the fill bar.
    pub timestamp: DateTime<Utc>,
}

/// Lifecycle record of one strategy-generated order (market/limit/stop/close).
/// Protective executions are recorded through fills/trades and position state,
/// not as generic orders.
#[derive(Debug, Clone)]
pub struct OrderRecord {
    /// Strictly-increasing engine-assigned creation sequence.
    pub seq: u64,
    /// Generic order kind requested.
    pub order_type: OrderKind,
    /// Requested side.
    pub side: Direction,
    /// Quantity in lots.
    pub quantity_lots: f64,
    /// Bar on which the order was created.
    pub created_bar: usize,
    /// Current lifecycle state.
    pub state: OrderState,
    /// Position opened/closed by this order, when applicable.
    pub position_id: Option<Uuid>,
    /// Bar on which it filled, when applicable.
    pub filled_bar: Option<usize>,
    /// Execution price when filled.
    pub executed_price: Option<f64>,
    /// Structured rejection reason, when rejected.
    pub rejection: Option<String>,
}

/// A fully closed trade (position close) — the raw material for trade
/// statistics. Realized P&L values come from the portfolio (OBS-0005).
#[derive(Debug, Clone)]
pub struct TradeRecord {
    /// Bar on which the position closed.
    pub bar_index: usize,
    /// The closed position's ticket.
    pub position_id: Uuid,
    /// Original position side (long/short).
    pub direction: Direction,
    /// Quantity closed.
    pub quantity_lots: f64,
    /// Entry price.
    pub entry_price: f64,
    /// Exit price.
    pub exit_price: f64,
    /// Why it closed.
    pub exit_reason: ExitReason,
    /// Gross realized P&L (before commission).
    pub gross_realized_pnl: f64,
    /// Total commission booked against the position.
    pub total_commission: f64,
    /// Net realized P&L (gross − total commission).
    pub net_realized_pnl: f64,
}

/// Per-bar runtime record: end-of-bar canonical portfolio snapshot plus any
/// drawings the strategy produced on that bar.
#[derive(Debug, Clone)]
pub struct BarRecord {
    /// Zero-based bar index.
    pub bar_index: usize,
    /// Bar timestamp.
    pub timestamp: DateTime<Utc>,
    /// End-of-bar mark-to-market snapshot (all open positions).
    pub snapshot: PortfolioSnapshot,
    /// Drawings emitted by the strategy for this bar.
    pub drawings: Vec<DrawingInstruction>,
}

/// Structured in-memory result of a completed run.
///
/// The canonical runtime history is [`RunResult::events`] — a strictly
/// increasing, ordered event sequence (persisted as `events.jsonl`). Every
/// other field is derived runtime bookkeeping recorded alongside it.
#[derive(Debug, Clone)]
pub struct RunResult {
    /// Run id.
    pub run_id: Uuid,
    /// Total bars processed.
    pub total_bars: usize,
    /// Canonical ordered runtime event history (EventSeq 0..n), source of truth.
    pub events: Vec<EngineEvent>,
    /// Per-bar runtime records (snapshot + drawings).
    pub bars: Vec<BarRecord>,
    /// All execution fills in chronological order.
    pub fills: Vec<RuntimeFill>,
    /// Strategy-order lifecycle records in creation order.
    pub orders: Vec<OrderRecord>,
    /// Fully closed trades.
    pub trades: Vec<TradeRecord>,
    /// End-of-run financial state (open positions are NOT force-closed).
    pub final_state: EndOfRunState,
}

// ────────────────────────────────────────────────
// Internal scheduling state
// ────────────────────────────────────────────────

/// A MARKET order queued for execution at the next bar's open
/// (FillMode::NextBarOpen), or a close-by-ticket market order queued the same
/// way.
#[derive(Debug, Clone)]
struct QueuedMarket {
    seq: u64,
    /// For entries: the side to open. For closes: derived at execution from
    /// the target position (this field holds `Close` until resolved).
    side: Direction,
    quantity_lots: f64,
    stop_loss: Option<f64>,
    take_profit: Option<f64>,
    /// Position ticket for close-by-ticket market orders.
    ticket: Option<Uuid>,
}

/// A resting LIMIT/STOP order persisting across bars.
///
/// Strategy-supplied protective levels are carried through the whole pending
/// lifecycle and passed to the canonical portfolio open when the order fills —
/// they are never silently discarded.
#[derive(Debug, Clone)]
struct PendingOrder {
    seq: u64,
    order_type: OrderKind,
    side: Direction,
    quantity_lots: f64,
    /// Limit or stop trigger price.
    trigger_price: f64,
    /// Protective stop-loss attached at open (from the original signal).
    stop_loss: Option<f64>,
    /// Protective take-profit attached at open (from the original signal).
    take_profit: Option<f64>,
    created_bar: usize,
}

// ────────────────────────────────────────────────
// Engine
// ────────────────────────────────────────────────

/// The canonical replay engine: one loop, one execution path, one portfolio
/// authority.
pub struct Engine {
    run_id: Uuid,
    /// Resolved run configuration (dataset + strategy present).
    config: BacktestConfig,
    portfolio: PortfolioManager,
    exec_settings: ExecutionSettings,
    fill_mode: FillMode,
    commission: CommissionConfig,
    instrument: InstrumentConfig,

    // Runtime state (fresh per Engine instance; a new Engine per run).
    next_seq: u64,
    queued_market: Vec<QueuedMarket>,
    pending_orders: Vec<PendingOrder>,
    order_log: Vec<OrderRecord>,
    fills: Vec<RuntimeFill>,
    trades: Vec<TradeRecord>,
    bar_records: Vec<BarRecord>,

    // Canonical ordered event history (single-writer: only the Engine appends).
    events: Vec<EngineEvent>,
    next_event_seq: u64,
    /// Single-run guard: runtime state is never reusable across runs.
    started: bool,
}

impl Engine {
    /// Creates an Engine from a **resolved** `BacktestConfig`
    /// (`dataset` and `strategy` metadata must be present and the config must
    /// validate).
    pub fn new(config: BacktestConfig) -> Result<Self, EngineError> {
        config
            .validate()
            .map_err(|e| EngineError::InvalidConfiguration(e.to_string()))?;
        if !config.is_resolved() {
            return Err(EngineError::InvalidConfiguration(
                "resolved configuration requires dataset and strategy metadata".into(),
            ));
        }

        let settings = PortfolioSettings {
            initial_cash: config.account.starting_balance,
            leverage: config.account.leverage,
            contract_size: config.instrument.contract_size,
            symbol: config.instrument.symbol.clone(),
            commission_mode: config.execution.commission.mode,
            legacy_commission: 0.0,
            legacy_slippage: 0.0,
        };
        let portfolio =
            PortfolioManager::try_new(Uuid::new_v4(), settings).map_err(EngineError::Portfolio)?;

        Ok(Self {
            run_id: Uuid::new_v4(),
            exec_settings: ExecutionSettings::from_config(&config.execution),
            fill_mode: config.execution.fill_mode,
            commission: config.execution.commission.clone(),
            instrument: config.instrument.clone(),
            portfolio,
            config,
            next_seq: 0,
            queued_market: Vec::new(),
            pending_orders: Vec::new(),
            order_log: Vec::new(),
            fills: Vec::new(),
            trades: Vec::new(),
            bar_records: Vec::new(),
            events: Vec::new(),
            next_event_seq: 0,
            started: false,
        })
    }

    /// The portfolio behind this Engine (financial authority).
    pub fn portfolio(&self) -> &PortfolioManager {
        &self.portfolio
    }

    /// The resolved run configuration this Engine was built from.
    pub fn config(&self) -> &BacktestConfig {
        &self.config
    }

    /// The canonical ordered event history emitted so far. Empty before a
    /// run starts; after a failed run it retains every event emitted up to
    /// the failure (used for failure-artifact persistence).
    pub fn events(&self) -> &[EngineEvent] {
        &self.events
    }

    /// Appends one canonical event at the next strictly-increasing EventSeq.
    fn emit(&mut self, payload: EngineEventPayload) -> Result<(), EngineError> {
        let seq = self.next_event_seq;
        self.next_event_seq = self
            .next_event_seq
            .checked_add(1)
            .ok_or(EngineError::EventSequenceOverflow)?;
        self.events.push(EngineEvent {
            event_seq: seq,
            payload,
        });
        Ok(())
    }

    /// Emits the canonical fill + opened events for one strategy-order entry
    /// (queued-market, bar-close market, or resting limit/stop).
    fn emit_entry_events(
        &mut self,
        bar_index: usize,
        seq: u64,
        side: Direction,
        quantity_lots: f64,
        fill: &semantics::Fill,
        stop_loss: Option<f64>,
        take_profit: Option<f64>,
        position_id: Uuid,
        timestamp: DateTime<Utc>,
    ) -> Result<(), EngineError> {
        self.emit(EngineEventPayload::OrderFilled {
            order_seq: seq,
            side,
            quantity_lots,
            raw_reference: fill.raw_reference,
            executed_price: fill.executed_price,
            spread_applied: fill.spread_applied,
            slippage_applied: fill.slippage_applied,
            commission_amount: self.commission_amount(quantity_lots),
            bar_index,
            timestamp,
        })?;
        self.emit(EngineEventPayload::PositionOpened {
            position_id,
            order_seq: Some(seq),
            side,
            quantity_lots,
            entry_price: fill.executed_price,
            stop_loss,
            take_profit,
            bar_index,
            timestamp,
        })?;
        Ok(())
    }

    /// Runs the complete backtest.
    ///
    /// The same instance is single-run: runtime state (sequences, pending
    /// orders, event history) is never reusable across runs — create a fresh
    /// Engine per run. On failure the partial canonical event history stays
    /// on the Engine (`events()`) so the caller can persist failure artifacts.
    ///
    /// # Deterministic per-bar chronology
    ///
    /// For each bar `B` (index `i`):
    /// 1. **Scheduled work** — MARKET orders queued from the previous bar
    ///    execute at `B`'s open (`FillMode::NextBarOpen`), in ascending
    ///    creation order; each fill is financially accepted by the portfolio
    ///    (`can_open`/`open_position` for entries, explicit-ticket
    ///    `close_position` for closes).
    ///
    ///    After this stage the set of **protective-eligible positions for bar
    ///    `B`** is captured: positions already open before `B` plus positions
    ///    opened at `B`'s open. Positions opened later in `B` (intrabar
    ///    resting-order fills or `BAR_CLOSE` strategy fills) are excluded —
    ///    OHLC cannot reveal whether a protective level was reached before or
    ///    after an intrabar entry, so they become eligible only on the next
    ///    bar.
    /// 2. **Resting generic orders** — LIMIT/STOP orders created on earlier
    ///    bars are evaluated against `B` (OBS-0006 gap + intrabar trigger
    ///    semantics), in ascending creation order. Strategy-supplied SL/TP are
    ///    carried into the positions opened here. Such intrabar fills are NOT
    ///    protective-evaluated on `B` itself.
    /// 3. **Protective exits** — SL/TP of exactly the positions captured in
    ///    step 1 are evaluated with the OBS-0006 opening-gap precedence and
    ///    SL-first intrabar convention, per position in creation order; each
    ///    hit closes that exact position by ticket.
    /// 4. **Strategy observation** — the completed bar `B` and a read-only
    ///    portfolio view (all open positions, valued at `B`'s close) are
    ///    presented to the strategy with strictly-prior history.
    /// 5. **New strategy intents** — signals become canonical orders
    ///    (validated; rejected orders recorded). MARKET orders execute at
    ///    `B`'s close under `BAR_CLOSE` or queue for `B+1`'s open under
    ///    `NEXT_BAR_OPEN`. LIMIT/STOP orders rest (with their SL/TP) and are
    ///    first evaluated on later bars. Close signals require an explicit
    ///    ticket.
    /// 6. **End of bar** — history advances and an end-of-bar mark-to-market
    ///    portfolio snapshot (all positions) is recorded.
    ///
    /// All execution work within a stage is ordered by the engine-assigned
    /// strictly-increasing `OrderSeq`, and every transition is recorded as a
    /// canonical event with a strictly-increasing `EventSeq`. No wall-clock
    /// time, UUID ordering, hash iteration or thread scheduling influences
    /// economics.
    pub fn run(
        &mut self,
        bars: &[Bar],
        strategy: &mut dyn Strategy,
    ) -> Result<RunResult, EngineError> {
        if self.started {
            return Err(EngineError::InvalidState(
                "this Engine instance has already been run; create a fresh Engine per run".into(),
            ));
        }
        self.started = true;
        if bars.is_empty() {
            return Err(EngineError::NoDataLoaded);
        }
        // Require strictly increasing bar timestamps (the data loader already
        // enforces this; the Engine re-checks so replay order is never
        // incidental).
        if bars.windows(2).any(|w| w[1].timestamp <= w[0].timestamp) {
            return Err(EngineError::InvalidState(
                "bars must be in strictly increasing chronological order".into(),
            ));
        }

        self.emit(EngineEventPayload::RunStarted {
            strategy_name: self
                .config
                .strategy
                .as_ref()
                .map(|s| s.name.clone())
                .unwrap_or_default(),
        })?;

        // Strategy lifecycle + replay. The body is isolated so any failure
        // appends a canonical RunFailed event while the partial history stays
        // on the Engine for failure-artifact persistence.
        let body = (|| -> Result<(), EngineError> {
            let params = self.config.strategy.as_ref().map(|s| s.parameters.clone());
            strategy.initialize_with_params(params.as_ref());
            if let Some(msg) = strategy.take_strategy_error() {
                self.emit(EngineEventPayload::StrategyError {
                    message: msg.clone(),
                })?;
                return Err(EngineError::StrategyFailure {
                    bar_index: None,
                    message: msg,
                });
            }
            self.emit(EngineEventPayload::StrategyInitialized {})?;

            let mut history: Vec<Bar> = Vec::new();
            for (index, bar) in bars.iter().enumerate() {
                // Strategy history only contains strictly prior bars: the
                // current bar is appended AFTER the strategy observed it.
                self.run_bar(index, bar, &history, strategy)?;
                history.push(bar.clone());
            }

            // Teardown (errors are surfaced, never swallowed).
            strategy.teardown();
            if let Some(msg) = strategy.take_strategy_error() {
                self.emit(EngineEventPayload::StrategyError {
                    message: msg.clone(),
                })?;
                return Err(EngineError::StrategyFailure {
                    bar_index: Some(bars.len().saturating_sub(1)),
                    message: msg,
                });
            }

            // Dataset-end handling: queued NEXT_BAR_OPEN markets on the final
            // bar and any resting LIMIT/STOP orders are expired — never
            // fabricated.
            self.expire_unfilled_orders()?;
            Ok(())
        })();

        if let Err(error) = body {
            let (category, message) = run_failure(&error);
            self.emit(EngineEventPayload::RunFailed { category, message })?;
            return Err(error);
        }

        let last_close = bars.last().expect("bars non-empty").close;
        let final_state = self.portfolio.end_of_run_state(last_close);

        self.emit(EngineEventPayload::RunCompleted {
            total_bars: bars.len(),
            final_balance: final_state.final_balance,
            final_equity: final_state.final_equity,
            open_positions_remaining: final_state.open_positions_remaining,
        })?;

        Ok(RunResult {
            run_id: self.run_id,
            total_bars: bars.len(),
            events: std::mem::take(&mut self.events),
            bars: std::mem::take(&mut self.bar_records),
            fills: std::mem::take(&mut self.fills),
            orders: std::mem::take(&mut self.order_log),
            trades: std::mem::take(&mut self.trades),
            final_state,
        })
    }

    fn run_bar(
        &mut self,
        index: usize,
        bar: &Bar,
        history: &[Bar],
        strategy: &mut dyn Strategy,
    ) -> Result<(), EngineError> {
        self.emit(EngineEventPayload::BarProcessed {
            bar_index: index,
            timestamp: bar.timestamp,
        })?;

        // ── Stage 1 — scheduled NEXT_BAR_OPEN work at bar open ──────────────
        let queued = std::mem::take(&mut self.queued_market);
        for market in queued {
            self.execute_queued_market(index, bar, market)?;
        }

        // ── Protective-eligibility snapshot (before resting-order fills) ────
        // Positions eligible for protective evaluation THIS bar are:
        //   * positions already open before this bar; and
        //   * positions opened during stage 1 at this bar's OPEN.
        // Positions filled intrabar later in this bar (stage-2 resting LIMIT/
        // STOP orders, and BAR_CLOSE strategy fills) are NOT eligible until
        // the next bar, because OHLC cannot reveal whether the protective
        // level was reached before or after the intrabar entry.
        let protected: Vec<Uuid> = self
            .portfolio
            .positions()
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.position_id)
            .collect();

        // ── Stage 2 — resting generic LIMIT/STOP orders ─────────────────────
        let rested = std::mem::take(&mut self.pending_orders);
        let mut still_pending = Vec::new();
        for order in rested {
            let seq = order.seq;
            match self.evaluate_pending(index, bar, order)? {
                PendingEval::Filled => {}
                PendingEval::StillPending(o) => still_pending.push(o),
                PendingEval::Rejected(msg) => {
                    self.reject_order(seq, index, RejectionCategory::ExecutionDomain, &msg)?;
                }
            }
        }
        self.pending_orders = still_pending;

        // ── Stage 3 — protective SL/TP over the pre-resting snapshot ────────
        // Only the positions captured before stage 3 are evaluated. An entry
        // filled intrabar by a resting order is never stopped out / taken
        // profit on the same bar using its full high/low (some of that range
        // may have occurred before the entry). Such positions become
        // protective-eligible starting with the next bar.
        for position_id in protected {
            let pos = match self.portfolio.position(&position_id) {
                Some(p) if p.is_open() => p.clone(),
                _ => continue,
            };
            let levels = ProtectiveLevels {
                stop_loss: pos.stop_loss,
                take_profit: pos.take_profit,
            };
            match semantics::protective_outcome(&self.exec_settings, bar, pos.direction, &levels) {
                ProtectiveOutcome::None => {}
                ProtectiveOutcome::Executed(kind, fill) => {
                    let reason = match kind {
                        observa_core::types::ProtectiveKind::StopLoss => ExitReason::StopLoss,
                        observa_core::types::ProtectiveKind::TakeProfit => ExitReason::TakeProfit,
                    };
                    let fill_reason = match kind {
                        observa_core::types::ProtectiveKind::StopLoss => FillReason::StopLoss,
                        observa_core::types::ProtectiveKind::TakeProfit => FillReason::TakeProfit,
                    };
                    let exit_side = opposite_side(pos.direction);
                    self.record_fill(
                        index,
                        None,
                        fill_reason,
                        exit_side,
                        pos.quantity_lots,
                        &fill,
                        Some(position_id),
                        bar.timestamp,
                    );
                    self.execute_close_by_id(
                        index,
                        position_id,
                        pos.quantity_lots,
                        fill.executed_price,
                        reason,
                        bar.timestamp,
                    )?;
                }
            }
        }

        // ── Stage 4 — strategy observation ──────────────────────────────────
        let view = self.build_portfolio_view(bar);
        let signals = strategy.on_bar(bar, &view, history);
        if let Some(msg) = strategy.take_strategy_error() {
            self.emit(EngineEventPayload::StrategyError {
                message: msg.clone(),
            })?;
            return Err(EngineError::StrategyFailure {
                bar_index: Some(index),
                message: msg,
            });
        }
        let drawings = strategy.take_drawings();
        self.emit(EngineEventPayload::StrategyDecision {
            bar_index: index,
            signal_count: signals.len(),
        })?;

        // ── Stage 5 — convert strategy intents into canonical orders ────────
        for signal in signals {
            self.process_signal(index, bar, signal)?;
        }

        // ── Stage 6 — end-of-bar snapshot ───────────────────────────────────
        let snapshot = self.portfolio.snapshot(bar.close, bar.timestamp);
        self.emit(EngineEventPayload::PortfolioSnapshot {
            bar_index: index,
            timestamp: bar.timestamp,
            balance: snapshot.balance,
            equity: snapshot.equity,
            used_margin: snapshot.used_margin,
            free_margin: snapshot.free_margin,
            unrealised_pnl: snapshot.unrealised_pnl,
            realised_pnl: snapshot.realised_pnl,
            commissions_paid: snapshot.commissions_paid,
            open_positions: snapshot.open_positions.len(),
        })?;
        self.bar_records.push(BarRecord {
            bar_index: index,
            timestamp: bar.timestamp,
            snapshot,
            drawings,
        });

        Ok(())
    }

    // ── Order sequence ───────────────────────────

    fn next_seq(&mut self) -> Result<u64, EngineError> {
        let seq = self.next_seq;
        self.next_seq = self
            .next_seq
            .checked_add(1)
            .ok_or(EngineError::OrderSequenceOverflow)?;
        Ok(seq)
    }

    fn register_order(
        &mut self,
        created_bar: usize,
        order_type: OrderKind,
        side: Direction,
        quantity_lots: f64,
    ) -> Result<u64, EngineError> {
        let seq = self.next_seq()?;
        debug_assert_eq!(self.order_log.len() as u64, seq);
        self.order_log.push(OrderRecord {
            seq,
            order_type,
            side,
            quantity_lots,
            created_bar,
            state: OrderState::Created,
            position_id: None,
            filled_bar: None,
            executed_price: None,
            rejection: None,
        });
        self.emit(EngineEventPayload::OrderCreated {
            order_seq: seq,
            order_type,
            side,
            quantity_lots,
            created_bar,
        })?;
        Ok(seq)
    }

    fn order_mut(&mut self, seq: u64) -> &mut OrderRecord {
        debug_assert!(seq < self.order_log.len() as u64);
        let rec = &mut self.order_log[seq as usize];
        debug_assert_eq!(rec.seq, seq);
        rec
    }

    /// Marks an order rejected and appends the canonical rejection event.
    fn reject_order(
        &mut self,
        seq: u64,
        bar_index: usize,
        category: RejectionCategory,
        reason: &str,
    ) -> Result<(), EngineError> {
        let rec = self.order_mut(seq);
        rec.state = OrderState::Rejected;
        rec.rejection = Some(reason.to_string());
        self.emit(EngineEventPayload::OrderRejected {
            order_seq: seq,
            category,
            reason: reason.to_string(),
            bar_index,
        })
    }

    /// Marks a filled close order (state/execution info on the order log).
    fn mark_order_filled(
        &mut self,
        seq: u64,
        bar_index: usize,
        position_id: Uuid,
        executed_price: f64,
    ) {
        let rec = self.order_mut(seq);
        rec.state = OrderState::Filled;
        rec.filled_bar = Some(bar_index);
        rec.executed_price = Some(executed_price);
        rec.position_id = Some(position_id);
    }

    fn expire_unfilled_orders(&mut self) -> Result<(), EngineError> {
        let expired: Vec<u64> = self
            .order_log
            .iter()
            .filter(|rec| rec.state == OrderState::Pending || rec.state == OrderState::Created)
            .map(|rec| rec.seq)
            .collect();
        for seq in expired {
            self.order_mut(seq).state = OrderState::Expired;
            self.emit(EngineEventPayload::OrderExpired { order_seq: seq })?;
        }
        Ok(())
    }

    // ── Helpers ──────────────────────────────────

    fn commission_amount(&self, quantity_lots: f64) -> f64 {
        let units = quantity_lots * self.instrument.contract_size;
        self.commission.amount_for_units(units)
    }

    fn record_fill(
        &mut self,
        bar_index: usize,
        order_seq: Option<u64>,
        reason: FillReason,
        side: Direction,
        quantity_lots: f64,
        fill: &semantics::Fill,
        position_id: Option<Uuid>,
        timestamp: DateTime<Utc>,
    ) {
        self.fills.push(RuntimeFill {
            bar_index,
            order_seq,
            reason,
            side,
            quantity_lots,
            raw_reference: fill.raw_reference,
            executed_price: fill.executed_price,
            spread_applied: fill.spread_applied,
            slippage_applied: fill.slippage_applied,
            commission_amount: self.commission_amount(quantity_lots),
            position_id,
            timestamp,
        });
    }

    fn execute_queued_market(
        &mut self,
        bar_index: usize,
        bar: &Bar,
        market: QueuedMarket,
    ) -> Result<(), EngineError> {
        // Resolve close-by-ticket entries against current portfolio state.
        let (side, ticket) = match market.ticket {
            Some(ticket) => {
                let pos = match self.portfolio.position(&ticket) {
                    Some(p) if p.is_open() => p.clone(),
                    _ => {
                        self.reject_order(
                            market.seq,
                            bar_index,
                            RejectionCategory::ExecutionDomain,
                            &format!("cannot close position {ticket}: not open"),
                        )?;
                        return Ok(());
                    }
                };
                if !quantities_match(pos.quantity_lots, market.quantity_lots) {
                    self.reject_order(
                        market.seq,
                        bar_index,
                        RejectionCategory::ExecutionDomain,
                        &format!(
                            "close quantity mismatch for {ticket}: open {} requested {}",
                            pos.quantity_lots, market.quantity_lots
                        ),
                    )?;
                    return Ok(());
                }
                (opposite_side(pos.direction), Some(ticket))
            }
            None => (market.side, None),
        };

        let fill = semantics::market_fill(&self.exec_settings, FillMode::NextBarOpen, bar, side)?;

        match ticket {
            Some(ticket) => {
                self.record_fill(
                    bar_index,
                    Some(market.seq),
                    FillReason::MarketClose,
                    side,
                    market.quantity_lots,
                    &fill,
                    Some(ticket),
                    bar.timestamp,
                );
                self.emit(EngineEventPayload::OrderFilled {
                    order_seq: market.seq,
                    side,
                    quantity_lots: market.quantity_lots,
                    raw_reference: fill.raw_reference,
                    executed_price: fill.executed_price,
                    spread_applied: fill.spread_applied,
                    slippage_applied: fill.slippage_applied,
                    commission_amount: self.commission_amount(market.quantity_lots),
                    bar_index,
                    timestamp: bar.timestamp,
                })?;
                self.mark_order_filled(market.seq, bar_index, ticket, fill.executed_price);
                self.execute_close_by_id(
                    bar_index,
                    ticket,
                    market.quantity_lots,
                    fill.executed_price,
                    ExitReason::Signal,
                    bar.timestamp,
                )?;
            }
            None => {
                // Open first (portfolio acceptance) and only then record the
                // fill against the actual position.
                if let Some(position_id) = self.open_entry(
                    bar_index,
                    market.seq,
                    OrderKind::Market,
                    side,
                    market.quantity_lots,
                    market.stop_loss,
                    market.take_profit,
                    fill.executed_price,
                    bar.timestamp,
                )? {
                    self.emit_entry_events(
                        bar_index,
                        market.seq,
                        side,
                        market.quantity_lots,
                        &fill,
                        market.stop_loss,
                        market.take_profit,
                        position_id,
                        bar.timestamp,
                    )?;
                    self.record_fill(
                        bar_index,
                        Some(market.seq),
                        FillReason::MarketEntry,
                        side,
                        market.quantity_lots,
                        &fill,
                        Some(position_id),
                        bar.timestamp,
                    );
                }
            }
        }
        Ok(())
    }

    fn evaluate_pending(
        &mut self,
        bar_index: usize,
        bar: &Bar,
        order: PendingOrder,
    ) -> Result<PendingEval, EngineError> {
        // Resting orders are only evaluated on bars strictly after the bar on
        // which they were created (no same-bar trigger on creation bar data).
        if order.created_bar >= bar_index {
            return Ok(PendingEval::StillPending(order));
        }
        let spec = OrderSpec {
            kind: order.order_type,
            side: order.side,
            quantity_lots: order.quantity_lots,
            limit_price: if order.order_type == OrderKind::Limit {
                Some(order.trigger_price)
            } else {
                None
            },
            stop_price: if order.order_type == OrderKind::Stop {
                Some(order.trigger_price)
            } else {
                None
            },
        };
        if let Err(e) = semantics::validate_order(&spec, &self.instrument, &self.config.execution) {
            return Ok(PendingEval::Rejected(e.to_string()));
        }

        let outcome = match order.order_type {
            OrderKind::Limit => semantics::limit_outcome(bar, order.side, order.trigger_price),
            OrderKind::Stop => {
                semantics::stop_outcome(&self.exec_settings, bar, order.side, order.trigger_price)
            }
            OrderKind::Market => return Ok(PendingEval::StillPending(order)),
        };

        match outcome {
            Outcome::NotExecutable => Ok(PendingEval::StillPending(order)),
            Outcome::Executed(fill) => {
                let reason = match order.order_type {
                    OrderKind::Limit => FillReason::LimitEntry,
                    _ => FillReason::StopEntry,
                };
                // The trigger itself is canonical: it fired on this bar even
                // if the subsequent open is financially rejected.
                self.emit(EngineEventPayload::OrderTriggered {
                    order_seq: order.seq,
                    bar_index,
                })?;
                match self.open_entry(
                    bar_index,
                    order.seq,
                    order.order_type,
                    order.side,
                    order.quantity_lots,
                    order.stop_loss,
                    order.take_profit,
                    fill.executed_price,
                    bar.timestamp,
                ) {
                    Ok(Some(position_id)) => {
                        self.emit_entry_events(
                            bar_index,
                            order.seq,
                            order.side,
                            order.quantity_lots,
                            &fill,
                            order.stop_loss,
                            order.take_profit,
                            position_id,
                            bar.timestamp,
                        )?;
                        self.record_fill(
                            bar_index,
                            Some(order.seq),
                            reason,
                            order.side,
                            order.quantity_lots,
                            &fill,
                            Some(position_id),
                            bar.timestamp,
                        );
                        Ok(PendingEval::Filled)
                    }
                    Ok(None) => Ok(PendingEval::Filled), // financial rejection recorded
                    Err(e) => {
                        self.reject_order(
                            order.seq,
                            bar_index,
                            RejectionCategory::Runtime,
                            &format!("portfolio failed to open: {e}"),
                        )?;
                        Ok(PendingEval::Filled)
                    }
                }
            }
        }
    }

    /// Opens an entry position.
    ///
    /// Returns `Ok(Some(position_id))` when opened; `Ok(None)` when the
    /// portfolio financially rejected the entry (structured rejection recorded
    /// on the order log); `Err` for unexpected failures.
    fn open_entry(
        &mut self,
        bar_index: usize,
        seq: u64,
        _order_type: OrderKind,
        side: Direction,
        quantity_lots: f64,
        stop_loss: Option<f64>,
        take_profit: Option<f64>,
        executed_price: f64,
        timestamp: DateTime<Utc>,
    ) -> Result<Option<Uuid>, EngineError> {
        let levels = ProtectiveLevels {
            stop_loss,
            take_profit,
        };
        if let Err(e) = semantics::validate_protective_levels(executed_price, side, &levels) {
            self.reject_order(
                seq,
                bar_index,
                RejectionCategory::ExecutionDomain,
                &e.to_string(),
            )?;
            return Ok(None);
        }

        let request = OpenPositionRequest {
            order_id: Uuid::new_v4(),
            fill_id: None,
            direction: side,
            quantity_lots,
            entry_price: executed_price,
            stop_loss,
            take_profit,
            opened_at: timestamp,
            commission_amount: self.commission_amount(quantity_lots),
        };
        match self.portfolio.open_position(&request) {
            Ok(report) => {
                let rec = self.order_mut(seq);
                rec.state = OrderState::Filled;
                rec.filled_bar = Some(bar_index);
                rec.executed_price = Some(executed_price);
                rec.position_id = Some(report.position_id);
                Ok(Some(report.position_id))
            }
            Err(observa_portfolio::error::PortfolioError::InsufficientMargin {
                required,
                available,
            }) => {
                self.reject_order(
                    seq,
                    bar_index,
                    RejectionCategory::Financial,
                    &format!("insufficient margin: required {required}, free margin {available}"),
                )?;
                Ok(None)
            }
            Err(e) => Err(EngineError::Portfolio(e)),
        }
    }

    fn execute_close_by_id(
        &mut self,
        bar_index: usize,
        position_id: Uuid,
        quantity_lots: f64,
        exit_price: f64,
        exit_reason: ExitReason,
        timestamp: DateTime<Utc>,
    ) -> Result<(), EngineError> {
        let request = observa_portfolio::portfolio::ClosePositionRequest {
            position_id,
            quantity_lots,
            exit_price,
            exit_reason,
            closed_at: timestamp,
            commission_amount: self.commission_amount(quantity_lots),
        };
        match self.portfolio.close_position(&request) {
            Ok(report) => {
                self.push_trade(bar_index, &report);
                // Canonical PositionClosed; strategy-close correlation is
                // via the preceding OrderFilled event (protective SL/TP exits
                // have none).
                if let Some(pos) = self.portfolio.position(&report.position_id) {
                    let pos = pos.clone();
                    self.emit(EngineEventPayload::PositionClosed {
                        position_id: report.position_id,
                        side: pos.direction,
                        quantity_lots: report.quantity_lots,
                        entry_price: pos.entry_price,
                        exit_price: report.exit_price,
                        exit_reason: report.exit_reason,
                        gross_realized_pnl: report.gross_realized_pnl,
                        total_commission: report.total_commission_for_position,
                        net_realized_pnl: report.net_realized_pnl,
                        bar_index,
                        timestamp,
                    })?;
                }
                Ok(())
            }
            Err(observa_portfolio::error::PortfolioError::PositionNotFound { .. })
            | Err(observa_portfolio::error::PortfolioError::PositionAlreadyClosed { .. })
            | Err(observa_portfolio::error::PortfolioError::CloseQuantityMismatch { .. }) => {
                // Already handled/closed earlier in the same deterministic
                // stage (or an invalid close) — not a run failure.
                Ok(())
            }
            Err(e) => Err(EngineError::Portfolio(e)),
        }
    }

    fn push_trade(&mut self, bar_index: usize, report: &ClosePositionReport) {
        let pos = match self.portfolio.position(&report.position_id) {
            Some(p) => p.clone(),
            None => return,
        };
        self.trades.push(TradeRecord {
            bar_index,
            position_id: report.position_id,
            direction: pos.direction,
            quantity_lots: report.quantity_lots,
            entry_price: pos.entry_price,
            exit_price: report.exit_price,
            exit_reason: report.exit_reason,
            gross_realized_pnl: report.gross_realized_pnl,
            total_commission: report.total_commission_for_position,
            net_realized_pnl: report.net_realized_pnl,
        });
    }

    fn build_portfolio_view(&self, bar: &Bar) -> PortfolioView {
        let open_positions: Vec<OpenPositionView> = self
            .portfolio
            .open_positions()
            .into_iter()
            .map(|p| OpenPositionView {
                ticket: p.position_id.to_string(),
                symbol: self.instrument.symbol.clone(),
                direction: p.direction,
                size: p.quantity_lots,
                entry_price: p.entry_price,
                unrealised_pnl: p.unrealised_pnl(bar.close),
                sl: p.stop_loss,
                tp: p.take_profit,
            })
            .collect();
        let unrealised_pnl: f64 = open_positions.iter().map(|p| p.unrealised_pnl).sum();
        PortfolioView {
            balance: self.portfolio.balance(),
            equity: self.portfolio.equity(bar.close),
            has_open_position: !open_positions.is_empty(),
            open_positions,
            unrealised_pnl,
            used_margin: self.portfolio.used_margin(bar.close),
            free_margin: self.portfolio.free_margin(bar.close),
        }
    }

    fn process_signal(
        &mut self,
        index: usize,
        bar: &Bar,
        signal: StrategySignal,
    ) -> Result<(), EngineError> {
        match signal.direction {
            Direction::Close => self.process_close_signal(index, bar, signal),
            Direction::Buy | Direction::Sell => self.process_open_signal(index, bar, signal),
        }
    }

    fn process_open_signal(
        &mut self,
        index: usize,
        bar: &Bar,
        signal: StrategySignal,
    ) -> Result<(), EngineError> {
        // Validate the order domain (quantity bounds/step, model support,
        // trigger price for limit/stop).
        let spec = OrderSpec {
            kind: signal.order_type,
            side: signal.direction,
            quantity_lots: signal.size,
            limit_price: if signal.order_type == OrderKind::Limit {
                Some(signal.intended_price)
            } else {
                None
            },
            stop_price: if signal.order_type == OrderKind::Stop {
                Some(signal.intended_price)
            } else {
                None
            },
        };
        if let Err(e) = semantics::validate_order(&spec, &self.instrument, &self.config.execution) {
            // Record a structured rejection; other signals still process.
            let seq =
                self.register_order(index, signal.order_type, signal.direction, signal.size)?;
            self.reject_order(
                seq,
                index,
                RejectionCategory::ExecutionDomain,
                &e.to_string(),
            )?;
            return Ok(());
        }

        let seq = self.register_order(index, signal.order_type, signal.direction, signal.size)?;

        match signal.order_type {
            OrderKind::Market => {
                // MARKET orders are fill-mode dependent.
                match self.fill_mode {
                    FillMode::BarClose => {
                        let fill = semantics::market_fill(
                            &self.exec_settings,
                            FillMode::BarClose,
                            bar,
                            signal.direction,
                        )?;
                        // Open first (portfolio acceptance), then record the
                        // fill against the actual position.
                        if let Some(position_id) = self.open_entry(
                            index,
                            seq,
                            OrderKind::Market,
                            signal.direction,
                            signal.size,
                            signal.sl,
                            signal.tp,
                            fill.executed_price,
                            bar.timestamp,
                        )? {
                            self.emit_entry_events(
                                index,
                                seq,
                                signal.direction,
                                signal.size,
                                &fill,
                                signal.sl,
                                signal.tp,
                                position_id,
                                bar.timestamp,
                            )?;
                            self.record_fill(
                                index,
                                Some(seq),
                                FillReason::MarketEntry,
                                signal.direction,
                                signal.size,
                                &fill,
                                Some(position_id),
                                bar.timestamp,
                            );
                        }
                    }
                    FillMode::NextBarOpen => {
                        // Queue for bar N+1; never fills on bar N.
                        self.order_mut(seq).state = OrderState::Pending;
                        self.emit(EngineEventPayload::OrderPending { order_seq: seq })?;
                        self.queued_market.push(QueuedMarket {
                            seq,
                            side: signal.direction,
                            quantity_lots: signal.size,
                            stop_loss: signal.sl,
                            take_profit: signal.tp,
                            ticket: None,
                        });
                    }
                }
            }
            OrderKind::Limit | OrderKind::Stop => {
                // Rest until a later bar triggers it. First evaluated on the
                // next bar (created_bar < evaluation bar).
                self.order_mut(seq).state = OrderState::Pending;
                self.emit(EngineEventPayload::OrderPending { order_seq: seq })?;
                self.pending_orders.push(PendingOrder {
                    seq,
                    order_type: signal.order_type,
                    side: signal.direction,
                    quantity_lots: signal.size,
                    trigger_price: signal.intended_price,
                    stop_loss: signal.sl,
                    take_profit: signal.tp,
                    created_bar: index,
                });
            }
        }
        Ok(())
    }

    fn process_close_signal(
        &mut self,
        index: usize,
        bar: &Bar,
        signal: StrategySignal,
    ) -> Result<(), EngineError> {
        let seq = self.register_order(index, OrderKind::Market, signal.direction, signal.size)?;
        let ticket = match signal.ticket {
            Some(t) => match t.parse::<Uuid>() {
                Ok(id) => id,
                Err(_) => {
                    self.reject_order(
                        seq,
                        index,
                        RejectionCategory::ExecutionDomain,
                        &format!("close requires a valid position ticket, got '{t}'"),
                    )?;
                    return Ok(());
                }
            },
            None => {
                self.reject_order(
                    seq,
                    index,
                    RejectionCategory::ExecutionDomain,
                    "close requires an explicit position ticket",
                )?;
                return Ok(());
            }
        };

        let pos = match self.portfolio.position(&ticket) {
            Some(p) if p.is_open() => p.clone(),
            _ => {
                self.reject_order(
                    seq,
                    index,
                    RejectionCategory::ExecutionDomain,
                    &format!("cannot close position {ticket}: not open"),
                )?;
                return Ok(());
            }
        };
        if !quantities_match(pos.quantity_lots, signal.size) {
            self.reject_order(
                seq,
                index,
                RejectionCategory::ExecutionDomain,
                &format!(
                    "close quantity mismatch for {ticket}: open {} requested {}",
                    pos.quantity_lots, signal.size
                ),
            )?;
            return Ok(());
        }
        let side = opposite_side(pos.direction);

        match self.fill_mode {
            FillMode::BarClose => {
                let fill =
                    semantics::market_fill(&self.exec_settings, FillMode::BarClose, bar, side)?;
                self.record_fill(
                    index,
                    Some(seq),
                    FillReason::MarketClose,
                    side,
                    signal.size,
                    &fill,
                    Some(ticket),
                    bar.timestamp,
                );
                self.emit(EngineEventPayload::OrderFilled {
                    order_seq: seq,
                    side,
                    quantity_lots: signal.size,
                    raw_reference: fill.raw_reference,
                    executed_price: fill.executed_price,
                    spread_applied: fill.spread_applied,
                    slippage_applied: fill.slippage_applied,
                    commission_amount: self.commission_amount(signal.size),
                    bar_index: index,
                    timestamp: bar.timestamp,
                })?;
                self.mark_order_filled(seq, index, ticket, fill.executed_price);
                self.execute_close_by_id(
                    index,
                    ticket,
                    signal.size,
                    fill.executed_price,
                    ExitReason::Signal,
                    bar.timestamp,
                )?;
            }
            FillMode::NextBarOpen => {
                // Queue close-by-ticket for bar N+1's open.
                self.order_mut(seq).state = OrderState::Pending;
                self.emit(EngineEventPayload::OrderPending { order_seq: seq })?;
                self.queued_market.push(QueuedMarket {
                    seq,
                    side: Direction::Close,
                    quantity_lots: signal.size,
                    stop_loss: None,
                    take_profit: None,
                    ticket: Some(ticket),
                });
            }
        }
        Ok(())
    }
}

enum PendingEval {
    Filled,
    StillPending(PendingOrder),
    Rejected(String),
}

/// Classifies an Engine error into a canonical run-failure category + message.
fn run_failure(error: &EngineError) -> (RunFailureCategory, String) {
    let (category, message) = match error {
        EngineError::InvalidConfiguration(m) => (RunFailureCategory::Configuration, m.clone()),
        EngineError::NoDataLoaded => (RunFailureCategory::Data, "no bars loaded".into()),
        EngineError::StrategyFailure { message, .. } => {
            (RunFailureCategory::Strategy, message.clone())
        }
        EngineError::Portfolio(e) => (RunFailureCategory::Portfolio, e.to_string()),
        EngineError::Execution(e) => (RunFailureCategory::Execution, e.to_string()),
        EngineError::OrderSequenceOverflow => (
            RunFailureCategory::Runtime,
            "order sequence overflow".into(),
        ),
        EngineError::EventSequenceOverflow => (
            RunFailureCategory::Runtime,
            "event sequence overflow".into(),
        ),
        EngineError::InvalidState(m) => (RunFailureCategory::Runtime, m.clone()),
    };
    (category, message)
}

fn opposite_side(side: Direction) -> Direction {
    match side {
        Direction::Buy => Direction::Sell,
        Direction::Sell => Direction::Buy,
        Direction::Close => Direction::Close,
    }
}

fn quantities_match(open: f64, requested: f64) -> bool {
    let scale = open.abs().max(requested.abs()).max(1.0);
    (open - requested).abs() <= 1e-9 * scale
}
