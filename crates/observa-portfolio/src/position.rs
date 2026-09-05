use chrono::{DateTime, Utc};
use uuid::Uuid;

use observa_core::types::{Direction, ExitReason};
use observa_core::units::pnl_amount;

// ────────────────────────────────────────────────
// PositionStatus
// ────────────────────────────────────────────────

/// Whether a position is currently open or closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PositionStatus {
    Open,
    Closed,
}

// ────────────────────────────────────────────────
// Position
// ────────────────────────────────────────────────

/// A single, independently accounted position — from its opening fill to its
/// (full) closing fill (OBS-0005 position model).
///
/// Every fill that opens exposure creates a distinct `Position`; positions are
/// never merged, netted or FIFO-selected. Long and short positions on the same
/// instrument may coexist and each keeps its own identity, quantity, P&L,
/// SL/TP and lifecycle.
///
/// Accounting invariants implemented here:
/// * monetary P&L is computed with the canonical contract-size formula
///   `(exit - entry) × quantity_lots × contract_size × direction` via
///   [`observa_core::units`] — contract size is per-position configuration
///   captured at open, never a hard-coded broker constant.
/// * [`Position::close`] books **gross** realized P&L only. Commission is not
///   computed or deducted inside the position; the portfolio books
///   already-calculated commission amounts separately (OBS-0005 §20/§21).
#[derive(Debug, Clone)]
pub struct Position {
    /// Unique, run-scoped position identity (the "ticket").
    pub position_id: Uuid,
    /// Order that opened this position.
    pub order_id: Uuid,
    /// Fill that opened this position, when the execution layer supplies one.
    pub fill_id: Option<Uuid>,
    /// Instrument symbol.
    pub symbol: String,
    /// Long (Buy) or short (Sell). A `Direction::Close` is never a position
    /// direction; closes target positions by ticket.
    pub direction: Direction,
    /// Position quantity in lots/contracts.
    pub quantity_lots: f64,
    /// Base units per lot, from instrument configuration at open time.
    pub contract_size: f64,
    /// Executed entry price.
    pub entry_price: f64,
    /// Current protective stop-loss price, when set.
    pub stop_loss: Option<f64>,
    /// Current protective take-profit price, when set.
    pub take_profit: Option<f64>,
    /// When the position was opened.
    pub opened_at: DateTime<Utc>,
    /// When the position was closed — `None` while open.
    pub closed_at: Option<DateTime<Utc>>,
    /// Exit price — `None` while open.
    pub exit_price: Option<f64>,
    /// How the position closed — `None` while open.
    pub exit_reason: Option<ExitReason>,
    /// Current lifecycle status.
    pub status: PositionStatus,
    /// Gross realized P&L, set when the position closes (before commission).
    pub realised_pnl: f64,
    /// Total commission booked against this position across its lifetime
    /// (entry leg under PER_SIDE plus the closing leg). Booked by the
    /// portfolio, never computed here.
    pub commission_paid: f64,
}

impl Position {
    /// Creates a new open position from an opening fill.
    ///
    /// `quantity_lots` must already be validated by the caller (finite and
    /// positive); `direction` must be `Buy` or `Sell` (the portfolio enforces
    /// this before construction).
    pub fn new(
        position_id: Uuid,
        order_id: Uuid,
        fill_id: Option<Uuid>,
        symbol: String,
        direction: Direction,
        quantity_lots: f64,
        contract_size: f64,
        entry_price: f64,
        stop_loss: Option<f64>,
        take_profit: Option<f64>,
        opened_at: DateTime<Utc>,
    ) -> Self {
        Self {
            position_id,
            order_id,
            fill_id,
            symbol,
            direction,
            quantity_lots,
            contract_size,
            entry_price,
            stop_loss,
            take_profit,
            opened_at,
            closed_at: None,
            exit_price: None,
            exit_reason: None,
            status: PositionStatus::Open,
            realised_pnl: 0.0,
            commission_paid: 0.0,
        }
    }

    /// Returns true while the position is still open.
    pub fn is_open(&self) -> bool {
        self.status == PositionStatus::Open
    }

    /// Base units of the position: `quantity_lots × contract_size`.
    pub fn units(&self) -> f64 {
        self.quantity_lots * self.contract_size
    }

    /// Direction multiplier for P&L: LONG = +1, SHORT = -1.
    pub fn direction_multiplier(&self) -> f64 {
        match self.direction {
            Direction::Buy => 1.0,
            Direction::Sell => -1.0,
            // A position can never be opened with Direction::Close; the
            // portfolio rejects such opens. Kept total for exhaustive matches.
            Direction::Close => 0.0,
        }
    }

    /// Unrealized P&L of an **open** position at `current_price`
    /// (canonical contract-size formula). Returns 0 for closed positions.
    pub fn unrealised_pnl(&self, current_price: f64) -> f64 {
        if !self.is_open() {
            return 0.0;
        }
        pnl_amount(
            self.entry_price,
            current_price,
            self.quantity_lots,
            self.contract_size,
            self.direction_multiplier(),
        )
    }

    /// Checks whether the stop-loss was hit by this bar.
    /// Returns the stop price if hit, `None` otherwise.
    pub fn check_sl(&self, bar_low: f64, bar_high: f64) -> Option<f64> {
        let sl = self.stop_loss?;
        match self.direction {
            // Long — SL is below entry; hit if the bar's low touches/breaks it.
            Direction::Buy if bar_low <= sl => Some(sl),
            // Short — SL is above entry; hit if the bar's high touches/breaks it.
            Direction::Sell if bar_high >= sl => Some(sl),
            _ => None,
        }
    }

    /// Checks whether the take-profit was hit by this bar.
    /// Returns the take-profit price if hit, `None` otherwise.
    pub fn check_tp(&self, bar_low: f64, bar_high: f64) -> Option<f64> {
        let tp = self.take_profit?;
        match self.direction {
            // Long — TP is above entry.
            Direction::Buy if bar_high >= tp => Some(tp),
            // Short — TP is below entry.
            Direction::Sell if bar_low <= tp => Some(tp),
            _ => None,
        }
    }

    /// Closes this position at the given price/reason/time and returns the
    /// **gross** realized P&L (canonical formula, no commission).
    pub fn close(
        &mut self,
        exit_price: f64,
        exit_reason: ExitReason,
        closed_at: DateTime<Utc>,
    ) -> f64 {
        let gross = pnl_amount(
            self.entry_price,
            exit_price,
            self.quantity_lots,
            self.contract_size,
            self.direction_multiplier(),
        );
        self.exit_price = Some(exit_price);
        self.exit_reason = Some(exit_reason);
        self.closed_at = Some(closed_at);
        self.status = PositionStatus::Closed;
        self.realised_pnl = gross;
        gross
    }
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    const EURUSD_CONTRACT: f64 = 100_000.0;

    fn ts() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 7, 10, 3, 0, 0).unwrap()
    }

    fn test_position(direction: Direction, contract: f64) -> Position {
        Position::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            None,
            "EURUSD".to_string(),
            direction,
            1.0,
            contract,
            1.1000, // entry price
            match direction {
                Direction::Buy => Some(1.0950),
                Direction::Sell => Some(1.1050),
                Direction::Close => None,
            },
            match direction {
                Direction::Buy => Some(1.1100),
                Direction::Sell => Some(1.0900),
                Direction::Close => None,
            },
            ts(),
        )
    }

    #[test]
    fn new_position_is_open_with_zero_pnl() {
        let p = test_position(Direction::Buy, EURUSD_CONTRACT);
        assert!(p.is_open());
        assert_eq!(p.realised_pnl, 0.0);
        assert_eq!(p.commission_paid, 0.0);
        assert!(p.exit_price.is_none());
        assert_eq!(p.units(), 100_000.0);
    }

    #[test]
    fn direction_multipliers_are_long_plus_short_minus() {
        assert_eq!(
            test_position(Direction::Buy, 1.0).direction_multiplier(),
            1.0
        );
        assert_eq!(
            test_position(Direction::Sell, 1.0).direction_multiplier(),
            -1.0
        );
    }

    #[test]
    fn units_use_configured_contract_size() {
        // Stock-style contract: 100 shares.
        let p = Position::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            None,
            "AAPL".to_string(),
            Direction::Buy,
            100.0,
            1.0,
            182.50,
            None,
            None,
            ts(),
        );
        assert_eq!(p.units(), 100.0);
        assert_eq!(p.quantity_lots, 100.0);
    }

    #[test]
    fn unrealised_pnl_long_uses_contract_size() {
        let p = test_position(Direction::Buy, EURUSD_CONTRACT);
        // Entry 1.1000 → price 1.1010: 10 pips on 1 lot = +$100.
        let pnl = p.unrealised_pnl(1.1010);
        assert!((pnl - 100.0).abs() < 1e-6);
    }

    #[test]
    fn unrealised_pnl_short_uses_contract_size() {
        let p = test_position(Direction::Sell, EURUSD_CONTRACT);
        // Short entry 1.1000, price falls to 1.0990 → +$100.
        let pnl = p.unrealised_pnl(1.0990);
        assert!((pnl - 100.0).abs() < 1e-6);
    }

    #[test]
    fn unrealised_pnl_zero_for_closed_position() {
        let mut p = test_position(Direction::Buy, EURUSD_CONTRACT);
        p.close(1.1050, ExitReason::TakeProfit, ts());
        assert_eq!(p.unrealised_pnl(1.1010), 0.0);
    }

    #[test]
    fn close_returns_gross_pnl_and_marks_closed() {
        let mut p = test_position(Direction::Buy, EURUSD_CONTRACT);
        // Entry 1.1000 → exit 1.1050: 50 pips × $10 = +$500 gross.
        let gross = p.close(1.1050, ExitReason::TakeProfit, ts());
        assert!((gross - 500.0).abs() < 1e-6);
        assert!(!p.is_open());
        assert_eq!(p.exit_reason, Some(ExitReason::TakeProfit));
        assert_eq!(p.realised_pnl, gross);
        // Commission is never deducted inside the position.
        assert_eq!(p.commission_paid, 0.0);
    }

    #[test]
    fn close_loss_is_negative() {
        let mut p = test_position(Direction::Buy, EURUSD_CONTRACT);
        let gross = p.close(1.0950, ExitReason::StopLoss, ts());
        assert!((gross + 500.0).abs() < 1e-6);
    }

    #[test]
    fn gold_contract_size_pnl() {
        // Gold CFD: contract 100 oz, 1 lot, $1 move.
        let mut p = Position::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            None,
            "XAUUSD".to_string(),
            Direction::Buy,
            1.0,
            100.0,
            1923.45,
            None,
            None,
            ts(),
        );
        let gross = p.close(1924.45, ExitReason::TakeProfit, ts());
        assert!((gross - 100.0).abs() < 1e-6);
    }

    #[test]
    fn equity_style_contract_size_pnl() {
        // 100 shares of a contract-size-1 instrument, $2.50 move.
        let mut p = Position::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            None,
            "AAPL".to_string(),
            Direction::Buy,
            100.0,
            1.0,
            182.50,
            None,
            None,
            ts(),
        );
        let gross = p.close(185.00, ExitReason::TakeProfit, ts());
        assert!((gross - 250.0).abs() < 1e-6);
    }

    #[test]
    fn sl_and_tp_detection_by_direction() {
        let long = test_position(Direction::Buy, EURUSD_CONTRACT);
        assert!(long.check_sl(1.0940, 1.0990).is_some()); // low broke 1.0950
        assert!(long.check_sl(1.0960, 1.0990).is_none());
        assert!(long.check_tp(1.0990, 1.1110).is_some()); // high reached 1.1100
        assert!(long.check_tp(1.0990, 1.1090).is_none());

        let short = test_position(Direction::Sell, EURUSD_CONTRACT);
        assert!(short.check_sl(1.1010, 1.1060).is_some()); // high broke 1.1050
        assert!(short.check_tp(1.0890, 1.1010).is_some()); // low reached 1.0900
    }

    #[test]
    fn sl_takes_priority_when_both_reachable() {
        let p = test_position(Direction::Buy, EURUSD_CONTRACT);
        assert!(p.check_sl(1.0940, 1.1110).is_some());
        assert!(p.check_tp(1.0940, 1.1110).is_some());
        // Priority is a convention of the caller (SL first); both detectable.
    }
}
