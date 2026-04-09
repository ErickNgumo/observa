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