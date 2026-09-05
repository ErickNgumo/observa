//! Portfolio / financial accounting — the single authoritative financial model
//! for Observa (OBS-0005).
//!
//! Responsibilities:
//! * independent position lifecycle (every fill opens its own position),
//! * explicit-ticket full closes (no FIFO, no implicit selection),
//! * realized/unrealized P&L from the canonical contract-size formula,
//! * cash balance, equity, leverage-based used/free margin,
//! * commission **booking** of amounts supplied by the execution layer,
//! * end-of-run financial state (open positions are never auto-closed).
//!
//! There is exactly one financial source of truth here. Components may request
//! calculations or consume results; they must not maintain competing
//! formulas. Canonical unit math lives in [`observa_core::units`].

use chrono::{DateTime, Utc};
use uuid::Uuid;

use observa_core::bar::Bar;
use observa_core::config::CommissionMode;
use observa_core::events::{
    EventMetadata, OrderFilledEvent, PortfolioSnapshotEvent, PositionClosedEvent,
    PositionOpenedEvent,
};
use observa_core::types::{Direction, ExitReason};
use observa_core::units::{margin_required_from_lots, notional_from_lots};

use crate::error::PortfolioError;
use crate::position::Position;

/// Relative tolerance used when comparing close quantities to open quantities.
const QUANTITY_EPSILON: f64 = 1e-9;

// ────────────────────────────────────────────────
// PortfolioSettings
// ────────────────────────────────────────────────

/// Canonical financial inputs the portfolio accounts against.
///
/// Values come from the resolved canonical configuration (OBS-0004):
/// account (starting cash, leverage) and instrument (symbol, contract size),
/// plus the commission mode. `contract_size` and `leverage` are configuration
/// values — never hard-coded broker constants.
#[derive(Debug, Clone, PartialEq)]
pub struct PortfolioSettings {
    /// Starting cash balance (account currency).
    pub initial_cash: f64,
    /// Account leverage: `margin_required = notional / leverage`.
    pub leverage: f64,
    /// Instrument base units per lot, e.g. 100_000 (EURUSD) or 1 (equity).
    pub contract_size: f64,
    /// Instrument symbol.
    pub symbol: String,
    /// When commission amounts supplied by execution are charged.
    pub commission_mode: CommissionMode,
    /// LEGACY ADAPTER-ONLY (pre-OBS-0006): flat per-close commission used by
    /// the legacy fill/SL-TP adapter paths while the execution layer does not
    /// yet supply authoritative amounts. Never used by the canonical
    /// `open_position`/`close_position` math (those take explicit amounts).
    pub legacy_commission: f64,
    /// LEGACY ADAPTER-ONLY (pre-OBS-0006): slippage applied to protective SL
    /// exits inside the legacy `check_sl_tp` path.
    pub legacy_slippage: f64,
}

impl PortfolioSettings {
    /// Creates settings with the canonical commission mode (PER_SIDE) and no
    /// legacy adapter values.
    pub fn new(
        initial_cash: f64,
        leverage: f64,
        contract_size: f64,
        symbol: impl Into<String>,
    ) -> Self {
        Self {
            initial_cash,
            leverage,
            contract_size,
            symbol: symbol.into(),
            commission_mode: CommissionMode::PerSide,
            legacy_commission: 0.0,
            legacy_slippage: 0.0,
        }
    }

    /// Validates settings; called by [`PortfolioManager::try_new`].
    pub fn validate(&self) -> Result<(), PortfolioError> {
        let pos = |v: f64| v.is_finite();
        if !pos(self.initial_cash) || self.initial_cash < 0.0 {
            return Err(PortfolioError::InvalidSettings {
                reason: format!(
                    "initial_cash must be finite and >= 0, got {}",
                    self.initial_cash
                ),
            });
        }
        if !pos(self.leverage) || self.leverage <= 0.0 {
            return Err(PortfolioError::InvalidSettings {
                reason: format!("leverage must be finite and > 0, got {}", self.leverage),
            });
        }
        if !pos(self.contract_size) || self.contract_size <= 0.0 {
            return Err(PortfolioError::InvalidSettings {
                reason: format!(
                    "contract_size must be finite and > 0, got {}",
                    self.contract_size
                ),
            });
        }
        if self.symbol.trim().is_empty() {
            return Err(PortfolioError::InvalidSettings {
                reason: "symbol must be non-empty".to_string(),
            });
        }
        if !pos(self.legacy_commission) || self.legacy_commission < 0.0 {
            return Err(PortfolioError::InvalidSettings {
                reason: "legacy_commission must be finite and >= 0".to_string(),
            });
        }
        if !pos(self.legacy_slippage) || self.legacy_slippage < 0.0 {
            return Err(PortfolioError::InvalidSettings {
                reason: "legacy_slippage must be finite and >= 0".to_string(),
            });
        }
        Ok(())
    }
}

// ────────────────────────────────────────────────
// Canonical request/result records
// ────────────────────────────────────────────────

/// Request to open one independent position from an execution fill.
///
/// `entry_price` is the executed price (spread/slippage already applied by
/// execution). `commission_amount` is the already-calculated commission for
/// this fill leg, supplied by the execution layer; the portfolio only books it
/// (never recomputes it).
#[derive(Debug, Clone)]
pub struct OpenPositionRequest {
    /// Order that produced the fill.
    pub order_id: Uuid,
    /// Fill id, when the execution layer provides one.
    pub fill_id: Option<Uuid>,
    /// Buy (long) or Sell (short).
    pub direction: Direction,
    /// Quantity in lots/contracts.
    pub quantity_lots: f64,
    /// Executed entry price.
    pub entry_price: f64,
    /// Protective stop-loss attached at open.
    pub stop_loss: Option<f64>,
    /// Protective take-profit attached at open.
    pub take_profit: Option<f64>,
    /// Time of the fill/open.
    pub opened_at: DateTime<Utc>,
    /// Already-calculated commission for this leg (0 = none).
    pub commission_amount: f64,
}

/// Result of a successful open.
#[derive(Debug, Clone, PartialEq)]
pub struct OpenPositionReport {
    /// The new position's unique ticket.
    pub position_id: Uuid,
    /// Margin reserved by this position at the entry price.
    pub margin_required: f64,
}

/// Request to close one position **in full**, by explicit ticket.
#[derive(Debug, Clone)]
pub struct ClosePositionRequest {
    /// Ticket of the position to close (never implicitly selected).
    pub position_id: Uuid,
    /// Must equal the position's full open quantity (partial closes are out of
    /// the MVP scope).
    pub quantity_lots: f64,
    /// Exit price (execution-determined).
    pub exit_price: f64,
    /// Why the position closed.
    pub exit_reason: ExitReason,
    /// Time of the close.
    pub closed_at: DateTime<Utc>,
    /// Already-calculated closing-leg (PER_SIDE) or round-trip
    /// (ROUND_TRIP) commission supplied by execution (0 = none).
    pub commission_amount: f64,
}

/// Result of a successful full close.
#[derive(Debug, Clone, PartialEq)]
pub struct ClosePositionReport {
    /// The closed position's ticket.
    pub position_id: Uuid,
    /// Closed quantity.
    pub quantity_lots: f64,
    /// Gross realized P&L (before commission), canonical formula.
    pub gross_realized_pnl: f64,
    /// Commission booked by this close.
    pub commission_booked_now: f64,
    /// Total commission booked against the position (entry leg under
    /// PER_SIDE plus the closing leg).
    pub total_commission_for_position: f64,
    /// Net realized P&L for the trade (gross − total commission).
    pub net_realized_pnl: f64,
    /// Exit price.
    pub exit_price: f64,
    /// Exit reason.
    pub exit_reason: ExitReason,
}

// ────────────────────────────────────────────────
// Snapshot / view records
// ────────────────────────────────────────────────

/// Read-only view of one open position at a valuation price.
#[derive(Debug, Clone, PartialEq)]
pub struct PositionView {
    /// Position ticket.
    pub position_id: Uuid,
    /// Opening order.
    pub order_id: Uuid,
    /// Opening fill id, when known.
    pub fill_id: Option<Uuid>,
    /// Instrument symbol.
    pub symbol: String,
    /// Long or short.
    pub direction: Direction,
    /// Quantity in lots.
    pub quantity_lots: f64,
    /// Base units (`quantity_lots × contract_size`).
    pub units: f64,
    /// Executed entry price.
    pub entry_price: f64,
    /// Unrealized P&L at the valuation price.
    pub unrealised_pnl: f64,
    /// Protective stop-loss.
    pub stop_loss: Option<f64>,
    /// Protective take-profit.
    pub take_profit: Option<f64>,
}

/// Canonical mark-to-market portfolio snapshot at one valuation price.
///
/// `open_positions` contains **all** open positions — it is never capped.
#[derive(Debug, Clone, PartialEq)]
pub struct PortfolioSnapshot {
    /// Snapshot time (bar timestamp).
    pub timestamp: DateTime<Utc>,
    /// Cash balance (unrealized P&L excluded, margin not deducted).
    pub balance: f64,
    /// Balance + unrealized P&L of all open positions.
    pub equity: f64,
    /// Sum of margin required by all open positions at the valuation price.
    pub used_margin: f64,
    /// `equity − used_margin`.
    pub free_margin: f64,
    /// Total unrealized P&L across all open positions.
    pub unrealised_pnl: f64,
    /// Cumulative gross realized P&L.
    pub realised_pnl: f64,
    /// Commissions booked so far.
    pub commissions_paid: f64,
    /// All open positions with per-position identity and unrealized P&L.
    pub open_positions: Vec<PositionView>,
}

/// Complete financial state at dataset end. Open positions are **not**
/// automatically closed; their unrealized P&L remains in final equity.
#[derive(Debug, Clone, PartialEq)]
pub struct EndOfRunState {
    /// Final cash balance (realized P&L − booked commissions).
    pub final_balance: f64,
    /// Final equity (balance + unrealized of all remaining positions).
    pub final_equity: f64,
    /// Margin in use by remaining open positions.
    pub used_margin: f64,
    /// Free margin at the end of the dataset.
    pub free_margin: f64,
    /// Number of positions still open.
    pub open_positions_remaining: usize,
}

// ────────────────────────────────────────────────
// Legacy event carrier (pre-OBS-0007)
// ────────────────────────────────────────────────

/// Events produced by the legacy `process_fill`/`check_sl_tp` adapter paths.
/// The canonical engine (OBS-0007) will emit events itself.
#[derive(Debug)]
pub struct PortfolioEvents {
    pub position_opened: Option<PositionOpenedEvent>,
    pub position_closed: Option<PositionClosedEvent>,
    pub snapshot: PortfolioSnapshotEvent,
}

// ────────────────────────────────────────────────
// PortfolioManager
// ────────────────────────────────────────────────

/// The single authoritative financial/position accounting object for a run.
pub struct PortfolioManager {
    run_id: Uuid,
    settings: PortfolioSettings,
    /// Cash balance: `initial_cash + Σ gross realized − Σ booked commissions`.
    balance: f64,
    /// All positions ever opened for this run (open and closed), in open
    /// order. Closed positions are retained so history and events stay stable.
    positions: Vec<Position>,
    /// Cumulative gross realized P&L (before commissions).
    realised_pnl_gross: f64,
    /// Number of fully closed positions.
    total_trades: u64,
    /// Cumulative booked commissions.
    commissions_paid: f64,
}

impl PortfolioManager {
    /// Creates a portfolio from validated canonical settings.
    pub fn try_new(run_id: Uuid, settings: PortfolioSettings) -> Result<Self, PortfolioError> {
        settings.validate()?;
        Ok(Self {
            run_id,
            balance: settings.initial_cash,
            positions: Vec::new(),
            realised_pnl_gross: 0.0,
            total_trades: 0,
            commissions_paid: 0.0,
            settings,
        })
    }

    // ── Basic accessors ─────────────────────────

    /// Cash balance (realized P&L minus booked commissions; unrealized P&L and
    /// margin reservations do NOT affect it).
    pub fn balance(&self) -> f64 {
        self.balance
    }

    /// Cumulative gross realized P&L (before commissions).
    pub fn realised_pnl(&self) -> f64 {
        self.realised_pnl_gross
    }

    /// Cumulative booked commissions.
    pub fn commissions_paid(&self) -> f64 {
        self.commissions_paid
    }

    /// Number of fully closed trades.
    pub fn total_trades(&self) -> u64 {
        self.total_trades
    }

    /// All positions (open and closed), in opening order.
    pub fn positions(&self) -> &[Position] {
        &self.positions
    }

    /// Position by ticket.
    pub fn position(&self, position_id: &Uuid) -> Option<&Position> {
        self.positions
            .iter()
            .find(|p| p.position_id == *position_id)
    }

    /// All currently open positions.
    pub fn open_positions(&self) -> Vec<&Position> {
        self.positions.iter().filter(|p| p.is_open()).collect()
    }

    // ── Canonical financial calculations ────────

    /// Base units for a quantity: `quantity_lots × contract_size`.
    pub fn units_for(&self, quantity_lots: f64) -> f64 {
        self.settings.contract_size * quantity_lots
    }

    /// Notional for a quantity at a price: `units × price` (quote currency).
    pub fn notional_for(&self, quantity_lots: f64, price: f64) -> f64 {
        notional_from_lots(quantity_lots, self.settings.contract_size, price)
    }

    /// Margin required to hold `quantity_lots` at `price`
    /// (`notional / leverage`).
    pub fn margin_required_for(&self, quantity_lots: f64, price: f64) -> f64 {
        self.margin_for(quantity_lots, price)
    }

    fn margin_for(&self, quantity_lots: f64, price: f64) -> f64 {
        margin_required_from_lots(
            quantity_lots,
            self.settings.contract_size,
            price,
            self.settings.leverage,
        )
        .expect("leverage validated by PortfolioSettings::validate")
    }

    /// Total unrealized P&L of **all** open positions at `price`.
    pub fn unrealised_pnl(&self, price: f64) -> f64 {
        self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.unrealised_pnl(price))
            .sum()
    }

    /// Equity: `cash balance + Σ unrealized(all open positions)`.
    pub fn equity(&self, price: f64) -> f64 {
        self.balance + self.unrealised_pnl(price)
    }

    /// Used margin: Σ margin required by all open positions at `price`
    /// (hedged positions reserve independently — gross, never netted).
    pub fn used_margin(&self, price: f64) -> f64 {
        self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| self.margin_for(p.quantity_lots, price))
            .sum()
    }

    /// Free margin: `equity − used_margin`. Margin is reserved, not deducted
    /// from cash.
    pub fn free_margin(&self, price: f64) -> f64 {
        self.equity(price) - self.used_margin(price)
    }

    /// Margin pre-open check (OBS-0006 will call this before opening).
    ///
    /// Validates the quantity/price and rejects the open when the required
    /// margin exceeds the current free margin.
    pub fn can_open(&self, quantity_lots: f64, price: f64) -> Result<(), PortfolioError> {
        self.validate_quantity(quantity_lots)?;
        self.validate_price(price, "entry")?;
        let required = self.margin_for(quantity_lots, price);
        let available = self.free_margin(price);
        if required > available {
            return Err(PortfolioError::InsufficientMargin {
                required,
                available,
            });
        }
        Ok(())
    }

    /// Opens one independent position from an execution fill (canonical path).
    pub fn open_position(
        &mut self,
        request: &OpenPositionRequest,
    ) -> Result<OpenPositionReport, PortfolioError> {
        match request.direction {
            Direction::Buy | Direction::Sell => {}
            Direction::Close => {
                return Err(PortfolioError::InvalidDirection {
                    direction: "Close".to_string(),
                })
            }
        }
        self.validate_quantity(request.quantity_lots)?;
        self.validate_price(request.entry_price, "entry")?;
        self.validate_commission_amount(request.commission_amount)?;
        if let Some(sl) = request.stop_loss {
            self.validate_price(sl, "stop_loss")?;
        }
        if let Some(tp) = request.take_profit {
            self.validate_price(tp, "take_profit")?;
        }

        let required = self.margin_for(request.quantity_lots, request.entry_price);
        let available = self.free_margin(request.entry_price);
        if required > available {
            return Err(PortfolioError::InsufficientMargin {
                required,
                available,
            });
        }

        let mut position = Position::new(
            Uuid::new_v4(),
            request.order_id,
            request.fill_id,
            self.settings.symbol.clone(),
            request.direction,
            request.quantity_lots,
            self.settings.contract_size,
            request.entry_price,
            request.stop_loss,
            request.take_profit,
            request.opened_at,
        );

        // Commission booking (PER_SIDE charges the entry leg at open;
        // ROUND_TRIP waits for the close).
        if self.settings.commission_mode == CommissionMode::PerSide {
            self.book_commission(request.commission_amount)?;
            position.commission_paid = request.commission_amount;
        }

        let position_id = position.position_id;
        self.positions.push(position);

        Ok(OpenPositionReport {
            position_id,
            margin_required: required,
        })
    }

    /// Closes one position **in full, by explicit ticket** (canonical path).
    ///
    /// Never selects a position implicitly (no FIFO/first/oldest fallback).
    pub fn close_position(
        &mut self,
        request: &ClosePositionRequest,
    ) -> Result<ClosePositionReport, PortfolioError> {
        let idx = self
            .positions
            .iter()
            .position(|p| p.position_id == request.position_id)
            .ok_or_else(|| PortfolioError::PositionNotFound {
                position_id: request.position_id.to_string(),
            })?;
        if !self.positions[idx].is_open() {
            return Err(PortfolioError::PositionAlreadyClosed {
                position_id: request.position_id.to_string(),
            });
        }
        self.validate_quantity(request.quantity_lots)?;
        self.validate_price(request.exit_price, "exit")?;
        self.validate_commission_amount(request.commission_amount)?;
        if !quantities_equal(request.quantity_lots, self.positions[idx].quantity_lots) {
            return Err(PortfolioError::CloseQuantityMismatch {
                position_id: request.position_id.to_string(),
                open_quantity: self.positions[idx].quantity_lots,
                requested_quantity: request.quantity_lots,
            });
        }

        // Book gross realized P&L; commission is booked separately.
        let gross =
            self.positions[idx].close(request.exit_price, request.exit_reason, request.closed_at);
        self.balance += gross;
        self.realised_pnl_gross += gross;
        self.total_trades += 1;

        self.book_commission(request.commission_amount)?;
        self.positions[idx].commission_paid += request.commission_amount;

        let position = &self.positions[idx];
        Ok(ClosePositionReport {
            position_id: position.position_id,
            quantity_lots: position.quantity_lots,
            gross_realized_pnl: gross,
            commission_booked_now: request.commission_amount,
            total_commission_for_position: position.commission_paid,
            net_realized_pnl: gross - position.commission_paid,
            exit_price: request.exit_price,
            exit_reason: request.exit_reason,
        })
    }

    /// Books an already-calculated commission amount exactly once.
    ///
    /// Used by the canonical paths with amounts supplied by execution; the
    /// portfolio never recomputes commission.
    pub fn book_commission(&mut self, amount: f64) -> Result<(), PortfolioError> {
        self.validate_commission_amount(amount)?;
        if amount == 0.0 {
            return Ok(());
        }
        self.balance -= amount;
        self.commissions_paid += amount;
        Ok(())
    }

    /// Canonical mark-to-market snapshot at `valuation_price`.
    pub fn snapshot(&self, valuation_price: f64, timestamp: DateTime<Utc>) -> PortfolioSnapshot {
        let unrealised_pnl = self.unrealised_pnl(valuation_price);
        let equity = self.balance + unrealised_pnl;
        let used_margin = self.used_margin(valuation_price);
        let open_views = self
            .positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| PositionView {
                position_id: p.position_id,
                order_id: p.order_id,
                fill_id: p.fill_id,
                symbol: p.symbol.clone(),
                direction: p.direction,
                quantity_lots: p.quantity_lots,
                units: p.units(),
                entry_price: p.entry_price,
                unrealised_pnl: p.unrealised_pnl(valuation_price),
                stop_loss: p.stop_loss,
                take_profit: p.take_profit,
            })
            .collect();
        PortfolioSnapshot {
            timestamp,
            balance: self.balance,
            equity,
            used_margin,
            free_margin: equity - used_margin,
            unrealised_pnl,
            realised_pnl: self.realised_pnl_gross,
            commissions_paid: self.commissions_paid,
            open_positions: open_views,
        }
    }

    /// Complete end-of-run financial state at the final valuation price.
    ///
    /// Open positions are NOT automatically closed; they are reported and
    /// their unrealized P&L stays in final equity.
    pub fn end_of_run_state(&self, valuation_price: f64) -> EndOfRunState {
        let unrealised_pnl = self.unrealised_pnl(valuation_price);
        let equity = self.balance + unrealised_pnl;
        let used_margin = self.used_margin(valuation_price);
        let open_positions_remaining = self.positions.iter().filter(|p| p.is_open()).count();
        EndOfRunState {
            final_balance: self.balance,
            final_equity: equity,
            used_margin,
            free_margin: equity - used_margin,
            open_positions_remaining,
        }
    }

    // ── Validation helpers ───────────────────────

    fn validate_quantity(&self, quantity_lots: f64) -> Result<(), PortfolioError> {
        if !quantity_lots.is_finite() || quantity_lots <= 0.0 {
            return Err(PortfolioError::InvalidQuantity {
                quantity: quantity_lots,
                reason: "quantity must be finite and > 0".to_string(),
            });
        }
        Ok(())
    }

    fn validate_price(&self, price: f64, field: &str) -> Result<(), PortfolioError> {
        if !price.is_finite() || price <= 0.0 {
            return Err(PortfolioError::InvalidPrice {
                price,
                reason: format!("{field} price must be finite and > 0"),
            });
        }
        Ok(())
    }

    fn validate_commission_amount(&self, amount: f64) -> Result<(), PortfolioError> {
        if !amount.is_finite() || amount < 0.0 {
            return Err(PortfolioError::InvalidCommission {
                amount,
                reason: "commission amount must be finite and >= 0".to_string(),
            });
        }
        Ok(())
    }

    // ──────────────────────────────────────────────
    // LEGACY ADAPTERS (pre-OBS-0006/0007)
    // ──────────────────────────────────────────────
    //
    // The current CLI replay loop still drives fills through these methods.
    // They are thin: they translate legacy fill/bar inputs into the canonical
    // operations above and map the results back to the legacy event structs.
    // They are removed when the canonical engine (OBS-0007) takes over event
    // production. They do not implement a second accounting model.

    /// Legacy fill entry point (used by the pre-OBS-0007 CLI).
    ///
    /// Buy/Sell fills open independent positions; Close fills close the exact
    /// position identified by `ticket` (ticket required; no FIFO fallback).
    pub fn process_fill(
        &mut self,
        fill: &OrderFilledEvent,
        ticket: Option<String>,
    ) -> Result<PortfolioEvents, PortfolioError> {
        match fill.direction {
            Direction::Buy | Direction::Sell => {
                let position_id = self
                    .open_position(&OpenPositionRequest {
                        order_id: fill.order_id,
                        fill_id: None,
                        direction: fill.direction,
                        quantity_lots: fill.size,
                        entry_price: fill.executed_price,
                        stop_loss: fill.sl,
                        take_profit: fill.tp,
                        opened_at: fill.metadata.timestamp,
                        commission_amount: if self.settings.commission_mode
                            == CommissionMode::PerSide
                        {
                            fill.commission
                        } else {
                            0.0
                        },
                    })?
                    .position_id;

                let position = self
                    .position(&position_id)
                    .expect("just-opened position must exist");
                let equity = self.equity(fill.executed_price);
                let opened = PositionOpenedEvent {
                    metadata: EventMetadata::new(self.run_id, fill.metadata.timestamp),
                    position_id,
                    order_id: fill.order_id,
                    direction: position.direction,
                    size: position.quantity_lots,
                    entry_price: position.entry_price,
                    sl: position.stop_loss,
                    tp: position.take_profit,
                    pnl: 0.0,
                    exposure_pct: self.exposure_pct(
                        position.quantity_lots,
                        position.entry_price,
                        equity,
                    ),
                    risk_pct: self.risk_pct(position),
                    margin_pct: self.margin_pct(
                        position.quantity_lots,
                        position.entry_price,
                        equity,
                    ),
                };
                let snapshot = self.snapshot_event(fill.executed_price, fill.metadata.timestamp);
                Ok(PortfolioEvents {
                    position_opened: Some(opened),
                    position_closed: None,
                    snapshot,
                })
            }
            Direction::Close => {
                let position_id = parse_ticket(ticket)?;
                let report = self.close_position(&ClosePositionRequest {
                    position_id,
                    quantity_lots: fill.size,
                    exit_price: fill.executed_price,
                    exit_reason: ExitReason::Signal,
                    closed_at: fill.metadata.timestamp,
                    commission_amount: fill.commission,
                })?;
                let position = self
                    .position(&position_id)
                    .expect("just-closed position must exist");
                let equity = self.equity(fill.executed_price);
                let closed = PositionClosedEvent {
                    metadata: EventMetadata::new(self.run_id, fill.metadata.timestamp),
                    position_id,
                    order_id: position.order_id,
                    direction: position.direction,
                    size: position.quantity_lots,
                    entry_price: position.entry_price,
                    exit_price: report.exit_price,
                    exit_reason: report.exit_reason,
                    pnl: report.net_realized_pnl,
                    exposure_pct: self.exposure_pct(
                        position.quantity_lots,
                        position.entry_price,
                        equity,
                    ),
                    risk_pct: self.risk_pct(position),
                };
                let snapshot = self.snapshot_event(fill.executed_price, fill.metadata.timestamp);
                Ok(PortfolioEvents {
                    position_opened: None,
                    position_closed: Some(closed),
                    snapshot,
                })
            }
        }
    }

    /// Legacy per-bar SL/TP check (used by the pre-OBS-0007 CLI).
    ///
    /// SL is a market-style exit and receives `legacy_slippage`; TP is a
    /// limit-style exit and does not. Within one position, SL is evaluated
    /// before TP. Each hit closes the exact position by ticket.
    pub fn check_sl_tp(&mut self, bar: &Bar) -> Vec<PortfolioEvents> {
        let mut results = Vec::new();

        let hits: Vec<(Uuid, f64, ExitReason)> = self
            .positions
            .iter()
            .filter(|p| p.is_open())
            .filter_map(|p| {
                if let Some(sl) = p.check_sl(bar.low, bar.high) {
                    let exit_price = match p.direction {
                        Direction::Buy => sl - self.settings.legacy_slippage,
                        Direction::Sell => sl + self.settings.legacy_slippage,
                        Direction::Close => sl,
                    };
                    Some((p.position_id, exit_price, ExitReason::StopLoss))
                } else if let Some(tp) = p.check_tp(bar.low, bar.high) {
                    Some((p.position_id, tp, ExitReason::TakeProfit))
                } else {
                    None
                }
            })
            .collect();

        for (position_id, exit_price, reason) in hits {
            if let Some(position) = self.position(&position_id) {
                let events = self.close_position(&ClosePositionRequest {
                    position_id,
                    quantity_lots: position.quantity_lots,
                    exit_price,
                    exit_reason: reason,
                    closed_at: bar.timestamp,
                    commission_amount: self.settings.legacy_commission,
                });
                if let Ok(report) = events {
                    results.push(self.closed_events(report, bar.timestamp, exit_price));
                }
            }
        }

        results
    }

    fn closed_events(
        &self,
        report: ClosePositionReport,
        timestamp: DateTime<Utc>,
        _exit_price: f64,
    ) -> PortfolioEvents {
        let position = self
            .position(&report.position_id)
            .expect("closed position must exist for event mapping");
        let equity = self.equity(report.exit_price);
        let closed = PositionClosedEvent {
            metadata: EventMetadata::new(self.run_id, timestamp),
            position_id: report.position_id,
            order_id: position.order_id,
            direction: position.direction,
            size: position.quantity_lots,
            entry_price: position.entry_price,
            exit_price: report.exit_price,
            exit_reason: report.exit_reason,
            pnl: report.net_realized_pnl,
            exposure_pct: self.exposure_pct(position.quantity_lots, position.entry_price, equity),
            risk_pct: self.risk_pct(position),
        };
        let snapshot = self.snapshot_event(report.exit_price, timestamp);
        PortfolioEvents {
            position_opened: None,
            position_closed: Some(closed),
            snapshot,
        }
    }

    fn snapshot_event(&self, price: f64, timestamp: DateTime<Utc>) -> PortfolioSnapshotEvent {
        let snap = self.snapshot(price, timestamp);
        PortfolioSnapshotEvent {
            metadata: EventMetadata::new(self.run_id, timestamp),
            balance: snap.balance,
            equity: snap.equity,
            margin: snap.used_margin,
            free_margin: snap.free_margin,
            unrealised_pnl: snap.unrealised_pnl,
            realised_pnl: snap.realised_pnl,
            open_positions: snap.open_positions.len() as u32,
        }
    }

    /// Informational percentage fields kept on legacy position events.
    fn exposure_pct(&self, quantity_lots: f64, price: f64, equity: f64) -> f64 {
        if equity <= 0.0 {
            return 0.0;
        }
        (self.notional_for(quantity_lots, price) / equity) * 100.0
    }

    fn risk_pct(&self, position: &Position) -> Option<f64> {
        let equity = self.equity(position.entry_price);
        if equity <= 0.0 {
            return None;
        }
        position
            .stop_loss
            .map(|sl| (position.entry_price - sl).abs() * position.units() / equity * 100.0)
    }

    fn margin_pct(&self, quantity_lots: f64, price: f64, equity: f64) -> f64 {
        if equity <= 0.0 {
            return 0.0;
        }
        (self.margin_for(quantity_lots, price) / equity) * 100.0
    }
}

// ────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────

fn quantities_equal(a: f64, b: f64) -> bool {
    let scale = a.abs().max(b.abs()).max(1.0);
    (a - b).abs() <= QUANTITY_EPSILON * scale
}

fn parse_ticket(ticket: Option<String>) -> Result<Uuid, PortfolioError> {
    let t = ticket.ok_or(PortfolioError::CloseRequiresTicket)?;
    Uuid::parse_str(&t).map_err(|_| PortfolioError::PositionNotFound { position_id: t })
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::position::PositionStatus;
    use chrono::TimeZone;
    use observa_core::events::{EventMetadata, OrderFilledEvent};

    const EURUSD: f64 = 100_000.0;
    const CASH: f64 = 100_000.0;

    fn ts() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 7, 10, 3, 0, 0).unwrap()
    }

    fn settings_eurusd(leverage: f64) -> PortfolioSettings {
        PortfolioSettings::new(CASH, leverage, EURUSD, "EURUSD")
    }

    fn pm(leverage: f64) -> PortfolioManager {
        PortfolioManager::try_new(Uuid::new_v4(), settings_eurusd(leverage)).unwrap()
    }

    fn open_request(price: f64, qty: f64, direction: Direction) -> OpenPositionRequest {
        OpenPositionRequest {
            order_id: Uuid::new_v4(),
            fill_id: None,
            direction,
            quantity_lots: qty,
            entry_price: price,
            stop_loss: None,
            take_profit: None,
            opened_at: ts(),
            commission_amount: 0.0,
        }
    }

    // ── P&L basics ───────────────────────────────

    #[test]
    fn long_pnl_is_canonical() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.1050,
                exit_reason: ExitReason::TakeProfit,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        // (1.1050 − 1.1000) × 1 × 100 000 = +500
        assert!((rep.gross_realized_pnl - 500.0).abs() < 1e-6);
        assert_eq!(rep.net_realized_pnl, rep.gross_realized_pnl);
        assert!((p.balance() - (CASH + 500.0)).abs() < 1e-6);
    }

    #[test]
    fn short_pnl_is_canonical() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 1.0, Direction::Sell))
            .unwrap()
            .position_id;
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.0950,
                exit_reason: ExitReason::TakeProfit,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        assert!((rep.gross_realized_pnl - 500.0).abs() < 1e-6);
        assert!((p.balance() - (CASH + 500.0)).abs() < 1e-6);
    }

    #[test]
    fn losing_trade_is_negative() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.0950,
                exit_reason: ExitReason::StopLoss,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        assert!((rep.gross_realized_pnl + 500.0).abs() < 1e-6);
        assert!((p.balance() - (CASH - 500.0)).abs() < 1e-6);
    }

    #[test]
    fn zero_pnl_when_price_unchanged() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 2.0, Direction::Buy))
            .unwrap()
            .position_id;
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 2.0,
                exit_price: 1.1000,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        assert!(rep.gross_realized_pnl.abs() < 1e-9);
        assert!((p.balance() - CASH).abs() < 1e-9);
    }

    // ── Multi-position / hedging ─────────────────

    #[test]
    fn same_direction_positions_are_independent() {
        let mut p = pm(100.0);
        let a = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        let b = p
            .open_position(&open_request(1.1020, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        assert_ne!(a, b);
        assert_eq!(p.open_positions().len(), 2);

        // Each retains its own P&L at a common valuation price.
        let pnl_a = p.position(&a).unwrap().unrealised_pnl(1.1050);
        let pnl_b = p.position(&b).unwrap().unrealised_pnl(1.1050);
        assert!((pnl_a - 500.0).abs() < 1e-6); // 1.1050−1.1000
        assert!((pnl_b - 300.0).abs() < 1e-6); // 1.1050−1.1020
    }

    #[test]
    fn equity_includes_all_open_positions() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        // Both up 50 pips → unrealized +1000 total.
        let equity = p.equity(1.1050);
        assert!((equity - (CASH + 1000.0)).abs() < 1e-6);
        assert!((p.unrealised_pnl(1.1050) - 1000.0).abs() < 1e-6);
    }

    #[test]
    fn hedging_long_and_short_coexist() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        p.open_position(&open_request(1.1000, 1.0, Direction::Sell))
            .unwrap();
        assert_eq!(p.open_positions().len(), 2);
        // At unchanged price both are flat.
        assert!(p.unrealised_pnl(1.1000).abs() < 1e-9);
    }

    #[test]
    fn hedge_margin_is_gross() {
        let mut p = pm(100.0); // 1 lot EURUSD @1.10 notional 110k; /100 → 1,100
        let price = 1.10;
        p.open_position(&open_request(price, 1.0, Direction::Buy))
            .unwrap();
        p.open_position(&open_request(price, 1.0, Direction::Sell))
            .unwrap();
        // Both legs reserve independently: 1,100 + 1,100.
        assert!((p.used_margin(price) - 2200.0).abs() < 1e-6);
        assert!((p.free_margin(price) - (CASH - 2200.0)).abs() < 1e-6);
    }

    // ── Explicit close / rejection semantics ─────

    #[test]
    fn valid_ticket_closes_exact_position() {
        let mut p = pm(100.0);
        let first = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        let second = p
            .open_position(&open_request(1.1020, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        p.close_position(&ClosePositionRequest {
            position_id: second,
            quantity_lots: 1.0,
            exit_price: 1.1040,
            exit_reason: ExitReason::Signal,
            closed_at: ts(),
            commission_amount: 0.0,
        })
        .unwrap();
        assert!(p.position(&second).unwrap().status == PositionStatus::Closed);
        assert!(p.position(&first).unwrap().status == PositionStatus::Open);
        assert_eq!(p.open_positions().len(), 1);
    }

    #[test]
    fn missing_ticket_is_rejected_not_fifo() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        // Attempt a ticket-less close via the legacy path: must reject.
        let err = p
            .process_fill(&close_fill(1.1050, Uuid::new_v4(), 7.0), None)
            .unwrap_err();
        assert!(matches!(err, PortfolioError::CloseRequiresTicket));
        // No position was silently selected.
        assert_eq!(p.open_positions().len(), 1);
    }

    #[test]
    fn unknown_ticket_is_rejected() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        let err = p
            .close_position(&ClosePositionRequest {
                position_id: Uuid::new_v4(),
                quantity_lots: 1.0,
                exit_price: 1.1050,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap_err();
        assert!(matches!(err, PortfolioError::PositionNotFound { .. }));
    }

    #[test]
    fn already_closed_ticket_is_rejected() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        p.close_position(&ClosePositionRequest {
            position_id: id,
            quantity_lots: 1.0,
            exit_price: 1.1050,
            exit_reason: ExitReason::Signal,
            closed_at: ts(),
            commission_amount: 0.0,
        })
        .unwrap();
        let err = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.1050,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap_err();
        assert!(matches!(err, PortfolioError::PositionAlreadyClosed { .. }));
    }

    #[test]
    fn wrong_quantity_is_rejected() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 2.0, Direction::Buy))
            .unwrap()
            .position_id;
        let err = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0, // partial close attempt
                exit_price: 1.1050,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap_err();
        assert!(matches!(err, PortfolioError::CloseQuantityMismatch { .. }));
        assert_eq!(p.open_positions().len(), 1);
    }

    // ── Margin ───────────────────────────────────

    #[test]
    fn margin_uses_leverage_and_contract_size() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.10, 1.0, Direction::Buy))
            .unwrap();
        // notional 110,000 / 100 → 1,100.
        assert!((p.used_margin(1.10) - 1100.0).abs() < 1e-6);
        assert!((p.free_margin(1.10) - (CASH - 1100.0)).abs() < 1e-6);
    }

    #[test]
    fn margin_scales_with_leverage() {
        let mut p = pm(50.0);
        p.open_position(&open_request(1.10, 1.0, Direction::Buy))
            .unwrap();
        assert!((p.used_margin(1.10) - 2200.0).abs() < 1e-6);
    }

    #[test]
    fn margin_rejection_when_free_margin_exceeded() {
        let mut p = PortfolioManager::try_new(
            Uuid::new_v4(),
            PortfolioSettings::new(10_000.0, 100.0, EURUSD, "EURUSD"),
        )
        .unwrap();
        // 1 lot @1.10 → margin 1,100 < 10,000 free → OK.
        p.open_position(&open_request(1.10, 1.0, Direction::Buy))
            .unwrap();
        // After reserving 1,100, free = 8,900. 9 lots @1.10 → 10,890 > 8,900.
        let err = p
            .open_position(&open_request(1.10, 9.0, Direction::Buy))
            .unwrap_err();
        assert!(matches!(err, PortfolioError::InsufficientMargin { .. }));
        assert_eq!(p.open_positions().len(), 1);
    }

    #[test]
    fn closing_releases_margin() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.10, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        assert!((p.used_margin(1.10) - 1100.0).abs() < 1e-6);
        p.close_position(&ClosePositionRequest {
            position_id: id,
            quantity_lots: 1.0,
            exit_price: 1.10,
            exit_reason: ExitReason::Signal,
            closed_at: ts(),
            commission_amount: 0.0,
        })
        .unwrap();
        assert!(p.used_margin(1.10).abs() < 1e-9);
        // Release of margin is availability, not profit: cash unchanged at 1.10.
        assert!((p.balance() - CASH).abs() < 1e-9);
    }

    #[test]
    fn can_open_api_reports_availability() {
        let mut p = PortfolioManager::try_new(
            Uuid::new_v4(),
            PortfolioSettings::new(10_000.0, 100.0, EURUSD, "EURUSD"),
        )
        .unwrap();
        assert!(p.can_open(1.0, 1.10).is_ok());
        assert!(p.can_open(100.0, 1.10).is_err());
        assert!(p.can_open(0.0, 1.10).is_err());
        assert!(p.can_open(f64::NAN, 1.10).is_err());
        p.open_position(&open_request(1.10, 1.0, Direction::Buy))
            .unwrap();
        assert!(p.can_open(8.0, 1.10).is_ok()); // 8,800 <= free 8,900
        assert!(p.can_open(9.0, 1.10).is_err());
    }

    // ── Cash vs equity vs commission ─────────────

    #[test]
    fn unrealised_changes_equity_not_balance() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        assert!((p.balance() - CASH).abs() < 1e-9);
        let equity = p.equity(1.1050);
        assert!((equity - (CASH + 500.0)).abs() < 1e-6);
        assert!((p.balance() - CASH).abs() < 1e-9);
    }

    #[test]
    fn commission_booked_exactly_once_per_side() {
        let mut p = pm(100.0);
        // PER_SIDE (canonical default): $7 on the entry leg and $7 on the exit leg.
        let id = p
            .open_position(&OpenPositionRequest {
                commission_amount: 7.0,
                ..open_request(1.1000, 1.0, Direction::Buy)
            })
            .unwrap()
            .position_id;
        assert!((p.balance() - (CASH - 7.0)).abs() < 1e-9);
        assert!((p.commissions_paid() - 7.0).abs() < 1e-9);
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.1050,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 7.0,
            })
            .unwrap();
        assert!((p.commissions_paid() - 14.0).abs() < 1e-9);
        // Net = gross 500 − 14 = 486.
        assert!((rep.net_realized_pnl - 486.0).abs() < 1e-6);
        assert!((p.balance() - (CASH - 14.0 + 500.0)).abs() < 1e-6);
    }

    #[test]
    fn round_trip_commission_charged_once_at_close() {
        let mut settings = settings_eurusd(100.0);
        settings.commission_mode = CommissionMode::RoundTrip;
        let mut p = PortfolioManager::try_new(Uuid::new_v4(), settings).unwrap();
        let id = p
            .open_position(&OpenPositionRequest {
                commission_amount: 7.0, // ignored at open under ROUND_TRIP
                ..open_request(1.1000, 1.0, Direction::Buy)
            })
            .unwrap()
            .position_id;
        assert!((p.balance() - CASH).abs() < 1e-9);
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1.1050,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 7.0, // single round-trip charge
            })
            .unwrap();
        assert!((rep.total_commission_for_position - 7.0).abs() < 1e-9);
        assert!((rep.net_realized_pnl - 493.0).abs() < 1e-6);
        assert!((p.balance() - (CASH - 7.0 + 500.0)).abs() < 1e-6);
    }

    #[test]
    fn invalid_commission_rejected() {
        let mut p = pm(100.0);
        let err = p.book_commission(-1.0).unwrap_err();
        assert!(matches!(err, PortfolioError::InvalidCommission { .. }));
        assert!((p.balance() - CASH).abs() < 1e-9);
    }

    // ── Different instruments (no FX assumption) ─

    #[test]
    fn equity_instrument_uses_contract_size_one() {
        let mut p = PortfolioManager::try_new(
            Uuid::new_v4(),
            PortfolioSettings::new(100_000.0, 4.0, 1.0, "AAPL"),
        )
        .unwrap();
        // 100 shares @182.50 → notional 18,250; leverage 4 → margin 4,562.50.
        let id = p
            .open_position(&open_request(182.50, 100.0, Direction::Buy))
            .unwrap()
            .position_id;
        assert!((p.used_margin(182.50) - 4562.50).abs() < 1e-6);
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 100.0,
                exit_price: 185.00,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        // (185 − 182.5) × 100 × 1 = +250
        assert!((rep.gross_realized_pnl - 250.0).abs() < 1e-6);
    }

    #[test]
    fn gold_instrument_pnl_and_margin() {
        let mut p = PortfolioManager::try_new(
            Uuid::new_v4(),
            PortfolioSettings::new(100_000.0, 20.0, 100.0, "XAUUSD"),
        )
        .unwrap();
        let id = p
            .open_position(&open_request(1923.45, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        // notional 192,345 / 20 = 9,617.25
        assert!((p.used_margin(1923.45) - 9617.25).abs() < 1e-6);
        let rep = p
            .close_position(&ClosePositionRequest {
                position_id: id,
                quantity_lots: 1.0,
                exit_price: 1924.45,
                exit_reason: ExitReason::Signal,
                closed_at: ts(),
                commission_amount: 0.0,
            })
            .unwrap();
        assert!((rep.gross_realized_pnl - 100.0).abs() < 1e-6);
    }

    // ── End of run / snapshot ────────────────────

    #[test]
    fn end_of_run_leaves_positions_open_and_reports_state() {
        let mut p = pm(100.0);
        let id = p
            .open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap()
            .position_id;
        // Price moved to 1.1050: unrealized +500.
        let state = p.end_of_run_state(1.1050);
        assert_eq!(state.open_positions_remaining, 1);
        assert!(p.position(&id).unwrap().is_open());
        assert!((state.final_balance - CASH).abs() < 1e-9);
        assert!((state.final_equity - (CASH + 500.0)).abs() < 1e-6);
        assert_ne!(state.final_balance, state.final_equity);
        // Margin uses the valuation price: 100 000 × 1.1050 / 100 = 1,105.
        assert!((state.used_margin - 1105.0).abs() < 1e-6);
        assert!((state.free_margin - (state.final_equity - 1105.0)).abs() < 1e-6);
    }

    #[test]
    fn snapshot_lists_all_positions_and_does_not_cap() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        p.open_position(&open_request(1.1000, 1.0, Direction::Sell))
            .unwrap();
        let snap = p.snapshot(1.1000, ts());
        assert_eq!(snap.open_positions.len(), 2);
        assert!(snap.open_positions.iter().all(|v| v.units == 100_000.0));
        assert!(snap.unrealised_pnl.abs() < 1e-9);
        assert!((snap.equity - snap.balance).abs() < 1e-9);
    }

    #[test]
    fn snapshot_invariants_hold() {
        let mut p = pm(100.0);
        p.open_position(&open_request(1.1000, 1.0, Direction::Buy))
            .unwrap();
        p.open_position(&open_request(1.1000, 0.5, Direction::Sell))
            .unwrap();
        let price = 1.1040;
        let snap = p.snapshot(price, ts());
        // equity = balance + total unrealized
        assert!((snap.equity - (snap.balance + snap.unrealised_pnl)).abs() < 1e-9);
        // free = equity − used
        assert!((snap.free_margin - (snap.equity - snap.used_margin)).abs() < 1e-9);
        // used margin = sum of per-position margins
        let margin_sum: f64 = snap
            .open_positions
            .iter()
            .map(|v| v.units * price / 100.0)
            .sum();
        assert!((snap.used_margin - margin_sum).abs() < 1e-6);
    }

    // ── Legacy adapter behaviour ─────────────────

    fn fill(price: f64, direction: Direction, commission: f64) -> OrderFilledEvent {
        OrderFilledEvent {
            metadata: EventMetadata::new(Uuid::new_v4(), ts()),
            order_id: Uuid::new_v4(),
            signal_id: Uuid::new_v4(),
            intended_price: price,
            executed_price: price,
            slippage: 0.0,
            spread_cost: 0.0,
            commission,
            size: 1.0,
            direction,
            sl: None,
            tp: None,
            reason: "test".to_string(),
        }
    }

    fn close_fill(price: f64, order_id: Uuid, commission: f64) -> OrderFilledEvent {
        let mut f = fill(price, Direction::Close, commission);
        f.order_id = order_id;
        f
    }

    #[test]
    fn legacy_process_fill_open_and_close_by_ticket() {
        let mut settings = settings_eurusd(100.0);
        settings.commission_mode = CommissionMode::RoundTrip;
        settings.legacy_commission = 7.0;
        let mut p = PortfolioManager::try_new(Uuid::new_v4(), settings).unwrap();

        let open = fill(1.13786, Direction::Buy, 7.0);
        let ev = p.process_fill(&open, None).unwrap();
        let pos_id = ev.position_opened.as_ref().unwrap().position_id;
        let ticket = pos_id.to_string();

        // No FIFO: closing without a ticket is rejected.
        let err = p
            .process_fill(&close_fill(1.14186, open.order_id, 7.0), None)
            .unwrap_err();
        assert!(matches!(err, PortfolioError::CloseRequiresTicket));

        // Close with the exact ticket succeeds.
        let ev = p
            .process_fill(&close_fill(1.14186, open.order_id, 7.0), Some(ticket))
            .unwrap();
        let closed = ev.position_closed.as_ref().unwrap();
        // 40 pips × $10 − $7 round-trip commission = $393.
        assert!((closed.pnl - 393.0).abs() < 1e-6);
        assert_eq!(p.open_positions().len(), 0);
        assert_eq!(p.total_trades(), 1);
        assert!(p.balance() > CASH);
    }

    #[test]
    fn legacy_check_sl_tp_closes_by_position() {
        let mut settings = settings_eurusd(100.0);
        settings.commission_mode = CommissionMode::RoundTrip;
        settings.legacy_commission = 7.0;
        settings.legacy_slippage = 0.0001;
        let mut p = PortfolioManager::try_new(Uuid::new_v4(), settings).unwrap();

        let mut open = fill(1.13786, Direction::Buy, 7.0);
        open.sl = Some(1.1350);
        let _ = p.process_fill(&open, None).unwrap();

        let bar = Bar::new(ts(), 1.1376, 1.1390, 1.1340, 1.1360, None);
        let events = p.check_sl_tp(&bar);
        assert_eq!(events.len(), 1);
        assert_eq!(p.open_positions().len(), 0);
        // Balance < start (loss with commission).
        assert!(p.balance() < CASH);
    }

    #[test]
    fn legacy_invalid_ticket_reports_not_found() {
        let mut settings = settings_eurusd(100.0);
        settings.commission_mode = CommissionMode::RoundTrip;
        settings.legacy_commission = 7.0;
        let mut p = PortfolioManager::try_new(Uuid::new_v4(), settings).unwrap();
        let open = fill(1.13786, Direction::Buy, 7.0);
        p.process_fill(&open, None).unwrap();
        let err = p
            .process_fill(
                &close_fill(1.14186, open.order_id, 7.0),
                Some(Uuid::new_v4().to_string()),
            )
            .unwrap_err();
        assert!(matches!(err, PortfolioError::PositionNotFound { .. }));
    }

    #[test]
    fn invalid_open_direction_is_rejected() {
        let mut p = pm(100.0);
        let err = p
            .open_position(&open_request(1.10, 1.0, Direction::Close))
            .unwrap_err();
        assert!(matches!(err, PortfolioError::InvalidDirection { .. }));
    }
}
