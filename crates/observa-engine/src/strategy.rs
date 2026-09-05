use std::collections::BTreeMap;

use serde_json::Value;

use observa_core::bar::Bar;
use observa_core::drawings::DrawingInstruction;
use observa_core::types::{Direction, OrderKind};

/// A single open position visible to the strategy.
/// Read-only — the strategy can see it but not modify it.
#[derive(Debug, Clone)]
pub struct OpenPositionView {
    /// Unique ticket ID — use this to close the position.
    pub ticket: String,
    /// Instrument symbol (single-instrument MVP).
    pub symbol: String,
    /// Buy or Sell.
    pub direction: Direction,
    /// Position quantity in lots.
    pub size: f64,
    /// Price at which the position was opened.
    pub entry_price: f64,
    /// Current unrealised PnL at the current valuation price.
    pub unrealised_pnl: f64,
    /// Current stop loss.
    pub sl: Option<f64>,
    /// Current take profit.
    pub tp: Option<f64>,
}

// ────────────────────────────────────────────────
// StrategySignal
// ────────────────────────────────────────────────

/// A signal emitted by a strategy expressing intent.
///
/// This is not an order — it is intent. The Engine (OBS-0007) converts each
/// signal into a canonical runtime order and schedules/executes it.
#[derive(Debug, Clone)]
pub struct StrategySignal {
    /// `Buy`/`Sell` open a new position; `Close` closes the position named by
    /// `ticket`.
    pub direction: Direction,

    /// Generic order type requested (defaults to MARKET). LIMIT/STOP orders
    /// use `intended_price` as their limit/stop trigger price.
    pub order_type: OrderKind,

    /// Requested quantity in lots.
    pub size: f64,

    /// For LIMIT/STOP orders this is the trigger/limit price; for MARKET
    /// orders it is informational (market reference prices come from the bar
    /// per the fill mode).
    pub intended_price: f64,

    /// Stop loss price — optional (attached to an entry position).
    pub sl: Option<f64>,

    /// Take profit price — optional (attached to an entry position).
    pub tp: Option<f64>,

    /// Why the strategy signalled (shown on chart tooltips).
    pub reason: String,

    /// Position ticket — required for `Close`.
    pub ticket: Option<String>,
}

impl StrategySignal {
    /// A MARKET order signal.
    pub fn market(
        direction: Direction,
        size: f64,
        sl: Option<f64>,
        tp: Option<f64>,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            direction,
            order_type: OrderKind::Market,
            size,
            intended_price: 0.0,
            sl,
            tp,
            reason: reason.into(),
            ticket: None,
        }
    }
}

// ────────────────────────────────────────────────
// PortfolioView — read only snapshot for strategy
// ────────────────────────────────────────────────

/// A read-only snapshot of portfolio state passed to the strategy on every
/// bar. The strategy can READ it but never mutate it.
#[derive(Debug, Clone)]
pub struct PortfolioView {
    /// Current account balance (realised only).
    pub balance: f64,
    /// Current equity (balance + unrealised PnL of ALL open positions).
    pub equity: f64,
    /// Whether any position is currently open.
    pub has_open_position: bool,
    /// All currently open positions.
    pub open_positions: Vec<OpenPositionView>,
    /// Current unrealised PnL across all open positions.
    pub unrealised_pnl: f64,
    /// Margin in use by open positions at the valuation price.
    pub used_margin: f64,
    /// `equity − used_margin`.
    pub free_margin: f64,
}

impl PortfolioView {
    /// An empty portfolio view, used at the start of a run.
    pub fn empty(initial_balance: f64) -> Self {
        Self {
            balance: initial_balance,
            equity: initial_balance,
            has_open_position: false,
            open_positions: Vec::new(),
            unrealised_pnl: 0.0,
            used_margin: 0.0,
            free_margin: initial_balance,
        }
    }
}

// ────────────────────────────────────────────────
// Strategy trait
// ────────────────────────────────────────────────

/// The interface every strategy must implement.
///
/// The Engine (OBS-0007) drives the strategy lifecycle in strict order:
///   1. `initialize_with_params` — once before replay starts (with the
///      resolved strategy parameters when available);
///   2. `on_bar` — once per closed bar;
///   3. `teardown` — once after replay ends.
///
/// The strategy never touches orders, fills, or portfolio state directly. It
/// returns signals (and optionally drawings) which the Engine converts into
/// canonical runtime orders.
pub trait Strategy {
    /// Called once before the first bar. Default: no-op.
    fn initialize(&mut self) {}

    /// Engine-owned parameterized initialization hook.
    ///
    /// Default implementation forwards to [`Strategy::initialize`]. Bridges
    /// that can deliver parameters (e.g. a future Python packaging layer)
    /// should override this method. The Engine always passes the resolved
    /// strategy parameters through this method; never call `initialize`
    /// directly from orchestration.
    fn initialize_with_params(&mut self, _params: Option<&BTreeMap<String, Value>>) {
        self.initialize();
    }

    /// Called on every closed bar in strict time order.
    ///
    /// Receives the current bar, a read-only portfolio snapshot (all open
    /// positions) and the strictly-prior bar history. Returns zero or more
    /// signals; an empty `Vec` means "do nothing this bar".
    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        bars_history: &[Bar],
    ) -> Vec<StrategySignal>;

    /// Drawings produced during the last `on_bar` call, drained by the Engine
    /// after each strategy invocation. Default: no drawings.
    fn take_drawings(&mut self) -> Vec<DrawingInstruction> {
        Vec::new()
    }

    /// A structured strategy error recorded by the bridge, drained by the
    /// Engine after each strategy call. `Some` means the last callback failed
    /// and the Engine must treat the run as failed rather than silently
    /// continuing with an empty decision. Default: no error.
    fn take_strategy_error(&mut self) -> Option<String> {
        None
    }

    /// Called once after the last bar. Use for cleanup or final logging.
    fn teardown(&mut self) {}
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use observa_core::types::Direction;

    /// A minimal test strategy that buys on every single bar.
    struct AlwaysBuyStrategy {
        initialized: bool,
        torn_down: bool,
        bars_seen: u32,
    }

    impl AlwaysBuyStrategy {
        fn new() -> Self {
            Self {
                initialized: false,
                torn_down: false,
                bars_seen: 0,
            }
        }
    }

    impl Strategy for AlwaysBuyStrategy {
        fn initialize(&mut self) {
            self.initialized = true;
        }

        fn on_bar(
            &mut self,
            bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            self.bars_seen += 1;
            vec![StrategySignal {
                direction: Direction::Buy,
                order_type: OrderKind::Market,
                size: 1.0,
                intended_price: bar.close,
                sl: Some(bar.close - 0.0020),
                tp: Some(bar.close + 0.0040),
                reason: "Always buy".to_string(),
                ticket: None,
            }]
        }

        fn teardown(&mut self) {
            self.torn_down = true;
        }
    }

    fn test_bar() -> Bar {
        Bar::new(Utc::now(), 1.1376, 1.13787, 1.1376, 1.13786, Some(278.19))
    }

    #[test]
    fn strategy_lifecycle_works_correctly() {
        let mut strategy = AlwaysBuyStrategy::new();

        assert!(!strategy.initialized);
        strategy.initialize_with_params(None);
        assert!(strategy.initialized);

        let bar = test_bar();
        let portfolio = PortfolioView::empty(10_000.0);
        let signals = strategy.on_bar(&bar, &portfolio, &[]);
        assert_eq!(signals.len(), 1);
        assert_eq!(signals[0].direction, Direction::Buy);
        assert_eq!(signals[0].order_type, OrderKind::Market);
        assert_eq!(strategy.bars_seen, 1);

        strategy.teardown();
        assert!(strategy.torn_down);
    }

    #[test]
    fn default_initialize_with_params_delegates_to_initialize() {
        struct Noop;
        impl Strategy for Noop {
            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                _history: &[Bar],
            ) -> Vec<StrategySignal> {
                vec![]
            }
        }
        let mut s = Noop;
        // Default hooks exist and are safe.
        assert!(s.take_drawings().is_empty());
        assert!(s.take_strategy_error().is_none());
        s.initialize_with_params(Some(&BTreeMap::new()));
        s.teardown();
    }

    #[test]
    fn portfolio_view_empty_has_correct_defaults() {
        let portfolio = PortfolioView::empty(10_000.0);
        assert_eq!(portfolio.balance, 10_000.0);
        assert_eq!(portfolio.equity, 10_000.0);
        assert!(!portfolio.has_open_position);
        assert!(portfolio.open_positions.is_empty());
        assert_eq!(portfolio.unrealised_pnl, 0.0);
    }

    #[test]
    fn strategy_receives_bar_history() {
        struct HistoryCheckStrategy {
            history_length_seen: usize,
        }

        impl Strategy for HistoryCheckStrategy {
            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                history: &[Bar],
            ) -> Vec<StrategySignal> {
                self.history_length_seen = history.len();
                vec![]
            }
        }

        let mut strategy = HistoryCheckStrategy {
            history_length_seen: 0,
        };

        let bar = test_bar();
        let portfolio = PortfolioView::empty(10_000.0);
        let history = vec![test_bar(), test_bar(), test_bar()];
        strategy.on_bar(&bar, &portfolio, &history);
        assert_eq!(strategy.history_length_seen, 3);
    }

    #[test]
    fn strategy_can_return_no_signals() {
        struct DoNothingStrategy;

        impl Strategy for DoNothingStrategy {
            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                _history: &[Bar],
            ) -> Vec<StrategySignal> {
                vec![]
            }
        }

        let mut strategy = DoNothingStrategy;
        let signals = strategy.on_bar(&test_bar(), &PortfolioView::empty(10_000.0), &[]);
        assert!(signals.is_empty());
    }
}
