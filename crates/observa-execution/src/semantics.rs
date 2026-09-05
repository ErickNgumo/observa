//! Canonical deterministic order & execution semantics (OBS-0006).
//!
//! This module defines **how** an order or a protective instruction resolves
//! against one OHLC bar: trigger decisions, raw reference prices, spread and
//! slippage adjustments, gap handling, and the deterministic SL-first / gap
//! precedence conventions. It is pure and stateless — the same inputs always
//! produce the same decision and price.
//!
//! Responsibilities kept OUT of this module (OBS-0005 financial authority):
//! account balance, equity, used/free margin, leverage sufficiency,
//! portfolio affordability, realized/unrealized P&L. This module receives
//! only execution-domain inputs (order, bar, instrument/execution
//! configuration) and produces execution results.
//!
//! Scheduling of orders across bars (which bar a MARKET order executes on,
//! when a resting order is first evaluated, dataset-end expiry) belongs to the
//! engine orchestration (OBS-0007); this module supplies the per-bar
//! evaluation primitives the engine will call.

use observa_core::bar::Bar;
use observa_core::config::FillMode;
use observa_core::config::{ExecutionConfig as CoreExecutionConfig, InstrumentConfig};
use observa_core::types::{Direction, OrderKind, OrderState, ProtectiveKind};

/// Tolerance used for quantity step/rounding comparisons.
const QUANTITY_EPSILON: f64 = 1e-9;

// ────────────────────────────────────────────────
// Execution settings
// ────────────────────────────────────────────────

/// Price-adjustment settings used by execution.
///
/// Contains **only** execution-domain values. There is deliberately no
/// balance/leverage/margin field here — execution must never perform account
/// affordability decisions.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ExecutionSettings {
    /// Full bid/ask spread in price units; applied symmetrically as
    /// `spread / 2` on each market-style fill.
    pub spread: f64,
    /// Adverse slippage in price units, applied only to market-style fills.
    pub slippage: f64,
}

impl ExecutionSettings {
    /// Builds settings from the canonical execution configuration.
    pub fn from_config(config: &CoreExecutionConfig) -> Self {
        Self {
            spread: config.spread,
            slippage: config.slippage,
        }
    }

    /// Validating constructor.
    pub fn new(spread: f64, slippage: f64) -> Result<Self, ExecutionDomainError> {
        if !spread.is_finite() || spread < 0.0 {
            return Err(ExecutionDomainError::InvalidExecutionSettings {
                reason: format!("spread must be finite and >= 0, got {spread}"),
            });
        }
        if !slippage.is_finite() || slippage < 0.0 {
            return Err(ExecutionDomainError::InvalidExecutionSettings {
                reason: format!("slippage must be finite and >= 0, got {slippage}"),
            });
        }
        Ok(Self { spread, slippage })
    }

    /// Half the configured spread, applied to each side of a market fill.
    pub fn half_spread(&self) -> f64 {
        self.spread / 2.0
    }
}

// ────────────────────────────────────────────────
// Order/protective specifications
// ────────────────────────────────────────────────

/// A generic (strategy-generated) order specification for evaluation.
///
/// `OrderKind` and the order lifecycle [`OrderState`] remain separate
/// concepts (OBS-0004); this spec describes *what* to execute, not *where* the
/// order is in its lifecycle.
#[derive(Debug, Clone, PartialEq)]
pub struct OrderSpec {
    /// MARKET, LIMIT or STOP.
    pub kind: OrderKind,
    /// Buy or Sell.
    pub side: Direction,
    /// Quantity in lots/contracts.
    pub quantity_lots: f64,
    /// Worst acceptable price — required for `OrderKind::Limit`.
    pub limit_price: Option<f64>,
    /// Trigger price — required for `OrderKind::Stop`.
    pub stop_price: Option<f64>,
}

impl OrderSpec {
    /// A MARKET order spec.
    pub fn market(side: Direction, quantity_lots: f64) -> Self {
        Self {
            kind: OrderKind::Market,
            side,
            quantity_lots,
            limit_price: None,
            stop_price: None,
        }
    }

    /// A LIMIT order spec at `limit_price`.
    pub fn limit(side: Direction, quantity_lots: f64, limit_price: f64) -> Self {
        Self {
            kind: OrderKind::Limit,
            side,
            quantity_lots,
            limit_price: Some(limit_price),
            stop_price: None,
        }
    }

    /// A STOP order spec triggered at `stop_price`.
    pub fn stop(side: Direction, quantity_lots: f64, stop_price: f64) -> Self {
        Self {
            kind: OrderKind::Stop,
            side,
            quantity_lots,
            limit_price: None,
            stop_price: Some(stop_price),
        }
    }
}

/// Protective instruction levels attached to an existing position.
///
/// Conceptually separate from generic order kinds: SL is stop/market-style
/// execution; TP is limit-style execution.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ProtectiveLevels {
    /// Protective stop-loss price (per side), when set.
    pub stop_loss: Option<f64>,
    /// Protective take-profit price (per side), when set.
    pub take_profit: Option<f64>,
}

impl ProtectiveLevels {
    pub fn new(stop_loss: Option<f64>, take_profit: Option<f64>) -> Self {
        Self {
            stop_loss,
            take_profit,
        }
    }
}

// ────────────────────────────────────────────────
// Results
// ────────────────────────────────────────────────

/// A resolved fill price with the applied adjustments.
///
/// `executed_price` is the price at which the trade actually executes — it
/// already includes any spread/slippage. Portfolio/accounting must consume
/// this value directly and must not add further execution adjustments.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Fill {
    /// Raw market/reference price before adjustments (for auditing).
    pub raw_reference: f64,
    /// The final execution price.
    pub executed_price: f64,
    /// Magnitude of spread applied (half spread for market-style fills; 0 for
    /// limit-style fills).
    pub spread_applied: f64,
    /// Magnitude of adverse slippage applied (0 for limit-style fills).
    pub slippage_applied: f64,
    /// True when the opening gap delivered a price better than the requested
    /// limit/trigger level (price improvement).
    pub price_improved: bool,
}

/// Whether an order became executable on the evaluated bar.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Outcome {
    /// The order's condition was not met on this bar.
    NotExecutable,
    /// The order executed on this bar.
    Executed(Fill),
}

/// How a protective instruction resolved on the evaluated bar.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ProtectiveOutcome {
    /// Neither protective level became executable on this bar.
    None,
    /// One protective level executed.
    Executed(ProtectiveKind, Fill),
}

// ────────────────────────────────────────────────
// MARKET orders
// ────────────────────────────────────────────────

/// Raw reference price for a MARKET order under the given fill mode.
///
/// * [`FillMode::BarClose`] → `bar.close` (the completed bar the strategy
///   observed).
/// * [`FillMode::NextBarOpen`] → `bar.open` — **the caller must supply the
///   NEXT bar (N+1)**. This primitive never "knows" a signal bar: if the
///   signal bar itself were passed here, its *close* would not be used, and if
///   a caller wants the old (forbidden) signal-bar-open behavior they would
///   have to explicitly pass the wrong bar. OBS-0007 owns the scheduling that
///   guarantees the next bar is supplied.
pub fn market_raw_reference(mode: FillMode, bar: &Bar) -> f64 {
    match mode {
        FillMode::BarClose => bar.close,
        FillMode::NextBarOpen => bar.open,
    }
}

/// Fills a MARKET order against `bar` for the given mode and side.
///
/// Market-style execution always crosses the market:
/// `BUY = reference + half_spread + slippage`, `SELL = reference − half_spread
/// − slippage`. Slippage always worsens the fill.
pub fn market_fill(
    settings: &ExecutionSettings,
    mode: FillMode,
    bar: &Bar,
    side: Direction,
) -> Result<Fill, ExecutionDomainError> {
    let reference = market_raw_reference(mode, bar);
    Ok(market_adjust(settings, reference, side))
}

/// Applies market-style adjustments to a raw execution reference.
pub fn market_adjust(settings: &ExecutionSettings, raw: f64, side: Direction) -> Fill {
    match side {
        Direction::Buy => Fill {
            raw_reference: raw,
            executed_price: raw + settings.half_spread() + settings.slippage,
            spread_applied: settings.half_spread(),
            slippage_applied: settings.slippage,
            price_improved: false,
        },
        Direction::Sell => Fill {
            raw_reference: raw,
            executed_price: raw - settings.half_spread() - settings.slippage,
            spread_applied: settings.half_spread(),
            slippage_applied: settings.slippage,
            price_improved: false,
        },
        Direction::Close => unreachable!("market fills are always BUY or SELL"),
    }
}

// ────────────────────────────────────────────────
// LIMIT orders
// ────────────────────────────────────────────────

/// Evaluates a LIMIT order against one bar.
///
/// Limit execution is price-constrained and receives **no** spread/slippage
/// adjustment. Opening gaps may deliver price improvement:
///
/// BUY:  if `open <= limit` → fill at `open`; else if `low <= limit` → fill at
///       `limit`; else not executable.
/// SELL: if `open >= limit` → fill at `open`; else if `high >= limit` → fill
///       at `limit`; else not executable.
pub fn limit_outcome(bar: &Bar, side: Direction, limit: f64) -> Outcome {
    match side {
        Direction::Buy => {
            if bar.open <= limit {
                Outcome::Executed(Fill {
                    raw_reference: bar.open,
                    executed_price: bar.open,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: bar.open < limit,
                })
            } else if bar.low <= limit {
                Outcome::Executed(Fill {
                    raw_reference: limit,
                    executed_price: limit,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: false,
                })
            } else {
                Outcome::NotExecutable
            }
        }
        Direction::Sell => {
            if bar.open >= limit {
                Outcome::Executed(Fill {
                    raw_reference: bar.open,
                    executed_price: bar.open,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: bar.open > limit,
                })
            } else if bar.high >= limit {
                Outcome::Executed(Fill {
                    raw_reference: limit,
                    executed_price: limit,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: false,
                })
            } else {
                Outcome::NotExecutable
            }
        }
        Direction::Close => Outcome::NotExecutable,
    }
}

// ────────────────────────────────────────────────
// STOP orders
// ────────────────────────────────────────────────

/// Evaluates a STOP order against one bar; once triggered the order becomes
/// market-style execution and receives spread + adverse slippage.
///
/// BUY:  if `open >= stop` → gap through, raw = `open`; else if `high >= stop`
///       → triggered intrabar, raw = `stop`; else not executable.
/// SELL: if `open <= stop` → gap through, raw = `open`; else if
///       `low <= stop` → triggered intrabar, raw = `stop`; else not
///       executable.
pub fn stop_outcome(
    settings: &ExecutionSettings,
    bar: &Bar,
    side: Direction,
    stop: f64,
) -> Outcome {
    let raw = match side {
        Direction::Buy => {
            if bar.open >= stop {
                Some(bar.open)
            } else if bar.high >= stop {
                Some(stop)
            } else {
                None
            }
        }
        Direction::Sell => {
            if bar.open <= stop {
                Some(bar.open)
            } else if bar.low <= stop {
                Some(stop)
            } else {
                None
            }
        }
        Direction::Close => None,
    };
    match raw {
        Some(raw) => Outcome::Executed(market_adjust(settings, raw, side)),
        None => Outcome::NotExecutable,
    }
}

// ────────────────────────────────────────────────
// Protective SL/TP
// ────────────────────────────────────────────────

/// Evaluates the protective SL/TP of one position against one bar
/// (deterministic OHLC convention, OBS-0006 §13–§17).
///
/// Chronology rule (only the opening price is chronologically known):
/// 1. Opening-gap conditions are resolved first (TP gap → favorable limit
///    fill at the open; SL gap → market-style fill at the open).
/// 2. Otherwise intrabar reachability is evaluated from the OHLC range.
/// 3. If both SL and TP are reachable intrabar, **SL is resolved first**.
///    This is an explicit deterministic modeling convention, not a claim about
///    historical tick order.
///
/// `position_side` is `Buy` for a long position and `Sell` for a short one.
pub fn protective_outcome(
    settings: &ExecutionSettings,
    bar: &Bar,
    position_side: Direction,
    levels: &ProtectiveLevels,
) -> ProtectiveOutcome {
    match position_side {
        Direction::Buy => protective_long(settings, bar, levels),
        Direction::Sell => protective_short(settings, bar, levels),
        Direction::Close => ProtectiveOutcome::None,
    }
}

fn protective_long(
    settings: &ExecutionSettings,
    bar: &Bar,
    levels: &ProtectiveLevels,
) -> ProtectiveOutcome {
    // Long position: SL below entry, TP above entry.

    // Gap precedence — TP is limit-style, so a favorable open at/above TP
    // resolves as a take profit at the open.
    if let Some(tp) = levels.take_profit {
        if bar.open >= tp {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::TakeProfit,
                Fill {
                    raw_reference: bar.open,
                    executed_price: bar.open,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: bar.open > tp,
                },
            );
        }
    }
    // SL gap — market-style exit at the actually available opening price.
    if let Some(sl) = levels.stop_loss {
        if bar.open <= sl {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::StopLoss,
                market_adjust(settings, bar.open, Direction::Sell),
            );
        }
    }
    // Intrabar reachability — SL first when both are reachable.
    if let Some(sl) = levels.stop_loss {
        if bar.low <= sl {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::StopLoss,
                market_adjust(settings, sl, Direction::Sell),
            );
        }
    }
    if let Some(tp) = levels.take_profit {
        if bar.high >= tp {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::TakeProfit,
                Fill {
                    raw_reference: tp,
                    executed_price: tp,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: false,
                },
            );
        }
    }
    ProtectiveOutcome::None
}

fn protective_short(
    settings: &ExecutionSettings,
    bar: &Bar,
    levels: &ProtectiveLevels,
) -> ProtectiveOutcome {
    // Short position: SL above entry, TP below entry.

    // SL gap first (market-style exit at the open).
    if let Some(sl) = levels.stop_loss {
        if bar.open >= sl {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::StopLoss,
                market_adjust(settings, bar.open, Direction::Buy),
            );
        }
    }
    // TP gap — favorable limit-style fill at the open.
    if let Some(tp) = levels.take_profit {
        if bar.open <= tp {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::TakeProfit,
                Fill {
                    raw_reference: bar.open,
                    executed_price: bar.open,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: bar.open < tp,
                },
            );
        }
    }
    // Intrabar reachability — SL first when both are reachable.
    if let Some(sl) = levels.stop_loss {
        if bar.high >= sl {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::StopLoss,
                market_adjust(settings, sl, Direction::Buy),
            );
        }
    }
    if let Some(tp) = levels.take_profit {
        if bar.low <= tp {
            return ProtectiveOutcome::Executed(
                ProtectiveKind::TakeProfit,
                Fill {
                    raw_reference: tp,
                    executed_price: tp,
                    spread_applied: 0.0,
                    slippage_applied: 0.0,
                    price_improved: false,
                },
            );
        }
    }
    ProtectiveOutcome::None
}

// ────────────────────────────────────────────────
// Execution-domain validation
// ────────────────────────────────────────────────

/// Validates an order spec against the enabled order model and instrument
/// quantity constraints. Purely execution-domain; performs no affordability
/// checks (balance/margin/leverage are portfolio concerns, OBS-0005).
pub fn validate_order(
    order: &OrderSpec,
    instrument: &InstrumentConfig,
    execution_config: &CoreExecutionConfig,
) -> Result<(), ExecutionDomainError> {
    match order.side {
        Direction::Buy | Direction::Sell => {}
        Direction::Close => {
            return Err(ExecutionDomainError::InvalidSide {
                side: "Close".to_string(),
            })
        }
    }

    if !execution_config.order_model.supports(order.kind) {
        return Err(ExecutionDomainError::UnsupportedOrderKind { kind: order.kind });
    }

    validate_quantity(order.quantity_lots, instrument)?;

    match order.kind {
        OrderKind::Market => {}
        OrderKind::Limit => {
            let price = order
                .limit_price
                .ok_or_else(|| ExecutionDomainError::MissingTriggerPrice { kind: order.kind })?;
            validate_positive_price(price, "limit_price")?;
        }
        OrderKind::Stop => {
            let price = order
                .stop_price
                .ok_or_else(|| ExecutionDomainError::MissingTriggerPrice { kind: order.kind })?;
            validate_positive_price(price, "stop_price")?;
        }
    }
    Ok(())
}

/// Validates protective levels against the position's entry price and side.
///
/// Structural rules: for a long, `stop_loss < entry < take_profit`; for a
/// short, `stop_loss > entry > take_profit`. Any supplied level must be a
/// finite positive price. (Distance-from-fill validation relative to the
/// executed price is applied at order creation by the runtime using the
/// canonical portfolio/execution configuration; this check covers structure.)
pub fn validate_protective_levels(
    entry_price: f64,
    side: Direction,
    levels: &ProtectiveLevels,
) -> Result<(), ExecutionDomainError> {
    validate_positive_price(entry_price, "entry_price")?;
    for (name, price) in [
        ("stop_loss", levels.stop_loss),
        ("take_profit", levels.take_profit),
    ] {
        if let Some(p) = price {
            validate_positive_price(p, name)?;
        }
    }

    let sl = levels.stop_loss;
    let tp = levels.take_profit;
    match side {
        Direction::Buy => {
            if let Some(sl) = sl {
                if sl >= entry_price {
                    return Err(ExecutionDomainError::InvalidProtective {
                        reason: format!("long stop_loss {sl} must be below entry {entry_price}"),
                    });
                }
            }
            if let Some(tp) = tp {
                if tp <= entry_price {
                    return Err(ExecutionDomainError::InvalidProtective {
                        reason: format!("long take_profit {tp} must be above entry {entry_price}"),
                    });
                }
            }
        }
        Direction::Sell => {
            if let Some(sl) = sl {
                if sl <= entry_price {
                    return Err(ExecutionDomainError::InvalidProtective {
                        reason: format!("short stop_loss {sl} must be above entry {entry_price}"),
                    });
                }
            }
            if let Some(tp) = tp {
                if tp >= entry_price {
                    return Err(ExecutionDomainError::InvalidProtective {
                        reason: format!("short take_profit {tp} must be below entry {entry_price}"),
                    });
                }
            }
        }
        Direction::Close => {
            return Err(ExecutionDomainError::InvalidSide {
                side: "Close".to_string(),
            })
        }
    }
    if let (Some(sl), Some(tp)) = (sl, tp) {
        match side {
            Direction::Buy if sl >= tp => {
                return Err(ExecutionDomainError::InvalidProtective {
                    reason: format!("long stop_loss {sl} must be below take_profit {tp}"),
                })
            }
            Direction::Sell if sl <= tp => {
                return Err(ExecutionDomainError::InvalidProtective {
                    reason: format!("short stop_loss {sl} must be above take_profit {tp}"),
                })
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_quantity(
    quantity_lots: f64,
    instrument: &InstrumentConfig,
) -> Result<(), ExecutionDomainError> {
    if !quantity_lots.is_finite() || quantity_lots <= 0.0 {
        return Err(ExecutionDomainError::InvalidQuantity {
            quantity: quantity_lots,
            reason: "quantity must be finite and > 0".to_string(),
        });
    }
    if quantity_lots < instrument.min_quantity || quantity_lots > instrument.max_quantity {
        return Err(ExecutionDomainError::InvalidQuantity {
            quantity: quantity_lots,
            reason: format!(
                "quantity outside allowed range [{}, {}]",
                instrument.min_quantity, instrument.max_quantity
            ),
        });
    }
    // Quantity step: (qty − min) must be (approximately) a multiple of step.
    let step = instrument.quantity_step;
    if step > 0.0 {
        let from_min = quantity_lots - instrument.min_quantity;
        let steps = from_min / step;
        let nearest = steps.round();
        if (steps - nearest).abs() > QUANTITY_EPSILON * nearest.abs().max(1.0) {
            return Err(ExecutionDomainError::InvalidQuantity {
                quantity: quantity_lots,
                reason: format!(
                    "quantity does not respect quantity_step {} (min {})",
                    step, instrument.min_quantity
                ),
            });
        }
    }
    Ok(())
}

fn validate_positive_price(price: f64, field: &str) -> Result<(), ExecutionDomainError> {
    if !price.is_finite() || price <= 0.0 {
        return Err(ExecutionDomainError::InvalidPrice {
            price,
            reason: format!("{field} must be finite and > 0"),
        });
    }
    Ok(())
}

// ────────────────────────────────────────────────
// Deterministic same-bar ordering
// ────────────────────────────────────────────────

/// Monotonic creation sequence assigned to every order by the owning runtime.
///
/// Order IDs are random UUIDs and must never be used as economic chronology.
/// Economic chronology is the creation sequence only.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OrderSeq(pub u64);

/// Deterministic ordering rule for multiple orders executable on the same
/// bar: **ascending creation sequence**.
///
/// The rule is deterministic because the sequence is assigned monotonically at
/// order creation and is never derived from UUIDs, hash iteration, filesystem
/// or thread scheduling. Ties cannot occur when the runtime assigns strictly
/// increasing sequences; if equal sequences were ever present the sort keeps
/// their (runtime-defined, append-ordered) input order because Rust's sort is
/// stable.
pub fn sort_by_sequence<T>(orders: &mut [(OrderSeq, T)]) {
    orders.sort_by_key(|(seq, _)| *seq);
}

/// The canonical order-lifecycle transition table (OBS-0004/OBS-0006 §5).
///
/// Allowed transitions:
/// * `Created → Pending | Filled | Rejected`
/// * `Pending → Triggered | Filled | Expired`
/// * `Triggered → Filled`
/// Any other transition is invalid.
pub fn can_transition(from: OrderState, to: OrderState) -> bool {
    use OrderState::*;
    match (from, to) {
        (Created, Pending) | (Created, Filled) | (Created, Rejected) => true,
        (Pending, Triggered) | (Pending, Filled) | (Pending, Expired) => true,
        (Triggered, Filled) => true,
        _ => false,
    }
}

// ────────────────────────────────────────────────
// Errors
// ────────────────────────────────────────────────

/// Structured execution-domain errors. Deliberately contains no margin or
/// account affordability variants — those belong to the portfolio (OBS-0005).
#[derive(Debug, thiserror::Error, PartialEq)]
pub enum ExecutionDomainError {
    #[error("invalid execution side for this operation: {side}")]
    InvalidSide { side: String },

    #[error("order kind is not enabled in the execution configuration: {kind}")]
    UnsupportedOrderKind { kind: OrderKind },

    #[error("invalid quantity {quantity}: {reason}")]
    InvalidQuantity { quantity: f64, reason: String },

    #[error("invalid price {price}: {reason}")]
    InvalidPrice { price: f64, reason: String },

    #[error("missing trigger price for {kind} order")]
    MissingTriggerPrice { kind: OrderKind },

    #[error("invalid protective levels: {reason}")]
    InvalidProtective { reason: String },

    #[error("invalid execution settings: {reason}")]
    InvalidExecutionSettings { reason: String },
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use observa_core::config::FillMode::{BarClose, NextBarOpen};
    use observa_core::config::OrderModelConfig;

    fn ts() -> chrono::DateTime<chrono::Utc> {
        chrono::DateTime::parse_from_rfc3339("2026-07-10T03:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc)
    }

    fn bar(open: f64, high: f64, low: f64, close: f64) -> Bar {
        Bar::new(ts(), open, high, low, close, None)
    }

    fn settings() -> ExecutionSettings {
        // 2 pips spread, 1 pip slippage on a 5-digit pair.
        ExecutionSettings::new(0.0002, 0.0001).unwrap()
    }

    fn instrument() -> InstrumentConfig {
        InstrumentConfig {
            symbol: "EURUSD".to_string(),
            contract_size: 100_000.0,
            min_quantity: 0.01,
            max_quantity: 100.0,
            quantity_step: 0.01,
            ..Default::default()
        }
    }

    fn execution_config() -> CoreExecutionConfig {
        CoreExecutionConfig {
            fill_mode: FillMode::NextBarOpen,
            spread: 0.0002,
            slippage: 0.0001,
            commission: Default::default(),
            order_model: OrderModelConfig::default(),
        }
    }

    fn fill_of(outcome: Outcome) -> Fill {
        match outcome {
            Outcome::Executed(f) => f,
            Outcome::NotExecutable => panic!("expected executed, got NotExecutable"),
        }
    }

    // ── MARKET: BAR_CLOSE ────────────────────────

    #[test]
    fn market_buy_bar_close_fills_at_close_plus_half_spread_plus_slippage() {
        let b = bar(1.1000, 1.1050, 1.0980, 1.1040);
        let f = market_fill(&settings(), BarClose, &b, Direction::Buy).unwrap();
        assert_eq!(f.raw_reference, b.close);
        let expected = b.close + settings().half_spread() + settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
        assert!((f.spread_applied - 0.0001).abs() < 1e-12);
        assert!((f.slippage_applied - 0.0001).abs() < 1e-12);
    }

    #[test]
    fn market_sell_bar_close_fills_at_close_minus_adjustments() {
        let b = bar(1.1000, 1.1050, 1.0980, 1.1040);
        let f = market_fill(&settings(), BarClose, &b, Direction::Sell).unwrap();
        let expected = b.close - settings().half_spread() - settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
    }

    // ── MARKET: NEXT_BAR_OPEN + regression ───────

    #[test]
    fn market_buy_next_bar_open_uses_next_bar_open() {
        // Signal bar N (the completed bar the strategy observed).
        let signal = bar(1.1000, 1.1060, 1.0990, 1.1050);
        // Next bar N+1, where the queued market order must execute.
        let next = bar(1.1020, 1.1090, 1.1010, 1.1070);

        let f = market_fill(&settings(), NextBarOpen, &next, Direction::Buy).unwrap();
        // Reference is the NEXT bar's open, never the signal bar's open/close.
        assert_eq!(f.raw_reference, next.open);
        assert_ne!(f.raw_reference, signal.open);
        assert_ne!(f.raw_reference, signal.close);
        let expected = next.open + settings().half_spread() + settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
    }

    #[test]
    fn market_sell_next_bar_open_uses_next_bar_open() {
        let signal = bar(1.1000, 1.1060, 1.0990, 1.1050);
        let next = bar(1.1020, 1.1090, 1.1010, 1.1070);
        let f = market_fill(&settings(), NextBarOpen, &next, Direction::Sell).unwrap();
        assert_eq!(f.raw_reference, next.open);
        assert_ne!(f.raw_reference, signal.open);
        let expected = next.open - settings().half_spread() - settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
    }

    #[test]
    fn next_bar_open_never_uses_signal_bar_open_regression() {
        // The historical defect filled against the signal bar's open. This
        // regression documents that the primitive references the open of the
        // bar it is GIVEN (which the runtime must supply as bar N+1), and that
        // the signal bar's open is not reachable through the reference rule.
        let signal = bar(1.1000, 1.1060, 1.0990, 1.1050);
        let next = bar(1.1020, 1.1090, 1.1010, 1.1070);
        assert_eq!(market_raw_reference(NextBarOpen, &next), next.open);
        assert_ne!(market_raw_reference(NextBarOpen, &next), signal.open);
        // Sanity: BarClose references close, which is also not the signal open.
        assert_eq!(market_raw_reference(BarClose, &next), next.close);
        assert_ne!(market_raw_reference(BarClose, &next), signal.open);
    }

    // ── MARKET: side adjustments are always adverse ──

    #[test]
    fn slippage_never_improves_a_market_fill() {
        let b = bar(1.1000, 1.1050, 1.0980, 1.1040);
        let buy = market_fill(&settings(), BarClose, &b, Direction::Buy).unwrap();
        let sell = market_fill(&settings(), BarClose, &b, Direction::Sell).unwrap();
        assert!(buy.executed_price > b.close);
        assert!(sell.executed_price < b.close);
    }

    // ── LIMIT ────────────────────────────────────

    #[test]
    fn buy_limit_untouched_remains_pending() {
        let b = bar(1.1000, 1.1020, 1.0990, 1.1010);
        assert_eq!(
            limit_outcome(&b, Direction::Buy, 1.0980),
            Outcome::NotExecutable
        );
    }

    #[test]
    fn buy_limit_touched_intrabar_fills_at_limit() {
        let b = bar(1.1000, 1.1020, 1.0975, 1.1010);
        let f = fill_of(limit_outcome(&b, Direction::Buy, 1.0980));
        assert!((f.executed_price - 1.0980).abs() < 1e-12);
        assert_eq!(f.spread_applied, 0.0);
        assert_eq!(f.slippage_applied, 0.0);
        assert!(!f.price_improved);
    }

    #[test]
    fn buy_limit_opening_gap_improves_price() {
        // BUY LIMIT 100, open 98 → fill at 98.
        let b = bar(98.0, 99.0, 97.0, 98.5);
        let f = fill_of(limit_outcome(&b, Direction::Buy, 100.0));
        assert!((f.executed_price - 98.0).abs() < 1e-12);
        assert!(f.price_improved);
        assert_eq!(f.slippage_applied, 0.0);
    }

    #[test]
    fn sell_limit_untouched_remains_pending() {
        let b = bar(1.1000, 1.1020, 1.0990, 1.1010);
        assert_eq!(
            limit_outcome(&b, Direction::Sell, 1.1050),
            Outcome::NotExecutable
        );
    }

    #[test]
    fn sell_limit_touched_intrabar_fills_at_limit() {
        let b = bar(1.1000, 1.1055, 1.0990, 1.1010);
        let f = fill_of(limit_outcome(&b, Direction::Sell, 1.1050));
        assert!((f.executed_price - 1.1050).abs() < 1e-12);
        assert_eq!(f.slippage_applied, 0.0);
    }

    #[test]
    fn sell_limit_opening_gap_improves_price() {
        // SELL LIMIT 100, open 102 → fill at 102.
        let b = bar(102.0, 103.0, 101.0, 102.5);
        let f = fill_of(limit_outcome(&b, Direction::Sell, 100.0));
        assert!((f.executed_price - 102.0).abs() < 1e-12);
        assert!(f.price_improved);
    }

    // ── STOP ─────────────────────────────────────

    #[test]
    fn buy_stop_untouched_remains_pending() {
        let b = bar(1.1000, 1.1030, 1.0990, 1.1010);
        assert_eq!(
            stop_outcome(&settings(), &b, Direction::Buy, 1.1050),
            Outcome::NotExecutable
        );
    }

    #[test]
    fn buy_stop_triggered_intrabar_becomes_market() {
        // Triggered at high >= stop → raw reference = stop, then market
        // adjustments (buy: +half spread + slippage).
        let b = bar(1.1000, 1.1055, 1.0990, 1.1010);
        let f = fill_of(stop_outcome(&settings(), &b, Direction::Buy, 1.1050));
        assert!((f.raw_reference - 1.1050).abs() < 1e-12);
        let expected = 1.1050 + settings().half_spread() + settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
    }

    #[test]
    fn buy_stop_opening_gap_through_uses_open() {
        // BUY STOP 100, open 103 → raw reference 103.
        let b = bar(103.0, 105.0, 102.0, 104.0);
        let f = fill_of(stop_outcome(&settings(), &b, Direction::Buy, 100.0));
        assert!((f.raw_reference - 103.0).abs() < 1e-12);
        assert!(f.executed_price > 103.0);
    }

    #[test]
    fn sell_stop_untouched_remains_pending() {
        let b = bar(1.1000, 1.1030, 1.0990, 1.1010);
        assert_eq!(
            stop_outcome(&settings(), &b, Direction::Sell, 1.0950),
            Outcome::NotExecutable
        );
    }

    #[test]
    fn sell_stop_triggered_intrabar_becomes_market() {
        let b = bar(1.1000, 1.1030, 1.0945, 1.1010);
        let f = fill_of(stop_outcome(&settings(), &b, Direction::Sell, 1.0950));
        assert!((f.raw_reference - 1.0950).abs() < 1e-12);
        let expected = 1.0950 - settings().half_spread() - settings().slippage;
        assert!((f.executed_price - expected).abs() < 1e-12);
    }

    #[test]
    fn sell_stop_opening_gap_through_uses_open() {
        let b = bar(97.0, 98.0, 96.0, 97.5);
        let f = fill_of(stop_outcome(&settings(), &b, Direction::Sell, 100.0));
        assert!((f.raw_reference - 97.0).abs() < 1e-12);
        assert!(f.executed_price < 97.0);
    }

    // ── Protective SL (market style) ─────────────

    fn long_levels() -> ProtectiveLevels {
        ProtectiveLevels::new(Some(1.0950), Some(1.1100))
    }

    #[test]
    fn long_sl_untouched() {
        let b = bar(1.1000, 1.1050, 1.0970, 1.1030);
        assert_eq!(
            protective_outcome(&settings(), &b, Direction::Buy, &long_levels()),
            ProtectiveOutcome::None
        );
    }

    #[test]
    fn long_sl_touched_intrabar_receives_market_adjustments() {
        let b = bar(1.1000, 1.1030, 1.0940, 1.0990);
        match protective_outcome(&settings(), &b, Direction::Buy, &long_levels()) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 1.0950).abs() < 1e-12);
                // Long exits by SELLING: raw − half spread − slippage (worse).
                let expected = 1.0950 - settings().half_spread() - settings().slippage;
                assert!((f.executed_price - expected).abs() < 1e-12);
            }
            other => panic!("expected SL execution, got {other:?}"),
        }
    }

    #[test]
    fn long_sl_opening_gap_through_uses_open_not_stale_sl() {
        // Long SL 100, next open 97 → exit at 97 (adjusted), never 100.
        let b = bar(97.0, 98.0, 96.0, 97.4);
        let levels = ProtectiveLevels::new(Some(100.0), None);
        match protective_outcome(&settings(), &b, Direction::Buy, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 97.0).abs() < 1e-12);
                assert!(f.executed_price < 97.0);
            }
            other => panic!("expected SL gap execution, got {other:?}"),
        }
    }

    #[test]
    fn short_sl_opening_gap_through_uses_open() {
        let b = bar(105.0, 106.0, 104.0, 105.5);
        let levels = ProtectiveLevels::new(Some(100.0), None); // short SL above entry
        match protective_outcome(&settings(), &b, Direction::Sell, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 105.0).abs() < 1e-12);
                assert!(f.executed_price > 105.0);
            }
            other => panic!("expected SL gap execution, got {other:?}"),
        }
    }

    #[test]
    fn short_sl_touched_intrabar() {
        // Short SL 102, bar high >= 102 → SL (buy to cover, market style).
        let b = bar(100.0, 102.5, 99.0, 101.0);
        let levels = ProtectiveLevels::new(Some(102.0), Some(98.0));
        match protective_outcome(&settings(), &b, Direction::Sell, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 102.0).abs() < 1e-12);
                let expected = 102.0 + settings().half_spread() + settings().slippage;
                assert!((f.executed_price - expected).abs() < 1e-12);
            }
            other => panic!("expected SL execution, got {other:?}"),
        }
    }

    // ── Protective TP (limit style) ──────────────

    #[test]
    fn long_tp_touched_intrabar_no_slippage() {
        let b = bar(1.1000, 1.1110, 1.0990, 1.1080);
        match protective_outcome(&settings(), &b, Direction::Buy, &long_levels()) {
            ProtectiveOutcome::Executed(ProtectiveKind::TakeProfit, f) => {
                assert!((f.executed_price - 1.1100).abs() < 1e-12);
                assert_eq!(f.slippage_applied, 0.0);
                assert_eq!(f.spread_applied, 0.0);
            }
            other => panic!("expected TP execution, got {other:?}"),
        }
    }

    #[test]
    fn long_tp_favorable_opening_gap() {
        // Long TP 110, open 113 → fill at 113 (better), no slippage.
        let b = bar(113.0, 115.0, 112.0, 114.0);
        let levels = ProtectiveLevels::new(None, Some(110.0));
        match protective_outcome(&settings(), &b, Direction::Buy, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::TakeProfit, f) => {
                assert!((f.executed_price - 113.0).abs() < 1e-12);
                assert!(f.price_improved);
                assert_eq!(f.slippage_applied, 0.0);
            }
            other => panic!("expected TP gap execution, got {other:?}"),
        }
    }

    #[test]
    fn short_tp_favorable_opening_gap() {
        let b = bar(96.0, 97.0, 95.0, 96.5);
        let levels = ProtectiveLevels::new(None, Some(100.0)); // short TP below? no—gap test short TP above? short TP below entry; entry was e.g. 102 → TP 100; open 96 <= 100 → fill 96
        match protective_outcome(&settings(), &b, Direction::Sell, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::TakeProfit, f) => {
                assert!((f.executed_price - 96.0).abs() < 1e-12);
                assert!(f.price_improved);
                assert_eq!(f.slippage_applied, 0.0);
            }
            other => panic!("expected TP gap execution, got {other:?}"),
        }
    }

    #[test]
    fn short_tp_touched_intrabar_no_slippage() {
        let b = bar(102.0, 103.0, 99.5, 101.0);
        let levels = ProtectiveLevels::new(Some(105.0), Some(100.0));
        match protective_outcome(&settings(), &b, Direction::Sell, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::TakeProfit, f) => {
                assert!((f.executed_price - 100.0).abs() < 1e-12);
                assert_eq!(f.slippage_applied, 0.0);
            }
            other => panic!("expected TP execution, got {other:?}"),
        }
    }

    // ── Same-bar SL/TP ambiguity: SL first ───────

    #[test]
    fn long_sl_and_tp_both_reachable_sl_first() {
        // open 100, high 110, low 90, close 105; SL 95, TP 108 (ticket §16).
        let b = bar(100.0, 110.0, 90.0, 105.0);
        let levels = ProtectiveLevels::new(Some(95.0), Some(108.0));
        match protective_outcome(&settings(), &b, Direction::Buy, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 95.0).abs() < 1e-12);
            }
            other => panic!("expected SL-first resolution, got {other:?}"),
        }
    }

    #[test]
    fn short_sl_and_tp_both_reachable_sl_first() {
        let b = bar(100.0, 110.0, 90.0, 105.0);
        let levels = ProtectiveLevels::new(Some(108.0), Some(92.0));
        match protective_outcome(&settings(), &b, Direction::Sell, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 108.0).abs() < 1e-12);
            }
            other => panic!("expected SL-first resolution, got {other:?}"),
        }
    }

    #[test]
    fn opening_gap_resolves_before_generic_sl_first() {
        // Long SL 95, TP 110; open 112 (>= TP): gap TP must win even though
        // the bar also contains the SL range (low 90).
        let b = bar(112.0, 115.0, 90.0, 113.0);
        let levels = ProtectiveLevels::new(Some(95.0), Some(110.0));
        match protective_outcome(&settings(), &b, Direction::Buy, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::TakeProfit, f) => {
                assert!((f.executed_price - 112.0).abs() < 1e-12);
            }
            other => panic!("expected opening-gap TP resolution, got {other:?}"),
        }
    }

    #[test]
    fn opening_sl_gap_resolves_over_intrabar_tp() {
        // Long SL 96, TP 110; open 94 (<= SL): gap SL wins even though high
        // later reaches TP.
        let b = bar(94.0, 111.0, 93.0, 108.0);
        let levels = ProtectiveLevels::new(Some(96.0), Some(110.0));
        match protective_outcome(&settings(), &b, Direction::Buy, &levels) {
            ProtectiveOutcome::Executed(ProtectiveKind::StopLoss, f) => {
                assert!((f.raw_reference - 94.0).abs() < 1e-12);
            }
            other => panic!("expected opening-gap SL resolution, got {other:?}"),
        }
    }

    // ── Deterministic same-bar ordering ──────────

    #[test]
    fn executable_orders_sort_by_creation_sequence() {
        let mut entries = vec![
            (OrderSeq(3), "third"),
            (OrderSeq(1), "first"),
            (OrderSeq(2), "second"),
        ];
        sort_by_sequence(&mut entries);
        assert_eq!(
            entries.iter().map(|(_, s)| *s).collect::<Vec<_>>(),
            vec!["first", "second", "third"]
        );
        // Re-running with a different input order yields the same result.
        let mut entries2 = vec![
            (OrderSeq(2), "second"),
            (OrderSeq(3), "third"),
            (OrderSeq(1), "first"),
        ];
        sort_by_sequence(&mut entries2);
        assert_eq!(
            entries2.iter().map(|(_, s)| *s).collect::<Vec<_>>(),
            vec!["first", "second", "third"]
        );
    }

    #[test]
    fn repeated_evaluation_is_identical() {
        let b = bar(100.0, 110.0, 90.0, 105.0);
        let levels = ProtectiveLevels::new(Some(95.0), Some(108.0));
        let a = protective_outcome(&settings(), &b, Direction::Buy, &levels);
        let b2 = protective_outcome(&settings(), &b, Direction::Buy, &levels);
        assert_eq!(a, b2);
        let stop = stop_outcome(&settings(), &b, Direction::Buy, 103.0);
        assert_eq!(stop, stop_outcome(&settings(), &b, Direction::Buy, 103.0));
    }

    // ── Validation ───────────────────────────────

    #[test]
    fn validates_quantity_bounds_and_step() {
        let cfg = execution_config();
        let instr = instrument();
        assert!(validate_order(&OrderSpec::market(Direction::Buy, 1.0), &instr, &cfg).is_ok());
        assert!(validate_order(&OrderSpec::market(Direction::Buy, 0.001), &instr, &cfg).is_err());
        assert!(validate_order(&OrderSpec::market(Direction::Buy, 1.005), &instr, &cfg).is_err());
        assert!(validate_order(&OrderSpec::market(Direction::Buy, -1.0), &instr, &cfg).is_err());
        assert!(validate_order(&OrderSpec::market(Direction::Close, 1.0), &instr, &cfg).is_err());
    }

    #[test]
    fn validates_order_kind_support_and_prices() {
        let mut cfg = execution_config();
        let instr = instrument();
        assert!(
            validate_order(&OrderSpec::limit(Direction::Buy, 1.0, 1.0980), &instr, &cfg).is_ok()
        );
        assert!(
            validate_order(&OrderSpec::limit(Direction::Buy, 1.0, -1.0), &instr, &cfg).is_err()
        );
        assert!(
            validate_order(&OrderSpec::stop(Direction::Sell, 1.0, 1.1050), &instr, &cfg).is_ok()
        );
        assert!(validate_order(
            &OrderSpec::stop(Direction::Sell, 1.0, f64::NAN),
            &instr,
            &cfg
        )
        .is_err());
        // A LIMIT spec without a limit price is structurally invalid.
        let no_price = OrderSpec {
            kind: OrderKind::Limit,
            side: Direction::Buy,
            quantity_lots: 1.0,
            limit_price: None,
            stop_price: None,
        };
        assert!(validate_order(&no_price, &instr, &cfg).is_err());

        // Order model gates the kind.
        cfg.order_model = OrderModelConfig {
            market: true,
            limit: false,
            stop: true,
        };
        assert!(
            validate_order(&OrderSpec::limit(Direction::Buy, 1.0, 1.09), &instr, &cfg).is_err()
        );
    }

    #[test]
    fn validates_protective_structure() {
        // Long: SL below entry, TP above entry.
        let long_ok = ProtectiveLevels::new(Some(1.0950), Some(1.1100));
        assert!(validate_protective_levels(1.1000, Direction::Buy, &long_ok).is_ok());
        let long_bad_sl = ProtectiveLevels::new(Some(1.1050), Some(1.1100));
        assert!(validate_protective_levels(1.1000, Direction::Buy, &long_bad_sl).is_err());
        let long_bad_tp = ProtectiveLevels::new(Some(1.0950), Some(1.0900));
        assert!(validate_protective_levels(1.1000, Direction::Buy, &long_bad_tp).is_err());

        // Short: SL above entry, TP below entry.
        let short_ok = ProtectiveLevels::new(Some(1.1050), Some(1.0950));
        assert!(validate_protective_levels(1.1000, Direction::Sell, &short_ok).is_ok());
        let short_bad = ProtectiveLevels::new(Some(1.0950), Some(1.0900));
        assert!(validate_protective_levels(1.1000, Direction::Sell, &short_bad).is_err());

        // Structural ordering between levels.
        let crossed = ProtectiveLevels::new(Some(1.1100), Some(1.0950));
        assert!(validate_protective_levels(1.1000, Direction::Buy, &crossed).is_err());
        assert!(validate_protective_levels(1.1000, Direction::Close, &long_ok).is_err());
    }

    #[test]
    fn invalid_settings_rejected() {
        assert!(ExecutionSettings::new(-0.0002, 0.0001).is_err());
        assert!(ExecutionSettings::new(0.0002, f64::NAN).is_err());
        assert!(ExecutionSettings::new(0.0, 0.0).is_ok());
    }

    // ── Order lifecycle transitions ──────────────

    #[test]
    fn market_lifecycle_created_to_filled() {
        assert!(can_transition(OrderState::Created, OrderState::Filled));
        assert!(can_transition(OrderState::Created, OrderState::Pending));
        assert!(can_transition(OrderState::Pending, OrderState::Filled));
    }

    #[test]
    fn limit_stop_lifecycle_created_pending_triggered_filled() {
        assert!(can_transition(OrderState::Created, OrderState::Pending));
        assert!(can_transition(OrderState::Pending, OrderState::Triggered));
        assert!(can_transition(OrderState::Triggered, OrderState::Filled));
    }

    #[test]
    fn invalid_transitions_rejected() {
        assert!(!can_transition(OrderState::Filled, OrderState::Pending));
        assert!(!can_transition(OrderState::Pending, OrderState::Created));
        assert!(!can_transition(OrderState::Expired, OrderState::Triggered));
        assert!(!can_transition(OrderState::Rejected, OrderState::Filled));
        assert!(!can_transition(OrderState::Triggered, OrderState::Expired));
        assert!(can_transition(OrderState::Created, OrderState::Rejected));
        assert!(can_transition(OrderState::Pending, OrderState::Expired));
    }

    // ── Financial boundary (structural) ──────────

    #[test]
    fn execution_settings_contain_no_account_financial_fields() {
        // Compile-time-ish structural guarantee: ExecutionSettings carries only
        // spread/slippage. There is no balance/leverage/margin field on the
        // type, and no evaluator accepts one, so execution cannot perform an
        // affordability check (OBS-0005 remains the sole financial authority).
        let s = ExecutionSettings::new(0.0002, 0.0001).unwrap();
        assert_eq!(s.spread, 0.0002);
        assert_eq!(s.slippage, 0.0001);
        assert!((s.half_spread() - 0.0001).abs() < 1e-12);
    }
}
