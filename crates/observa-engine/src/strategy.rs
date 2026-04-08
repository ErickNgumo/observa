use observa_core::bar::Bar;
use observa_core::types::Direction;

// ────────────────────────────────────────────────
// StrategySignal
// ────────────────────────────────────────────────

/// A signal emitted by a strategy indicating
/// it wants to enter or exit a trade.
///
/// This is not an order — it is intent.
/// The engine converts this into an OrderIntent.
#[derive(Debug, Clone)]
pub struct StrategySignal {
    /// Buy or Sell
    pub direction: Direction,

    /// Requested lot size
    pub size: f64,

    /// Price the strategy wants to fill at
    pub intended_price: f64,

    /// Stop loss price — optional
    pub sl: Option<f64>,

    /// Take profit price — optional
    pub tp: Option<f64>,

    /// Why the strategy signalled
    /// Appears on chart tooltip
    pub reason: String,
}

// ────────────────────────────────────────────────
// PortfolioView — read only snapshot for strategy
// ────────────────────────────────────────────────

/// A read-only snapshot of portfolio state
/// passed to the strategy on every bar.
///
/// The strategy can READ this but never mutate it.
#[derive(Debug, Clone)]
pub struct PortfolioView {
    /// Current account balance
    pub balance: f64,

    /// Current equity (balance + unrealised PnL)
    pub equity: f64,

    /// Whether there is currently an open position
    pub has_open_position: bool,

    /// Direction of open position if any
    pub position_direction: Option<Direction>,

    /// Entry price of open position if any
    pub position_entry_price: Option<f64>,

    /// Current unrealised PnL of open position
    pub unrealised_pnl: f64,
}

impl PortfolioView {
    /// Creates an empty portfolio view
    /// used at the start of a run
    pub fn empty(initial_balance: f64) -> Self {
        Self {
            balance: initial_balance,
            equity: initial_balance,
            has_open_position: false,
            position_direction: None,
            position_entry_price: None,
            unrealised_pnl: 0.0,
        }
    }
}

// ────────────────────────────────────────────────
// Strategy trait
// ────────────────────────────────────────────────

/// The interface every strategy must implement.
///
/// The engine calls these methods in strict order:
///   1. initialize() — once before replay starts
///   2. on_bar()     — once per closed bar
///   3. teardown()   — once after replay ends
///
/// The strategy never touches orders, fills, or
/// portfolio state directly. It only returns signals.
pub trait Strategy {
    /// Called once before the first bar.
    /// Use this to set up indicators and state.
    fn initialize(&mut self);

    /// Called on every closed bar in strict time order.
    /// Receives the current bar and a read-only
    /// portfolio snapshot.
    ///
    /// Returns zero or more signals. Returning an
    /// empty Vec means "do nothing this bar."
    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        bars_history: &[Bar],
    ) -> Vec<StrategySignal>;

    /// Called once after the last bar.
    /// Use this for cleanup or final logging.
    fn teardown(&mut self);
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use observa_core::types::Direction;

    /// A minimal test strategy that buys on
    /// every single bar — used to verify the
    /// trait interface works correctly
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
        fn initialize (&mut self) {
            self.initialized = true;            
        }

        fn on_bar(
            &mut self,
            bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            self.bars_seen += 1;
            vec! [StrategySignal {
                direction: Direction::Buy,
                size: 1.0,
                intended_price: bar.close,
                sl: Some(bar.close - 0.0020),
                tp: Some(bar.close + 0.0040),
                reason: "Always buy".to_string(),
            }]
        }

        fn teardown (&mut self) {
            self.torn_down = true;
        }
    }

    fn test_bar() -> Bar {
        Bar::new(
            Utc::now(),
            1.1376,
            1.13787,
            1.1376,
            1.13786,
            Some(278.19),
        )
    }

    fn test_portfolio() -> PortfolioView {
        PortfolioView::empty(10_000.0)
    }

    fn strategy_lifecycle_works_correctly () {
        let mut strategy = AlwaysBuyStrategy::new();

        //Before initialize
        assert!(!strategy.initialized);

        //Initialize
        strategy.initialize();
        assert!(strategy.initialized);

        //on_bar returns a signal
        let bar = test_bar();
        let portfolio = test_portfolio();
        let signals = strategy.on_bar(&bar, &portfolio, &[]);

        assert_eq!(signals.len(), 1);
        assert_eq!(signals[0].direction, Direction::Buy);
        assert_eq!(signals[0].intended_price, bar.close);
        assert_eq!(strategy.bars_seen, 1);

        // Teardown
        strategy.teardown();
        assert!(strategy.torn_down);
        
    }
    #[test]
    fn portfolio_view_empty_has_correct_defaults() {
        let portfolio = PortfolioView::empty(10_000.0);

        assert_eq!(portfolio.balance, 10_000.0);
        assert_eq!(portfolio.equity, 10_000.0);
        assert!(!portfolio.has_open_position);
        assert!(portfolio.position_direction.is_none());
        assert_eq!(portfolio.unrealised_pnl, 0.0);
    }

     #[test]
    fn strategy_receives_bar_history() {
        struct HistoryCheckStrategy {
            history_length_seen: usize,
        }

        impl Strategy for HistoryCheckStrategy {
            fn initialize(&mut self) {}

            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                history: &[Bar],
            ) -> Vec<StrategySignal> {
                self.history_length_seen = history.len();
                vec![]
            }

            fn teardown(&mut self) {}
        }

        let mut strategy = HistoryCheckStrategy {
            history_length_seen: 0,
        };

        let bar = test_bar();
        let portfolio = test_portfolio();

        // Simulate 3 bars of history
        let history = vec![test_bar(), test_bar(), test_bar()];
        strategy.on_bar(&bar, &portfolio, &history);

        assert_eq!(strategy.history_length_seen, 3);
    }

    #[test]
    fn strategy_can_return_no_signals() {
        struct DoNothingStrategy;

        impl Strategy for DoNothingStrategy {
            fn initialize(&mut self) {}

            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                _history: &[Bar],
            ) -> Vec<StrategySignal> {
                vec![] // no signals this bar
            }

            fn teardown(&mut self) {}
        }

        let mut strategy = DoNothingStrategy;
        let signals = strategy.on_bar(
            &test_bar(),
            &PortfolioView::empty(10_000.0),
            &[],
        );

        assert!(signals.is_empty());
    }
}