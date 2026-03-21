use serde::{Deserialize, Serialize};

// ────────────────────────────────────────────────
// Direction
// ────────────────────────────────────────────────

/// The direction of a trade or order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Buy,
    Sell,
}

impl Direction {
    /// Returns the multiplier for PnL calculation.
    /// Buy positions profit when price goes up (+1.0)
    /// Sell positions profit when price goes down (-1.0)
    pub fn multiplier(&self) -> f64 {
        match self {
            Direction::Buy  =>  1.0,
            Direction::Sell => -1.0,
        }
    }
}

impl std::fmt::Display for Direction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Direction::Buy  => write!(f, "Buy"),
            Direction::Sell => write!(f, "Sell"),
        }
    }
}
// ────────────────────────────────────────────────
// ExitReason
// ────────────────────────────────────────────────

/// Why a position was closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExitReason {
    /// Take profit level was hit
    TakeProfit,
    /// Stop loss level was hit
    StopLoss,
    /// Strategy explicitly called self.close()
    Signal,
}

impl std::fmt::Display for ExitReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ExitReason::TakeProfit => write!(f, "Take Profit"),
            ExitReason::StopLoss  => write!(f, "Stop Loss"),
            ExitReason::Signal    => write!(f, "Signal"),
        }
    }
}