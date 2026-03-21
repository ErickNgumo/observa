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