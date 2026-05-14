use chrono::{Datetime, Utc};
use uuid::Uuid;

use observa_core::types::{Direction, ExitReason};

// ────────────────────────────────────────────────
// PositionStatus
// ────────────────────────────────────────────────

/// Whether a position is currently open or closed
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
#[derive (Debug, Clone)]
pub struct Position {
    //Unique ID for this position
    pub position_id: Uuid,

    // Which fill opened this position
    pub order_id: Uuid,

    // Buy or Sell
    pub direction: Direction,

    //lot size
    pub size: f64,

    // Price at which positioned opened
    pub entry_price: f64,

    // Current stop loss
    pub sl: Option<f64>,

    //Current take profit
    pub tp: Option<f64>,

    // When positioned was opened
    pub opened_at: DateTime<Utc>,

    // When position was closed - None of stil open
    pub closed_at: Option<DateTime<Utc>>,

    // Exit price - None if still open
    pub exit_price: Option<f64>,

    //How position closed - None if still open
    pub exit_reason: Option<ExitReason>,

    // Current status
    pub status: PositionStatus,

    // Realised PnL - set when position closes
    pub status: PositionStatus,

    //Realised PnL - set when position closes
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
        tp:Option<f64>,
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

    // Calculate unrealised PnL at the given price
    pub fn unrealised_pnl(&self, current_price: f64) -> f64{
        if !self.is_open() {
            return self.realised_pnl;
        }
        let direction_multiplier = match self.direction{
            Direction::Buy => 1.0,
            Direction::Sell => -1.0,
            Direction::Close => 0.0,
        };
        (current_price - self.entry_price)
            *self.size
            *direction_multiplier
            *100_000 //Standard lot size
    }

    /// Checks if stop loss was hit by this bar.
    /// Returns the exit price if hit, None otherwise
    pub fn check_sl(&self, bar_low: f64, bar_high: f64)
        -> Option<f64>
        {
            let sl = self.sl?; // return None if no SL set

            match self.direction {
                // Long position - SL is below entry
                // Hit if bar's low touches or breaks SL
                Direction::Buy if bar_low <= sl => Some(sl),

                // Short Position - SL is above entry
                //Hit if bar's high touches or breaks sl
                Direction::Sell if bar_high >= sl => Some(sl),

                _=> None,
            }
        }

        /// Checks of the take profit was hit by this bar.
        /// Returns the exit price if hit, None otherwise.
        pub fn check_tp(&self, bar_low: f64, bar_high: f64)
            -> Option<f64>
        {
            let tp = self.tp?; //Return None if no TP set

            match self.direction {
                // Long position - TP is above entry
                // Hit if bar's high touches or reaches TP
                Direction::Buy if bar_high >= tp => Some(tp),

                // Short position - TP is below entry
                // Hit if bar's low touches or reaches TP
                Direction::Sell if bar_low <= tp => Some(tp),

                _ => None,
            }
        }

        /// Closes this position at the given price and reason.
        /// Returns the realised PnL.
        pub fn close(
            &mt self,
            exit_price: f64,
            exit_reason: ExitReason,
            closed_at: DateTime<Utc>,
            commmission: f64,
        ) -> f64 {
            let direction_multiplier = match self.direction {
                Direction::Buy => 1.0,
                Direction::Sell => -1.0,
                Direction::Close => 0.0,
            };

            let gross_pnl = (exit_price - self.entry-price)
                * self.size
                * direction_multiplier
                * 100_000;
            
            let net_pnl = gross_pnl - commission;

            self.exit_price = Some(exit-price);
            self.exit_reason = Some(exit_reason);
            self.closed_at = Some(closed_at);
            self.status = PositionStatus::Closed;
            self.realised_pnl = net_pnl;

            net pnl
        }
}