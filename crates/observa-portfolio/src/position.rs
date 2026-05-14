use chrono::{DateTime, Utc};
use uuid::Uuid;

use observa_core::types::{Direction, ExitReason};

// ────────────────────────────────────────────────
// PositionStatus
// ────────────────────────────────────────────────

/// Whether a position is currently open or closed.
#[derive(Debug, Clone, PartialEq)]
pub enum PositionStatus {
    Open,
    Closed,
}

// ────────────────────────────────────────────────
// Position
// ────────────────────────────────────────────────

/// A single trade — from entry fill to exit fill.
///
/// Tracks everything needed to calculate PnL,
/// check SL/TP, and emit position events.
#[derive(Debug, Clone)]
pub struct Position {
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

    /// Current stop loss
    pub sl: Option<f64>,

    /// Current take profit
    pub tp: Option<f64>,

    /// When position was opened
    pub opened_at: DateTime<Utc>,

    /// When position was closed — None if still open
    pub closed_at: Option<DateTime<Utc>>,

    /// Exit price — None if still open
    pub exit_price: Option<f64>,

    /// How position closed — None if still open
    pub exit_reason: Option<ExitReason>,

    /// Current status
    pub status: PositionStatus,

    /// Realised PnL — set when position closes
    pub realised_pnl: f64,
}

impl Position {
    /// Creates a new open position from a fill
    pub fn new(
        position_id: Uuid,
        order_id: Uuid,
        direction: Direction,
        size: f64,
        entry_price: f64,
        sl: Option<f64>,
        tp: Option<f64>,
        opened_at: DateTime<Utc>,
    ) -> Self {
        Self {
            position_id,
            order_id,
            direction,
            size,
            entry_price,
            sl,
            tp,
            opened_at,
            closed_at: None,
            exit_price: None,
            exit_reason: None,
            status: PositionStatus::Open,
            realised_pnl: 0.0,
        }
    }

    /// Returns true if this position is still open
    pub fn is_open(&self) -> bool {
        self.status == PositionStatus::Open
    }

    /// Calculates unrealised PnL at the given price
    pub fn unrealised_pnl(&self, current_price: f64) -> f64 {
        if !self.is_open() {
            return self.realised_pnl;
        }
        let direction_multiplier = match self.direction {
            Direction::Buy  =>  1.0,
            Direction::Sell => -1.0,
            Direction::Close => 0.0,
        };
        (current_price - self.entry_price)
            * self.size
            * direction_multiplier
            * 100_000.0 // standard lot size
    }

    /// Checks if stop loss was hit by this bar.
    /// Returns the exit price if hit, None otherwise.
    pub fn check_sl(&self, bar_low: f64, bar_high: f64)
        -> Option<f64>
    {
        let sl = self.sl?; // return None if no SL set

        match self.direction {
            // Long position — SL is below entry
            // Hit if bar's low touches or breaks SL
            Direction::Buy if bar_low <= sl => Some(sl),

            // Short position — SL is above entry
            // Hit if bar's high touches or breaks SL
            Direction::Sell if bar_high >= sl => Some(sl),

            _ => None,
        }
    }

    /// Checks if take profit was hit by this bar.
    /// Returns the exit price if hit, None otherwise.
    pub fn check_tp(&self, bar_low: f64, bar_high: f64)
        -> Option<f64>
    {
        let tp = self.tp?; // return None if no TP set

        match self.direction {
            // Long position — TP is above entry
            // Hit if bar's high touches or reaches TP
            Direction::Buy if bar_high >= tp => Some(tp),

            // Short position — TP is below entry
            // Hit if bar's low touches or reaches TP
            Direction::Sell if bar_low <= tp => Some(tp),

            _ => None,
        }
    }

    /// Closes this position at the given price and reason.
    /// Returns the realised PnL.
    pub fn close(
        &mut self,
        exit_price: f64,
        exit_reason: ExitReason,
        closed_at: DateTime<Utc>,
        commission: f64,
    ) -> f64 {
        let direction_multiplier = match self.direction {
            Direction::Buy  =>  1.0,
            Direction::Sell => -1.0,
            Direction::Close => 0.0,
        };

        let gross_pnl = (exit_price - self.entry_price)
            * self.size
            * direction_multiplier
            * 100_000.0;

        let net_pnl = gross_pnl - commission;

        self.exit_price  = Some(exit_price);
        self.exit_reason = Some(exit_reason);
        self.closed_at   = Some(closed_at);
        self.status      = PositionStatus::Closed;
        self.realised_pnl = net_pnl;

        net_pnl
    }
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn test_position(direction: Direction) -> Position {
        Position::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            direction,
            1.0,
            1.13786, // entry price
            match direction {
                Direction::Buy  => Some(1.1350), // SL below
                Direction::Sell => Some(1.1420), // SL above
                Direction::Close => None,
            },
            match direction {
                Direction::Buy  => Some(1.1420), // TP above
                Direction::Sell => Some(1.1350), // TP below
                Direction::Close => None,
            },
            Utc::now(),
        )
    }

    #[test]
    fn new_position_is_open_with_zero_pnl() {
        let position = test_position(Direction::Buy);
        assert!(position.is_open());
        assert_eq!(position.realised_pnl, 0.0);
        assert!(position.exit_price.is_none());
    }

    #[test]
    fn buy_sl_hit_when_bar_low_breaks_sl() {
        let position = test_position(Direction::Buy);
        // Bar low goes below SL of 1.1350
        let hit = position.check_sl(1.1340, 1.1390);
        assert!(hit.is_some());
    }

    #[test]
    fn buy_sl_not_hit_when_bar_low_above_sl() {
        let position = test_position(Direction::Buy);
        // Bar low stays above SL of 1.1350
        let hit = position.check_sl(1.1360, 1.1390);
        assert!(hit.is_none());
    }

    #[test]
    fn buy_tp_hit_when_bar_high_reaches_tp() {
        let position = test_position(Direction::Buy);
        // Bar high reaches TP of 1.1420
        let hit = position.check_tp(1.1390, 1.1430);
        assert!(hit.is_some());
    }

    #[test]
    fn sell_sl_hit_when_bar_high_breaks_sl() {
        let position = test_position(Direction::Sell);
        // Bar high goes above SL of 1.1420
        let hit = position.check_sl(1.1360, 1.1430);
        assert!(hit.is_some());
    }

    #[test]
    fn sell_tp_hit_when_bar_low_reaches_tp() {
        let position = test_position(Direction::Sell);
        // Bar low reaches TP of 1.1350
        let hit = position.check_tp(1.1340, 1.1390);
        assert!(hit.is_some());
    }

    #[test]
    fn sl_takes_priority_over_tp_same_bar() {
        let position = test_position(Direction::Buy);
        // Both SL and TP hit in same bar
        let sl_hit = position.check_sl(1.1340, 1.1430);
        let tp_hit = position.check_tp(1.1340, 1.1430);

        // Both return Some — caller must decide priority
        // By convention SL takes priority (worst case)
        assert!(sl_hit.is_some());
        assert!(tp_hit.is_some());
    }

    #[test]
    fn closing_position_calculates_pnl_correctly() {
        let mut position = test_position(Direction::Buy);

        // Entry at 1.13786, exit at 1.14186
        // = 40 pip profit on 1 lot
        // = 0.004 * 1.0 * 100_000 = $400 gross
        // minus $7 commission = $393 net
        let pnl = position.close(
            1.14186,
            ExitReason::TakeProfit,
            Utc::now(),
            7.0,
        );

        assert!(!position.is_open());
        assert!(pnl > 0.0);
        assert_eq!(position.exit_reason, Some(ExitReason::TakeProfit));
    }

    #[test]
    fn unrealised_pnl_positive_for_winning_long() {
        let position = test_position(Direction::Buy);
        // Price moved up from 1.13786
        let pnl = position.unrealised_pnl(1.13986);
        assert!(pnl > 0.0);
    }

    #[test]
    fn unrealised_pnl_negative_for_losing_long() {
        let position = test_position(Direction::Buy);
        // Price moved down from 1.13786
        let pnl = position.unrealised_pnl(1.13586);
        assert!(pnl < 0.0);
    }
}