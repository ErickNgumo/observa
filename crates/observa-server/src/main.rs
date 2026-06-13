use std::io::Write;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json;
use tiny_http::{Header, Response, Server};

use observa_core::bar::Bar;
use observa_core::events::{Event, EventMetadata, OrderIntentCreatedEvent};
use observa_core::types::Direction;
use observa_data::csv_reader::CsvReader;
use observa_engine::event_bus::EventBus;
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use observa_execution::execution::{ExecutionConfig, ExecutionModel, FillResult};
use observa_portfolio::portfolio::PortfolioManager;
use uuid::Uuid;

// ────────────────────────────────────────────────
// EMA Crossover Strategy
// Same as observa-runner but lives here too for now
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

    fn update_ema(current: Option<f64>, price: f64, period: usize) -> f64 {
        match current {
            None      => price,
            Some(ema) => {
                let k = 2.0 / (period as f64 + 1.0);
                price * k + ema * (1.0 - k)
            }
        }
    }
}

impl Strategy for EmaCrossover {
    fn initialize(&mut self) {}

    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        history: &[Bar],
    ) -> Vec<StrategySignal> {
        if history.len() < self.slow_period {
            self.prev_fast = self.fast_ema;
            self.prev_slow = self.slow_ema;
            self.fast_ema = Some(Self::update_ema(self.fast_ema, bar.close, self.fast_period));
            self.slow_ema = Some(Self::update_ema(self.slow_ema, bar.close, self.slow_period));
            return vec![];
        }

        let prev_fast = match self.prev_fast { Some(v) => v, None => return vec![] };
        let prev_slow = match self.prev_slow { Some(v) => v, None => return vec![] };

        self.prev_fast = self.fast_ema;
        self.prev_slow = self.slow_ema;
        self.fast_ema = Some(Self::update_ema(self.fast_ema, bar.close, self.fast_period));
        self.slow_ema = Some(Self::update_ema(self.slow_ema, bar.close, self.slow_period));

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
                    self.fast_period, self.slow_period
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
                    self.fast_period, self.slow_period
                ),
            }];
        }

        vec![]
    }

    fn teardown(&mut self) {}
}

// ────────────────────────────────────────────────
// EventCollector
// Runs the backtest and collects all events
// ────────────────────────────────────────────────

/// Runs a complete backtest and returns all events
/// in chronological order as serialized JSON strings.
fn collect_events(bars: Vec<Bar>) -> Vec<String> {
    let events: Arc<Mutex<Vec<String>>> =
        Arc::new(Mutex::new(Vec::new()));

    let events_clone = events.clone();

    // Build portfolio and execution
    let run_id = Uuid::new_v4();
    let mut portfolio = PortfolioManager::new(
        run_id, 10_000.0, 7.0
    );
    let execution = ExecutionModel::new(
        ExecutionConfig::default_eurusd()
    );

    let mut strategy = EmaCrossover::new(5, 20);
    strategy.initialize();

    let mut history: Vec<Bar> = Vec::new();

    // Helper closure to record an event
    let record = |event: &Event, store: &Arc<Mutex<Vec<String>>>| {
        if let Ok(json) = serde_json::to_string(event) {
            store.lock().unwrap().push(json);
        }
    };

    for bar in &bars {
        // Check SL/TP first
        if let Some(portfolio_events) = portfolio.check_sl_tp(bar) {
            if let Some(closed) = portfolio_events.position_closed {
                let e = Event::PositionClosed(closed);
                record(&e, &events_clone);
            }
            let snap = Event::PortfolioSnapshot(
                portfolio_events.snapshot
            );
            record(&snap, &events_clone);
        }

        // Emit bar event with EMA values
        let fast_ema = strategy.fast_ema;
        let slow_ema = strategy.slow_ema;

        // Build enriched bar event
        let bar_json = serde_json::json!({
            "event_type": "BarReceived",
            "timestamp":  bar.timestamp,
            "open":       bar.open,
            "high":       bar.high,
            "low":        bar.low,
            "close":      bar.close,
            "volume":     bar.volume,
            "ema_fast":   fast_ema,
            "ema_slow":   slow_ema,
        });
        events_clone.lock().unwrap()
            .push(bar_json.to_string());

        // Get portfolio view for strategy
        let open_pos = portfolio.open_position();
        let portfolio_view = PortfolioView {
            balance:               portfolio.balance(),
            equity:                portfolio.balance(),
            has_open_position:     open_pos.is_some(),
            position_direction:    open_pos.map(|p| p.direction),
            position_entry_price:  open_pos.map(|p| p.entry_price),
            unrealised_pnl:        0.0,
        };

        // Call strategy
        let signals = strategy.on_bar(bar, &portfolio_view, &history);

        // Process signals
        for signal in signals {
            let intent = OrderIntentCreatedEvent {
                metadata:       EventMetadata::new(run_id, bar.timestamp),
                order_id:       Uuid::new_v4(),
                signal_id:      Uuid::new_v4(),
                direction:      signal.direction,
                size:           signal.size,
                intended_price: signal.intended_price,
                sl:             signal.sl,
                tp:             signal.tp,
                reason:         signal.reason.clone(),
            };

            match execution.process(&intent, bar, portfolio.balance()) {
                Ok(FillResult::Filled(fill)) => {
                    let fill_event = Event::OrderFilled(fill.clone());
                    record(&fill_event, &events_clone);

                    match portfolio.process_fill(&fill) {
                        Ok(portfolio_events) => {
                            if let Some(opened) = portfolio_events.position_opened {
                                let e = Event::PositionOpened(opened);
                                record(&e, &events_clone);
                            }
                            if let Some(closed) = portfolio_events.position_closed {
                                let e = Event::PositionClosed(closed);
                                record(&e, &events_clone);
                            }
                            let snap = Event::PortfolioSnapshot(
                                portfolio_events.snapshot
                            );
                            record(&snap, &events_clone);
                        }
                        Err(e) => eprintln!("Portfolio error: {}", e),
                    }
                }
                Ok(FillResult::Rejected(r)) => {
                    let e = Event::OrderRejected(r);
                    record(&e, &events_clone);
                }
                Err(e) => eprintln!("Execution error: {}", e),
            }
        }

        history.push(bar.clone());
    }

    strategy.teardown();

    Arc::try_unwrap(events)
        .unwrap()
        .into_inner()
        .unwrap()
}

// ────────────────────────────────────────────────
// HTTP Server
// ────────────────────────────────────────────────

fn main() {
    // Load data and run backtest
    println!("Loading data and running backtest...");
    let bars = CsvReader::load("data/EURUSD_M15.csv")
        .expect("Failed to load CSV");

    let events = collect_events(bars);
    println!("Backtest complete. {} events collected.", events.len());
    println!("Open http://localhost:7878 in your browser");

    // Wrap events in Arc so they can be shared
    // across request handler threads
    let events = Arc::new(events);

    // Start HTTP server
    let server = Server::http("0.0.0.0:7878").unwrap();

    for request in server.incoming_requests() {
        let url = request.url().to_string();
        let events = events.clone();

        thread::spawn(move || {
            match url.as_str() {

                // Serve the main HTML page
                "/" => {
                    let html = include_str!("../../../frontend/index.html");
                    let response = Response::from_string(html)
                        .with_header(
                            Header::from_bytes(
                                "Content-Type",
                                "text/html; charset=utf-8",
                            ).unwrap()
                        );
                    request.respond(response).ok();
                }

                // Serve all events as JSON array
                "/api/events" => {
                    let json = format!(
                        "[{}]",
                        events.join(",")
                    );
                    let response = Response::from_string(json)
                        .with_header(
                            Header::from_bytes(
                                "Content-Type",
                                "application/json",
                            ).unwrap()
                        )
                        .with_header(
                            Header::from_bytes(
                                "Access-Control-Allow-Origin",
                                "*",
                            ).unwrap()
                        );
                    request.respond(response).ok();
                }

                // 404 for everything else
                _ => {
                    let response = Response::from_string("Not found")
                        .with_status_code(404);
                    request.respond(response).ok();
                }
            }
        });
    }
}