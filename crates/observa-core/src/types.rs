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

// ────────────────────────────────────────────────
// RejectionReason
// ────────────────────────────────────────────────

/// Why an order was rejected by the execution model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum RejectionReason {
    /// Stop loss is too close to entry price
    InvalidStop {
        entry_price: f64,
        sl_price: f64,
        min_distance: f64,
    },
    /// Take profit is too close to entry price
    InvalidTakeProfit {
        entry_price: f64,
        tp_price: f64,
        min_distance: f64,
    },
    /// Lot size is outside allowed range
    InvalidSize {
        requested: f64,
        min_size: f64,
        max_size: f64,
    },
    /// Account balance too low to open position
    InsufficientCapital {
        required: f64,
        available: f64,
    },
    /// Requested price is unreachable from current market
    PriceOutOfRange {
        requested: f64,
        current: f64,
    },
}

impl std::fmt::Display for RejectionReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RejectionReason::InvalidStop { entry_price, sl_price, min_distance } => {
                write!(f,
                    "Stop loss ({sl_price}) is too close to entry ({entry_price}). \
                     Minimum distance: {min_distance}"
                )
            }
            RejectionReason::InvalidTakeProfit { entry_price, tp_price, min_distance } => {
                write!(f,
                    "Take profit ({tp_price}) is too close to entry ({entry_price}). \
                     Minimum distance: {min_distance}"
                )
            }
            RejectionReason::InvalidSize { requested, min_size, max_size } => {
                write!(f,
                    "Lot size ({requested}) is outside allowed range \
                     [{min_size}, {max_size}]"
                )
            }
            RejectionReason::InsufficientCapital { required, available } => {
                write!(f,
                    "Insufficient capital. Required: {required}, \
                     Available: {available}"
                )
            }
            RejectionReason::PriceOutOfRange { requested, current } => {
                write!(f,
                    "Requested price ({requested}) is too far from \
                     current market price ({current})"
                )
            }
        }
    }
}

// ────────────────────────────────────────────────
// CancellationReason
// ────────────────────────────────────────────────

/// Why an active order was cancelled.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum CancellationReason {
    /// Balance dropped below required margin
    InsufficientFunds,
    /// Strategy explicitly cancelled the order
    CancelledByStrategy,
    /// Order reached its expiry time unfilled
    Expired,
}

impl std::fmt::Display for CancellationReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CancellationReason::InsufficientFunds    => write!(f, "Insufficient Funds"),
            CancellationReason::CancelledByStrategy  => write!(f, "Cancelled by Strategy"),
            CancellationReason::Expired              => write!(f, "Expired"),
        }
    }
}

// ────────────────────────────────────────────────
// UpdateType
// ────────────────────────────────────────────────

/// What kind of update was applied to a position.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum UpdateType {
    /// Stop loss was adjusted
    SlAdjusted,
    /// Take profit was adjusted
    TpAdjusted,
    /// Part of the position was closed
    PartialClose,
}

impl std::fmt::Display for UpdateType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            UpdateType::SlAdjusted   => write!(f, "SL Adjusted"),
            UpdateType::TpAdjusted   => write!(f, "TP Adjusted"),
            UpdateType::PartialClose => write!(f, "Partial Close"),
        }
    }
}

// ────────────────────────────────────────────────
// ErrorType
// ────────────────────────────────────────────────

/// Why a run was interrupted by an error.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ErrorType {
    /// User strategy code threw an exception
    StrategyException,
    /// Dataset contained invalid or malformed data
    DataCorruption,
    /// Internal engine error
    EngineFault,
    /// Strategy exceeded time or memory limits
    ResourceLimitExceeded,
}

impl std::fmt::Display for ErrorType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorType::StrategyException     => write!(f, "Strategy Exception"),
            ErrorType::DataCorruption        => write!(f, "Data Corruption"),
            ErrorType::EngineFault           => write!(f, "Engine Fault"),
            ErrorType::ResourceLimitExceeded => write!(f, "Resource Limit Exceeded"),
        }
    }
}

// ────────────────────────────────────────────────
// AnnotationSource
// ────────────────────────────────────────────────

/// Where a journal annotation came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnnotationSource {
    /// Annotation was added by strategy code
    Strategy,
    /// Annotation was added through the UI
    Ui,
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn direction_multiplier_is_correct() {
        assert_eq!(Direction::Buy.multiplier(),   1.0);
        assert_eq!(Direction::Sell.multiplier(), -1.0);
    }

    #[test]
    fn direction_displays_correctly() {
        assert_eq!(Direction::Buy.to_string(),  "Buy");
        assert_eq!(Direction::Sell.to_string(), "Sell");
    }

    #[test]
    fn exit_reason_displays_correctly() {
        assert_eq!(ExitReason::TakeProfit.to_string(), "Take Profit");
        assert_eq!(ExitReason::StopLoss.to_string(),   "Stop Loss");
        assert_eq!(ExitReason::Signal.to_string(),     "Signal");
    }

    #[test]
    fn rejection_reason_carries_context() {
        let reason = RejectionReason::InsufficientCapital {
            required:  1000.0,
            available: 500.0,
        };
        let message = reason.to_string();
        assert!(message.contains("1000"));
        assert!(message.contains("500"));
    }
}