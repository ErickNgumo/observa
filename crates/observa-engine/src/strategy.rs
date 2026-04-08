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