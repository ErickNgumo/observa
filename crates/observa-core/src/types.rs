use serde::{Deserialize, Serialize};

// ────────────────────────────────────────────────
// Direction
// ────────────────────────────────────────────────

/// The direction of a trade or order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Buy,
    Sell,
    Close,
}

impl Direction {
    /// Returns the multiplier for PnL calculation.
    /// Buy positions profit when price goes up (+1.0)
    /// Sell positions profit when price goes down (-1.0)
    pub fn multiplier(&self) -> f64 {
        match self {
            Direction::Buy  =>  1.0,
            Direction::Sell => -1.0,
            Direction::Close => 0.0,
        }
    }
}

impl std::fmt::Display for Direction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Direction::Buy  => write!(f, "Buy"),
            Direction::Sell => write!(f, "Sell"),
            Direction::Close => write!(f, "Close"),
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

// ────────────────────────────────────────────────
// Order domain — canonical MVP representation
// ────────────────────────────────────────────────
//
// Order KIND and order STATE are deliberately separate concepts:
//   * `OrderKind` is the type of order a strategy (or protective rule) emits:
//     MARKET, LIMIT or STOP. A LIMIT order is a *kind*, not a "pending" state.
//   * `OrderState` is the position of an order within its lifecycle.
// These types are the domain representation that the order/execution model
// (OBS-0006) consumes. They carry no execution logic.
//
// Protective SL/TP are conceptually distinct from generic strategy order
// kinds: a protective stop-loss behaves like a market-style exit and a
// protective take-profit behaves like a limit-style exit, but both are tied
// to an already-open position rather than being freely placed orders.

/// The MVP order kinds a strategy (or a protective rule) may produce.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OrderKind {
    /// Executes at the next permitted market price (per fill mode).
    Market,
    /// Price-constrained order: never fills worse than its limit price.
    Limit,
    /// Waits until the price trades through its stop level, then behaves
    /// as a market order.
    Stop,
}

impl std::fmt::Display for OrderKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            OrderKind::Market => "market",
            OrderKind::Limit => "limit",
            OrderKind::Stop => "stop",
        };
        write!(f, "{}", s)
    }
}

/// The lifecycle states an order can occupy.
///
/// Not every order passes through every state: a MARKET order normally goes
/// `Created → Filled` (or `Created → Rejected`), while resting LIMIT/STOP
/// orders go `Created → Pending → Triggered → Filled`. Dataset-end expiry is
/// the only expiry mechanism in the MVP; time-based order expiration is out
/// of scope.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OrderState {
    /// The order has been accepted by the engine and is being processed.
    Created,
    /// The order is resting and waiting for its trigger/market conditions.
    Pending,
    /// The order's trigger condition has been met (STOP orders, and LIMIT
    /// orders that became marketable); execution follows.
    Triggered,
    /// The order has executed and produced a fill.
    Filled,
    /// The order was refused by validation (quantity, price, margin,
    /// position reference, ...).
    Rejected,
    /// The order reached the end of the dataset without filling.
    Expired,
}

impl std::fmt::Display for OrderState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            OrderState::Created => "created",
            OrderState::Pending => "pending",
            OrderState::Triggered => "triggered",
            OrderState::Filled => "filled",
            OrderState::Rejected => "rejected",
            OrderState::Expired => "expired",
        };
        write!(f, "{}", s)
    }
}

/// The two protective order roles attachable to an open position.
///
/// These are conceptually separate from generic strategy `OrderKind`s: an SL
/// behaves as a market-style exit (receives slippage; fills at the bar open
/// when the market gaps through the level), while a TP behaves as a limit-style
/// exit (price constrained; no slippage). Their execution details belong to
/// the order/execution model (OBS-0006).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtectiveKind {
    /// Protective stop-loss attached to an open position.
    StopLoss,
    /// Protective take-profit attached to an open position.
    TakeProfit,
}

impl std::fmt::Display for ProtectiveKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            ProtectiveKind::StopLoss => "stop_loss",
            ProtectiveKind::TakeProfit => "take_profit",
        };
        write!(f, "{}", s)
    }
}

#[cfg(test)]
mod order_domain_tests {
    use super::*;

    #[test]
    fn order_kind_and_state_are_separate_concepts() {
        // A LIMIT order is a kind; Pending is a state it can be in.
        let kind = OrderKind::Limit;
        let state = OrderState::Pending;
        assert_eq!(kind.to_string(), "limit");
        assert_eq!(state.to_string(), "pending");
        // Kind and state must not be interchangeable.
        assert_ne!(format!("{kind:?}"), format!("{state:?}"));
    }

    #[test]
    fn order_kinds_cover_mvp_orders() {
        assert_eq!(format!("{:?}", OrderKind::Market), "Market");
        let all = [OrderKind::Market, OrderKind::Limit, OrderKind::Stop];
        assert_eq!(all.len(), 3);
    }

    #[test]
    fn order_states_cover_lifecycle() {
        assert_eq!(format!("{:?}", OrderState::Created), "Created");
        let all = [
            OrderState::Created,
            OrderState::Pending,
            OrderState::Triggered,
            OrderState::Filled,
            OrderState::Rejected,
            OrderState::Expired,
        ];
        assert_eq!(all.len(), 6);
    }

    #[test]
    fn protective_kinds_distinct_from_strategy_order_kinds() {
        // SL/TP are protective roles, not generic strategy orders.
        let sl = ProtectiveKind::StopLoss;
        let tp = ProtectiveKind::TakeProfit;
        assert_eq!(sl.to_string(), "stop_loss");
        assert_eq!(tp.to_string(), "take_profit");
        // The generic kinds do not include protective roles.
        assert!(!matches!(OrderKind::Market, OrderKind::Limit));
    }

    #[test]
    fn order_enums_serialize_lowercase() {
        let kind_json = serde_json::to_string(&OrderKind::Stop).unwrap();
        assert_eq!(kind_json, r#""stop""#);
        let state_json = serde_json::to_string(&OrderState::Triggered).unwrap();
        assert_eq!(state_json, r#""triggered""#);
        let prot_json = serde_json::to_string(&ProtectiveKind::TakeProfit).unwrap();
        assert_eq!(prot_json, r#""take_profit""#);
    }
}
