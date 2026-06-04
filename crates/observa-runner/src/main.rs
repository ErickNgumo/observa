use std::cell::RefCell;
use std::rc::Rc;

use observa_core::bar::Bar;
use observa_core::events::Event;
use observa_core::types::{Direction, ExitReason};
use observa_data::csv_reader::CsvReader;
use observa_engine::engine::{Engine, EngineConfig};
use observa_engine::event_bus::EventBus;
use observa_engine::strategy::{
    PortfolioView, Strategy, StrategySignal,
};
use observa_execution::execution::{
    ExecutionConfig, ExecutionModel, FillResult,
};
use observa_portfolio::portfolio::PortfolioManager;
use uuid::Uuid;

// ────────────────────────────────────────────────
// A simple EMA crossover strategy for testing
// ────────────────────────────────────────────────

struct EmaCrossover {
    fast_period: usize,
    slow_period: usize,
    fast_ema:    Option<f64>,
    slow_ema:    Option<f64>,
    prev_fast:   Option<f64>,
    prev_slow:   Option<f64>,
}

impl EmaCrossover {
    fn new(fast_period: usize, slow_period: usize) -> Self {
        Self {
            fast_period,
            slow_period,
            fast_ema:  None,
            slow_ema:  None,
            prev_fast: None,
            prev_slow: None,
        }
    }

    /// Calculates EMA incrementally.
    /// First value uses the price itself as seed.
    fn update_ema(
        current_ema: Option<f64>,
        price: f64,
        period: usize,
    ) -> f64 {
        match current_ema {
            None => price, // seed with first price
            Some(ema) => {
                let k = 2.0 / (period as f64 + 1.0);
                price * k + ema * (1.0 - k)
            }
        }
    }
}

impl Strategy for EmaCrossover {
    fn initialize(&mut self) {
        println!("EMA Crossover strategy initialized");
        println!(
            "Fast EMA: {} | Slow EMA: {}",
            self.fast_period,
            self.slow_period
        );
    }

    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        history: &[Bar],
    ) -> Vec<StrategySignal> {
        // Need enough history for slow EMA to warm up
        if history.len() < self.slow_period {
            // Update EMAs silently during warmup
            self.prev_fast = self.fast_ema;
            self.prev_slow = self.slow_ema;
            self.fast_ema = Some(Self::update_ema(
                self.fast_ema,
                bar.close,
                self.fast_period,
            ));
            self.slow_ema = Some(Self::update_ema(
                self.slow_ema,
                bar.close,
                self.slow_period,
            ));
            return vec![];
        }

        let prev_fast = match self.prev_fast {
            Some(v) => v,
            None    => return vec![],
        };
        let prev_slow = match self.prev_slow {
            Some(v) => v,
            None    => return vec![],
        };

        // Update EMAs
        self.prev_fast = self.fast_ema;
        self.prev_slow = self.slow_ema;
        self.fast_ema = Some(Self::update_ema(
            self.fast_ema,
            bar.close,
            self.fast_period,
        ));
        self.slow_ema = Some(Self::update_ema(
            self.slow_ema,
            bar.close,
            self.slow_period,
        ));

        let fast = self.fast_ema.unwrap();
        let slow = self.slow_ema.unwrap();

        // Detect crossover
        let crossed_up   = prev_fast <= prev_slow && fast > slow;
        let crossed_down = prev_fast >= prev_slow && fast < slow;

        // Entry — buy on bullish crossover
        if crossed_up && !portfolio.has_open_position {
            println!(
                "[{}] BUY signal — EMA{} crossed above EMA{}",
                bar.timestamp,
                self.fast_period,
                self.slow_period,
            );
            return vec![StrategySignal {
                direction:      Direction::Buy,
                size:           1.0,
                intended_price: bar.close,
                sl:             Some(bar.close - 0.0030),
                tp:             Some(bar.close + 0.0060),
                reason:         format!(
                    "EMA{} crossed above EMA{}",
                    self.fast_period,
                    self.slow_period,
                ),
            }];
        }

        // Exit — close on bearish crossover
        if crossed_down && portfolio.has_open_position {
            println!(
                "[{}] CLOSE signal — EMA{} crossed below EMA{}",
                bar.timestamp,
                self.fast_period,
                self.slow_period,
            );
            return vec![StrategySignal {
                direction:      Direction::Close,
                size:           1.0,
                intended_price: bar.close,
                sl:             None,
                tp:             None,
                reason:         format!(
                    "EMA{} crossed below EMA{}",
                    self.fast_period,
                    self.slow_period,
                ),
            }];
        }

        vec![]
    }

    fn teardown(&mut self) {
        println!("Strategy teardown complete");
    }
}

// ────────────────────────────────────────────────
// Main — wires everything together
// ────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════╗");
    println!("║         OBSERVA ENGINE v0.1          ║");
    println!("╚══════════════════════════════════════╝");
    println!();

    // ── Step 1: Load data ─────────────────────────
    println!("Loading EURUSD data...");
    let bars = CsvReader::load("data/EURUSD_M15.csv")
        .expect("Failed to load CSV");
    println!("Loaded {} bars", bars.len());
    println!();

    // ── Step 2: Set up shared state ───────────────

    // Current bar — shared between engine and subscribers
    let current_bar: Rc<RefCell<Option<Bar>>> =
        Rc::new(RefCell::new(None));

    // Pending order info — SL/TP needed by portfolio
    // when a fill arrives
    let pending_sl: Rc<RefCell<Option<f64>>> =
        Rc::new(RefCell::new(None));
    let pending_tp: Rc<RefCell<Option<f64>>> =
        Rc::new(RefCell::new(None));

    // Portfolio manager — shared across subscribers
    let run_id = Uuid::new_v4();
    let portfolio = Rc::new(RefCell::new(
        PortfolioManager::new(run_id, 10_000.0, 7.0)
    ));

    // Execution model
    let execution = ExecutionModel::new(
        ExecutionConfig::default_eurusd()
    );

    // ── Step 3: Build event bus with subscribers ──
    let mut event_bus = EventBus::new();

    // Clone Rc handles for each subscriber
    let bar_for_execution  = current_bar.clone();
    let bar_for_portfolio  = current_bar.clone();
    let bar_for_engine     = current_bar.clone();
    let portfolio_for_fill = portfolio.clone();
    let portfolio_for_bar  = portfolio.clone();
    let sl_for_intent      = pending_sl.clone();
    let tp_for_intent      = pending_tp.clone();
    let sl_for_fill        = pending_sl.clone();
    let tp_for_fill        = pending_tp.clone();

    // Subscriber 1 — track current bar
    event_bus.subscribe("bar_tracker", move |event| {
        if let Event::BarReceived(e) = event {
            *bar_for_engine.borrow_mut() = Some(e.bar.clone());
        }
    });

    // Subscriber 2 — execution model
    // Receives OrderIntentCreated, produces fills
    event_bus.subscribe("execution_model", move |event| {
        if let Event::OrderIntentCreated(intent) = event {
            // Store SL/TP for portfolio manager
            *sl_for_intent.borrow_mut() = intent.sl;
            *tp_for_intent.borrow_mut() = intent.tp;

            let bar_ref = bar_for_execution.borrow();
            if let Some(bar) = bar_ref.as_ref() {
                let balance = 10_000.0; // simplified
                match execution.process(intent, bar, balance) {
                    Ok(FillResult::Filled(fill)) => {
                        println!(
                            "  ✓ Fill: {} {:.5} (slippage: {:.5})",
                            fill.direction,
                            fill.executed_price,
                            fill.slippage,
                        );
                    }
                    Ok(FillResult::Rejected(rejection)) => {
                        println!(
                            "  ✗ Rejected: {}",
                            rejection.rejection_detail,
                        );
                    }
                    Err(e) => {
                        println!("  ! Execution error: {}", e);
                    }
                }
            }
        }
    });

    // Subscriber 3 — portfolio manager
    // Receives fills, manages positions
    event_bus.subscribe("portfolio_manager", move |event| {
        if let Event::OrderFilled(fill) = event {
            let sl = *sl_for_fill.borrow();
            let tp = *tp_for_fill.borrow();
            let mut pm = portfolio_for_fill.borrow_mut();

            match pm.process_fill(fill, sl, tp) {
                Ok(events) => {
                    if events.position_opened.is_some() {
                        println!(
                            "  → Position opened | Balance: {:.2}",
                            pm.balance(),
                        );
                    }
                    if let Some(closed) = events.position_closed {
                        println!(
                            "  → Position closed | PnL: {:.2} | \
                             Reason: {}",
                            closed.pnl,
                            closed.exit_reason,
                        );
                    }
                }
                Err(e) => println!("  ! Portfolio error: {}", e),
            }
        }
    });

    // Subscriber 4 — SL/TP checker
    // Checks open positions against each new bar
    event_bus.subscribe("sl_tp_checker", move |event| {
        if let Event::BarReceived(e) = event {
            let mut pm = portfolio_for_bar.borrow_mut();
            if let Some(events) = pm.check_sl_tp(&e.bar) {
                if let Some(closed) = events.position_closed {
                    println!(
                        "  → SL/TP hit | PnL: {:.2} | Reason: {}",
                        closed.pnl,
                        closed.exit_reason,
                    );
                }
            }
        }
    });

    // Subscriber 5 — run summary logger
    let portfolio_for_summary = portfolio.clone();
    event_bus.subscribe("run_logger", move |event| {
        match event {
            Event::RunStarted(e) => {
                println!("Run started: {}", e.metadata.run_id);
                println!("Dataset: {}", e.dataset_name);
                println!(
                    "Period: {} → {}",
                    e.data_start,
                    e.data_end,
                );
                println!();
            }
            Event::RunCompleted(e) => {
                let pm = portfolio_for_summary.borrow();
                println!();
                println!("╔══════════════════════════════════════╗");
                println!("║           RUN COMPLETE               ║");
                println!("╠══════════════════════════════════════╣");
                println!("║ Bars processed: {:>20} ║", e.total_bars);
                println!("║ Total trades:   {:>20} ║", pm.total_trades());
                println!("║ Final balance:  {:>20.2} ║", pm.balance());
                println!(
                    "║ Realised PnL:   {:>20.2} ║",
                    pm.realised_pnl(),
                );
                println!("╚══════════════════════════════════════╝");
            }
            _ => {}
        }
    });

    // ── Step 4: Run the engine ────────────────────
    let config = EngineConfig::new(
        10_000.0,
        0.0002,
        0.0001,
        7.0,
        "EMA Crossover (5/20)",
        "EURUSD_M15",
    );

    let mut engine = Engine::new(config, event_bus);
    let mut strategy = EmaCrossover::new(5, 20);

    engine.run(&mut strategy, bars)
        .expect("Engine run failed");
}