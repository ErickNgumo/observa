use std::cell::RefCell;
use std::rc::Rc;

use observa_core::bar::Bar;
use observa_core::events::{
    Event, EventMetadata, OrderFilledEvent,
    PositionClosedEvent, PositionOpenedEvent,
};
use observa_core::types::Direction;
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
// EMA Crossover Strategy
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

    fn update_ema(
        current_ema: Option<f64>,
        price: f64,
        period: usize,
    ) -> f64 {
        match current_ema {
            None      => price,
            Some(ema) => {
                let k = 2.0 / (period as f64 + 1.0);
                price * k + ema * (1.0 - k)
            }
        }
    }
}

impl Strategy for EmaCrossover {
    fn initialize(&mut self) {
        println!(
            "Strategy: EMA{}/EMA{} Crossover",
            self.fast_period,
            self.slow_period,
        );
    }

    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        history: &[Bar],
    ) -> Vec<StrategySignal> {
        // Warmup period
        if history.len() < self.slow_period {
            self.prev_fast = self.fast_ema;
            self.prev_slow = self.slow_ema;
            self.fast_ema = Some(Self::update_ema(
                self.fast_ema, bar.close, self.fast_period,
            ));
            self.slow_ema = Some(Self::update_ema(
                self.slow_ema, bar.close, self.slow_period,
            ));
            return vec![];
        }

        let prev_fast = match self.prev_fast {
            Some(v) => v, None => return vec![],
        };
        let prev_slow = match self.prev_slow {
            Some(v) => v, None => return vec![],
        };

        self.prev_fast = self.fast_ema;
        self.prev_slow = self.slow_ema;
        self.fast_ema  = Some(Self::update_ema(
            self.fast_ema, bar.close, self.fast_period,
        ));
        self.slow_ema  = Some(Self::update_ema(
            self.slow_ema, bar.close, self.slow_period,
        ));

        let fast = self.fast_ema.unwrap();
        let slow = self.slow_ema.unwrap();

        let crossed_up   = prev_fast <= prev_slow && fast > slow;
        let crossed_down = prev_fast >= prev_slow && fast < slow;

        if crossed_up && !portfolio.has_open_position {
            return vec![StrategySignal {
                direction:      Direction::Buy,
                size:           1.0,
                intended_price: bar.close,
                sl:             Some(bar.close - 0.0030),
                tp:             Some(bar.close + 0.0060),
                reason:         format!(
                    "EMA{} crossed above EMA{}",
                    self.fast_period, self.slow_period,
                ),
            }];
        }

        if crossed_down && portfolio.has_open_position {
            return vec![StrategySignal {
                direction:      Direction::Close,
                size:           1.0,
                intended_price: bar.close,
                sl:             None,
                tp:             None,
                reason:         format!(
                    "EMA{} crossed below EMA{}",
                    self.fast_period, self.slow_period,
                ),
            }];
        }

        vec![]
    }

    fn teardown(&mut self) {
        println!("Strategy teardown complete.");
    }
}

// ────────────────────────────────────────────────
// Observa Runner
// Wires engine, execution, and portfolio together
// ────────────────────────────────────────────────

struct ObservaRunner {
    execution:  ExecutionModel,
    portfolio:  PortfolioManager,
    event_bus:  Rc<RefCell<EventBus>>,
    run_id:     Uuid,
}

impl ObservaRunner {
    fn new(
        initial_balance: f64,
        execution_config: ExecutionConfig,
        run_id: Uuid,
        event_bus: Rc<RefCell<EventBus>>,
    ) -> Self {
        Self {
            execution: ExecutionModel::new(execution_config),
            portfolio: PortfolioManager::new(
                run_id,
                initial_balance,
                7.0,
            ),
            event_bus,
            run_id,
        }
    }

    /// Processes an order intent through execution
    /// and portfolio in sequence.
    /// Publishes resulting events to the bus.
    fn process_intent(
        &mut self,
        intent_event: &observa_core::events::OrderIntentCreatedEvent,
        current_bar: &Bar,
    ) {
        let balance = self.portfolio.balance();

        match self.execution.process(
            intent_event,
            current_bar,
            balance,
        ) {
            Ok(FillResult::Filled(fill)) => {
                println!(
                    "  ✓ {} @ {:.5} (slip: {:+.5}, comm: {:.2})",
                    fill.direction,
                    fill.executed_price,
                    fill.slippage,
                    fill.commission,
                );

                // Publish fill event to bus
                let fill_event = Event::OrderFilled(fill.clone());
                self.event_bus
                    .borrow_mut()
                    .publish(&fill_event)
                    .ok();

                // Process through portfolio
                match self.portfolio.process_fill(&fill) {
                    Ok(events) => {
                        self.publish_position_events(events);
                    }
                    Err(e) => {
                        println!("  ! Portfolio error: {}", e);
                    }
                }
            }
            Ok(FillResult::Rejected(rejection)) => {
                println!(
                    "  ✗ Rejected: {}",
                    rejection.rejection_detail,
                );
                let event = Event::OrderRejected(rejection);
                self.event_bus
                    .borrow_mut()
                    .publish(&event)
                    .ok();
            }
            Err(e) => println!("  ! Execution error: {}", e),
        }
    }

    /// Checks SL/TP on open positions for the current bar
    fn check_sl_tp(&mut self, bar: &Bar) {
        if let Some(events) = self.portfolio.check_sl_tp(bar) {
            self.publish_position_events(events);
        }
    }

    /// Publishes position opened/closed events to bus
    fn publish_position_events(
        &mut self,
        events: observa_portfolio::portfolio::PortfolioEvents,
    ) {
        if let Some(opened) = events.position_opened {
            println!(
                "  → Opened {} @ {:.5} | SL: {:?} | TP: {:?}",
                opened.direction,
                opened.entry_price,
                opened.sl,
                opened.tp,
            );
            self.event_bus
                .borrow_mut()
                .publish(&Event::PositionOpened(opened))
                .ok();
        }

        if let Some(closed) = events.position_closed {
            println!(
                "  → Closed @ {:.5} | PnL: {:+.2} | \
                 Reason: {} | Balance: {:.2}",
                closed.exit_price,
                closed.pnl,
                closed.exit_reason,
                self.portfolio.balance(),
            );
            self.event_bus
                .borrow_mut()
                .publish(&Event::PositionClosed(closed))
                .ok();
        }

        // Always publish portfolio snapshot
        self.event_bus
            .borrow_mut()
            .publish(&Event::PortfolioSnapshot(events.snapshot))
            .ok();
    }

    /// Returns a PortfolioView for the strategy
    fn portfolio_view(&self) -> PortfolioView {
        let position = self.portfolio.open_position();
        PortfolioView {
            balance: self.portfolio.balance(),
            equity:  self.portfolio.balance(),
            has_open_position:     position.is_some(),
            position_direction:    position.map(|p| p.direction),
            position_entry_price:  position.map(|p| p.entry_price),
            unrealised_pnl:        0.0,
        }
    }
}

// ────────────────────────────────────────────────
// Custom Engine Loop
// We drive the loop manually so the runner can
// process intents synchronously after each bar
// ────────────────────────────────────────────────

fn run_backtest(
    bars: Vec<Bar>,
    strategy: &mut dyn Strategy,
    runner: &mut ObservaRunner,
) {
    strategy.initialize();

    let mut history: Vec<Bar> = Vec::new();

    for bar in &bars {
        // Check SL/TP on open positions first
        runner.check_sl_tp(bar);

        // Publish BarReceivedEvent
        let bar_event = Event::BarReceived(
            observa_core::events::BarReceivedEvent {
                metadata: EventMetadata::new(
                    runner.run_id,
                    bar.timestamp,
                ),
                bar: bar.clone(),
            },
        );
        runner.event_bus
            .borrow_mut()
            .publish(&bar_event)
            .ok();

        // Get portfolio view for strategy
        let portfolio_view = runner.portfolio_view();

        // Call strategy
        let signals = strategy.on_bar(
            bar,
            &portfolio_view,
            &history,
        );

        // Process each signal through execution + portfolio
        for signal in signals {
            // Build OrderIntentCreatedEvent
            let signal_id = Uuid::new_v4();
            let intent = observa_core::events::OrderIntentCreatedEvent {
                metadata:        EventMetadata::new(
                                     runner.run_id,
                                     bar.timestamp,
                                 ),
                order_id:        Uuid::new_v4(),
                signal_id,
                direction:       signal.direction,
                size:            signal.size,
                intended_price:  signal.intended_price,
                sl:              signal.sl,
                tp:              signal.tp,
                reason:          signal.reason.clone(),
            };

            // Publish intent event
            let intent_event = Event::OrderIntentCreated(
                intent.clone()
            );
            runner.event_bus
                .borrow_mut()
                .publish(&intent_event)
                .ok();

            // Process intent synchronously
            runner.process_intent(&intent, bar);
        }

        history.push(bar.clone());
    }

    strategy.teardown();
}

// ────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════╗");
    println!("║         OBSERVA ENGINE v0.1          ║");
    println!("╚══════════════════════════════════════╝");
    println!();

    // Load data
    println!("Loading EURUSD data...");
    let bars = CsvReader::load("data/EURUSD_M15.csv")
        .expect("Failed to load CSV");
    println!("Loaded {} bars\n", bars.len());

    // Build shared event bus
    let event_bus = Rc::new(RefCell::new(EventBus::new()));

    // Subscribe run logger
    let bus_for_logger = event_bus.clone();
    event_bus.borrow_mut().subscribe(
        "run_logger",
        move |event| {
            match event {
                Event::RunCompleted(e) => {
                    println!(
                        "\nRun completed — {} bars processed",
                        e.total_bars,
                    );
                }
                _ => {}
            }
        },
    );

    // Build runner
    let run_id = Uuid::new_v4();
    let mut runner = ObservaRunner::new(
        10_000.0,
        ExecutionConfig::default_eurusd(),
        run_id,
        event_bus.clone(),
    );

    // Run backtest
    let mut strategy = EmaCrossover::new(5, 20);
    run_backtest(bars, &mut strategy, &mut runner);

    // Print summary
    println!();
    println!("╔══════════════════════════════════════╗");
    println!("║           RUN COMPLETE               ║");
    println!("╠══════════════════════════════════════╣");
    println!(
        "║ Total trades:   {:>20} ║",
        runner.portfolio.total_trades(),
    );
    println!(
        "║ Final balance:  {:>20.2} ║",
        runner.portfolio.balance(),
    );
    println!(
        "║ Realised PnL:   {:>20.2} ║",
        runner.portfolio.realised_pnl(),
    );
    println!("╚══════════════════════════════════════╝");
}