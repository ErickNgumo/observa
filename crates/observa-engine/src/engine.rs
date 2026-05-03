use chrono::Utc;
use uuid::Uuid;

use observa_core::bar::Bar;
use observa_core::events::{
    BarReceivedEvent, Event, EventMetadata,
    OrderIntentCreatedEvent, RunCompletedEvent,
    RunStartedEvent, SignalEmittedEvent,
};

use crate::error::EngineError;
use crate::event_bus::EventBus;
use crate::strategy::{PortfolioView, Strategy};

// ────────────────────────────────────────────────
// EngineConfig
// ────────────────────────────────────────────────

/// Configuration for a single run.
/// Frozen at the start — never changes during replay.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    /// Unique ID for this run
    pub run_id: Uuid,

    /// Starting capital
    pub initial_balance: f64,

    /// Fixed spread in price units e.g. 0.0002 for 2 pips
    pub spread: f64,

    /// Fixed slippage in price units
    pub slippage: f64,

    /// Commission per trade in account currency
    pub commission: f64,

    /// Name of the strategy being run
    pub strategy_name: String,

    /// Dataset name for reproducibility
    pub dataset_name: String,
}

impl EngineConfig {
    /// Creates a new config with a fresh run_id
    pub fn new(
        initial_balance: f64,
        spread: f64,
        slippage: f64,
        commission: f64,
        strategy_name: impl Into<String>,
        dataset_name: impl Into<String>,
    ) -> Self {
        Self {
            run_id: Uuid::new_v4(),
            initial_balance,
            spread,
            slippage,
            commission,
            strategy_name: strategy_name.into(),
            dataset_name: dataset_name.into(),
        }
    }
}

// ────────────────────────────────────────────────
// Engine
// ────────────────────────────────────────────────

/// The replay engine — the heartbeat of Observa.
///
/// Controls time, drives the bar loop, coordinates
/// all components through the event bus.
///
/// Usage:
///   let mut engine = Engine::new(config, event_bus);
///   engine.run(&mut strategy, bars)?;
pub struct Engine {
    config: EngineConfig,
    event_bus: EventBus,
}

impl Engine {
    /// Creates a new engine with the given config
    /// and event bus
    pub fn new(config: EngineConfig, event_bus: EventBus) -> Self {
        Self { config, event_bus }
    }

    /// Runs the complete backtest replay.
    ///
    /// Drives time forward bar by bar, calling the
    /// strategy and emitting events at each step.
    pub fn run(
        &mut self,
        strategy: &mut dyn Strategy,
        bars: Vec<Bar>,
    ) -> Result<(), EngineError> {
        if bars.is_empty() {
            return Err(EngineError::NoDataLoaded);
        }

        let run_id = self.config.run_id;
        let start_time = Utc::now();

        // ── Step 1: Emit RunStartedEvent ──────────
        let run_started = Event::RunStarted(RunStartedEvent {
            metadata: EventMetadata::new(run_id, start_time),
            strategy_name: self.config.strategy_name.clone(),
            strategy_version: "dev".to_string(),
            dataset_name: self.config.dataset_name.clone(),
            dataset_hash: "dev".to_string(),
            data_start: bars.first().unwrap().timestamp,
            data_end: bars.last().unwrap().timestamp,
            initial_balance: self.config.initial_balance,
            configuration: self.config_as_json(),
        });
        self.event_bus.publish(&run_started)?;

        // ── Step 2: Initialize strategy ───────────
        strategy.initialize();

        // ── Step 3: Portfolio view starts empty ───
        let mut portfolio = PortfolioView::empty(
            self.config.initial_balance
        );

        // ── Step 4: Bar loop ──────────────────────
        let mut history: Vec<Bar> = Vec::new();
        let total_bars = bars.len() as u64;

        for bar in &bars {
            // 4a — emit BarReceivedEvent
            let bar_event = Event::BarReceived(BarReceivedEvent {
                metadata: EventMetadata::new(run_id, bar.timestamp),
                bar: bar.clone(),
            });
            self.event_bus.publish(&bar_event)?;

            // 4b — call strategy with current bar,
            //       portfolio view, and bar history
            let signals = strategy.on_bar(
                bar,
                &portfolio,
                &history,
            );

            // 4c — process each signal
            for signal in signals {
                let signal_id = Uuid::new_v4();

                // Emit SignalEmittedEvent
                let signal_event = Event::SignalEmitted(
                    SignalEmittedEvent {
                        metadata: EventMetadata::new(
                            run_id,
                            bar.timestamp,
                        ),
                        signal_id,
                        direction: signal.direction,
                        size: signal.size,
                        intended_price: signal.intended_price,
                        sl: signal.sl,
                        tp: signal.tp,
                        reason: signal.reason.clone(),
                    },
                );
                self.event_bus.publish(&signal_event)?;

                // Emit OrderIntentCreatedEvent
                // Execution model subscribes to this
                // and takes over from here
                let intent_event = Event::OrderIntentCreated(
                    OrderIntentCreatedEvent {
                        metadata: EventMetadata::new(
                            run_id,
                            bar.timestamp,
                        ),
                        order_id: Uuid::new_v4(),
                        signal_id,
                        direction: signal.direction,
                        size: signal.size,
                        intended_price: signal.intended_price,
                        sl: signal.sl,
                        tp: signal.tp,
                        reason: signal.reason,
                    },
                );
                self.event_bus.publish(&intent_event)?;
            }

            // 4d — add current bar to history
            //       so next bar can look back
            history.push(bar.clone());

            // 4e — update portfolio view
            // For now this is a placeholder —
            // the real update comes from the
            // portfolio manager via events
            self.update_portfolio_view(
                &mut portfolio,
                &history,
            );
        }

        // ── Step 5: Teardown strategy ─────────────
        strategy.teardown();

        // ── Step 6: Emit RunCompletedEvent ────────
        let end_time = Utc::now();
        let run_completed = Event::RunCompleted(RunCompletedEvent {
            metadata: EventMetadata::new(run_id, end_time),
            start_time,
            end_time,
            total_bars,
            total_trades: 0, // updated by portfolio manager
            final_balance: portfolio.balance,
            final_equity: portfolio.equity,
            realised_pnl: portfolio.equity
                - self.config.initial_balance,
        });
        self.event_bus.publish(&run_completed)?;

        Ok(())
    }

    /// Returns the run ID for this engine
    pub fn run_id(&self) -> Uuid {
        self.config.run_id
    }

    /// Serializes config to JSON string for RunStartedEvent
    fn config_as_json(&self) -> String {
        format!(
            r#"{{"spread":{},"slippage":{},"commission":{}}}"#,
            self.config.spread,
            self.config.slippage,
            self.config.commission,
        )
    }

    /// Placeholder portfolio view update.
    /// Real implementation comes from portfolio manager
    /// subscribing to fill events.
    fn update_portfolio_view(
        &self,
        _portfolio: &mut PortfolioView,
        _history: &[Bar],
    ) {
        // Portfolio manager will handle this
        // via event subscriptions
    }
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::strategy::{PortfolioView, StrategySignal};
    use chrono::TimeZone;
    use observa_core::bar::Bar;
    use observa_core::events::Event;
    use observa_core::types::Direction;
    use std::cell::RefCell;
    use std::rc::Rc;

    /// Builds a sequence of valid test bars
    fn test_bars(count: usize) -> Vec<Bar> {
        (0..count)
            .map(|i| {
                Bar::new(
                    Utc.with_ymd_and_hms(
                        2021, 12, 31,
                        21, i as u32, 0,
                    )
                    .unwrap(),
                    1.1376,
                    1.13787,
                    1.1376,
                    1.13786,
                    Some(278.19),
                )
            })
            .collect()
    }

    /// Builds a default test config
    fn test_config() -> EngineConfig {
        EngineConfig::new(
            10_000.0,
            0.0002,
            0.0001,
            7.0,
            "TestStrategy",
            "EURUSD_M15",
        )
    }

    /// Strategy that does nothing — used to test
    /// the engine loop runs correctly
    struct DoNothingStrategy;
    impl Strategy for DoNothingStrategy {
        fn initialize(&mut self) {}
        fn on_bar(
            &mut self,
            _bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            vec![]
        }
        fn teardown(&mut self) {}
    }

    /// Strategy that buys on every bar
    struct AlwaysBuyStrategy;
    impl Strategy for AlwaysBuyStrategy {
        fn initialize(&mut self) {}
        fn on_bar(
            &mut self,
            bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            vec![StrategySignal {
                direction:      Direction::Buy,
                size:           1.0,
                intended_price: bar.close,
                sl:             Some(bar.close - 0.0020),
                tp:             Some(bar.close + 0.0040),
                reason:         "Test buy".to_string(),
            }]
        }
        fn teardown(&mut self) {}
    }

    #[test]
    fn engine_emits_run_started_and_completed() {
        let event_types = Rc::new(RefCell::new(Vec::new()));
        let event_types_clone = event_types.clone();

        let mut bus = EventBus::new();
        bus.subscribe("tracker", move |event| {
            let label = match event {
                Event::RunStarted(_)  => "RunStarted",
                Event::RunCompleted(_) => "RunCompleted",
                Event::BarReceived(_) => "BarReceived",
                _                     => "Other",
            };
            event_types_clone.borrow_mut()
                .push(label.to_string());
        });

        let mut engine = Engine::new(test_config(), bus);
        let mut strategy = DoNothingStrategy;
        engine.run(&mut strategy, test_bars(3)).unwrap();

        let events = event_types.borrow();

        // First event must be RunStarted
        assert_eq!(events[0], "RunStarted");

        // Last event must be RunCompleted
        assert_eq!(events[events.len() - 1], "RunCompleted");
    }

    #[test]
    fn engine_emits_bar_event_for_each_bar() {
        let bar_count = Rc::new(RefCell::new(0u32));
        let bar_count_clone = bar_count.clone();

        let mut bus = EventBus::new();
        bus.subscribe("bar_counter", move |event| {
            if matches!(event, Event::BarReceived(_)) {
                *bar_count_clone.borrow_mut() += 1;
            }
        });

        let mut engine = Engine::new(test_config(), bus);
        let mut strategy = DoNothingStrategy;
        engine.run(&mut strategy, test_bars(5)).unwrap();

        assert_eq!(*bar_count.borrow(), 5);
    }

    #[test]
    fn engine_emits_signal_and_intent_for_each_signal() {
        let signal_count = Rc::new(RefCell::new(0u32));
        let intent_count = Rc::new(RefCell::new(0u32));
        let signal_clone = signal_count.clone();
        let intent_clone = intent_count.clone();

        let mut bus = EventBus::new();
        bus.subscribe("signal_tracker", move |event| {
            match event {
                Event::SignalEmitted(_) => {
                    *signal_clone.borrow_mut() += 1;
                }
                Event::OrderIntentCreated(_) => {
                    *intent_clone.borrow_mut() += 1;
                }
                _ => {}
            }
        });

        let mut engine = Engine::new(test_config(), bus);
        let mut strategy = AlwaysBuyStrategy;

        // 3 bars, strategy buys every bar
        // = 3 signals, 3 intents
        engine.run(&mut strategy, test_bars(3)).unwrap();

        assert_eq!(*signal_count.borrow(), 3);
        assert_eq!(*intent_count.borrow(), 3);
    }

    #[test]
    fn engine_passes_growing_history_to_strategy() {
        let history_lengths = Rc::new(RefCell::new(Vec::new()));
        let history_clone = history_lengths.clone();

        struct HistoryTracker {
            lengths: Rc<RefCell<Vec<usize>>>,
        }

        impl Strategy for HistoryTracker {
            fn initialize(&mut self) {}
            fn on_bar(
                &mut self,
                _bar: &Bar,
                _portfolio: &PortfolioView,
                history: &[Bar],
            ) -> Vec<StrategySignal> {
                self.lengths.borrow_mut().push(history.len());
                vec![]
            }
            fn teardown(&mut self) {}
        }

        let mut bus = EventBus::new();
        bus.subscribe("noop", |_| {});

        let mut engine = Engine::new(test_config(), bus);
        let mut strategy = HistoryTracker {
            lengths: history_clone,
        };

        engine.run(&mut strategy, test_bars(4)).unwrap();

        // History grows by one each bar
        // First bar sees 0 history, second sees 1, etc.
        assert_eq!(
            *history_lengths.borrow(),
            vec![0, 1, 2, 3]
        );
    }

    #[test]
    fn engine_returns_error_for_empty_bars() {
        let mut bus = EventBus::new();
        bus.subscribe("noop", |_| {});

        let mut engine = Engine::new(test_config(), bus);
        let mut strategy = DoNothingStrategy;

        let result = engine.run(&mut strategy, vec![]);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            EngineError::NoDataLoaded
        ));
    }
}