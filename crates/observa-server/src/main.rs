use std::sync::Arc;
use std::thread;

use serde_json;
use tiny_http::{Header, Response, Server};

use observa_core::bar::Bar;
use observa_core::events::{Event, EventMetadata, OrderIntentCreatedEvent};
use observa_core::types::Direction;
use observa_data::csv_reader::CsvReader;
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use observa_execution::execution::{ExecutionConfig, ExecutionModel, FillResult};
use observa_metrics::metrics::MetricsEngine;
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
            self.fast_ema = Some(Self::update_ema(
                self.fast_ema, bar.close, self.fast_period,
            ));
            self.slow_ema = Some(Self::update_ema(
                self.slow_ema, bar.close, self.slow_period,
            ));
            return vec![];
        }

        let prev_fast = match self.prev_fast { Some(v) => v, None => return vec![] };
        let prev_slow = match self.prev_slow { Some(v) => v, None => return vec![] };

        self.prev_fast = self.fast_ema;
        self.prev_slow = self.slow_ema;
        self.fast_ema = Some(Self::update_ema(
            self.fast_ema, bar.close, self.fast_period,
        ));
        self.slow_ema = Some(Self::update_ema(
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
// collect_events
// Runs the backtest and returns JSON strings
// ────────────────────────────────────────────────

fn collect_events(bars: Vec<Bar>) -> Vec<String> {
    let mut events: Vec<String> = Vec::new();

    let run_id        = Uuid::new_v4();
    let mut portfolio = PortfolioManager::new(run_id, 10_000.0, 7.0);
    let execution     = ExecutionModel::new(ExecutionConfig::default_eurusd());

    // 15-minute bars, 252 trading days/year → 96 bars/day * 252
    let mut metrics = MetricsEngine::new(10_000.0, 96.0 * 252.0);

    let mut strategy = EmaCrossover::new(5, 20);
    strategy.initialize();

    let mut history: Vec<Bar> = Vec::new();

    // Simple helper — push a serialized event onto the vec
    let push = |event: &Event, store: &mut Vec<String>| {
        if let Ok(json) = serde_json::to_string(event) {
            store.push(json);
        }
    };

    for bar in &bars {
        // ── Check SL/TP on open positions ─────────
        if let Some(portfolio_events) = portfolio.check_sl_tp(bar) {
            if let Some(closed) = portfolio_events.position_closed {
                metrics.on_trade_closed(closed.pnl);
                push(&Event::PositionClosed(closed), &mut events);
            }

            metrics.on_snapshot(
                portfolio_events.snapshot.metadata.timestamp,
                portfolio_events.snapshot.equity,
            );
            push(
                &Event::PortfolioSnapshot(portfolio_events.snapshot),
                &mut events,
            );
        }

        // ── Emit enriched bar event with EMA values ─
        let bar_json = serde_json::json!({
            "event_type": "BarReceived",
            "timestamp":  bar.timestamp,
            "open":       bar.open,
            "high":       bar.high,
            "low":        bar.low,
            "close":      bar.close,
            "volume":     bar.volume,
            "ema_fast":   strategy.fast_ema,
            "ema_slow":   strategy.slow_ema,
        });
        events.push(bar_json.to_string());

        // ── Build portfolio view for strategy ──────
        let open_pos       = portfolio.open_position();
        let portfolio_view = PortfolioView {
            balance:              portfolio.balance(),
            equity:               portfolio.balance(),
            has_open_position:    open_pos.is_some(),
            position_direction:   open_pos.map(|p| p.direction),
            position_entry_price: open_pos.map(|p| p.entry_price),
            unrealised_pnl:       0.0,
        };

        // ── Call strategy ──────────────────────────
        let signals = strategy.on_bar(bar, &portfolio_view, &history);

        // ── Process each signal ────────────────────
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
                    push(&Event::OrderFilled(fill.clone()), &mut events);

                    match portfolio.process_fill(&fill) {
                        Ok(pe) => {
                            if let Some(opened) = pe.position_opened {
                                push(
                                    &Event::PositionOpened(opened),
                                    &mut events,
                                );
                            }
                            if let Some(closed) = pe.position_closed {
                                metrics.on_trade_closed(closed.pnl);
                                push(
                                    &Event::PositionClosed(closed),
                                    &mut events,
                                );
                            }

                            metrics.on_snapshot(
                                pe.snapshot.metadata.timestamp,
                                pe.snapshot.equity,
                            );
                            push(
                                &Event::PortfolioSnapshot(pe.snapshot),
                                &mut events,
                            );
                        }
                        Err(e) => eprintln!("Portfolio error: {}", e),
                    }
                }
                Ok(FillResult::Rejected(r)) => {
                    push(&Event::OrderRejected(r), &mut events);
                }
                Err(e) => eprintln!("Execution error: {}", e),
            }
        }

        history.push(bar.clone());
    }

    strategy.teardown();

    // ── Emit final metrics report ─────────────────
    let report = metrics.report();

    let report_json = serde_json::json!({
        "event_type": "MetricsReport",
        "report": report,
    });
    events.push(report_json.to_string());

    println!("Max Drawdown: {:.2}%", report.max_drawdown_pct);
    println!("Sharpe Ratio: {:?}", report.sharpe_ratio);
    println!("Calmar Ratio: {:?}", report.calmar_ratio);
    println!("Win Rate: {:.1}%", report.win_rate_pct);
    println!("Profit Factor: {:.2}", report.profit_factor);
    println!("Total Trades: {}", report.total_trades);

    events
}

// ────────────────────────────────────────────────
// HTTP Server
// ────────────────────────────────────────────────

fn main() {
    println!("Loading data and running backtest...");
    let bars = CsvReader::load("data/EURUSD_M15.csv")
        .expect("Failed to load CSV");

    let events = collect_events(bars);
    println!(
        "Backtest complete. {} events collected.",
        events.len()
    );

    // Build the JSON array ONCE on the main thread
    // before any requests arrive — no locking needed
    let events_json = Arc::new(format!("[{}]", events.join(",")));

    println!("Open http://localhost:7878 in your browser");

    let server = Server::http("0.0.0.0:7878").unwrap();

    for request in server.incoming_requests() {
        let url         = request.url().to_string();
        let events_json = events_json.clone();

        thread::spawn(move || {
            match url.as_str() {

                // ── Serve the frontend HTML ────────
                "/" => {
                    let html = include_str!(
                        "../../../frontend/index.html"
                    );
                    let response = Response::from_string(html)
                        .with_header(
                            Header::from_bytes(
                                "Content-Type",
                                "text/html; charset=utf-8",
                            )
                            .unwrap(),
                        );
                    request.respond(response).ok();
                }

                // ── Serve all events as JSON array ─
                "/api/events" => {
                    let response =
                        Response::from_string((*events_json).clone())
                            .with_header(
                                Header::from_bytes(
                                    "Content-Type",
                                    "application/json",
                                )
                                .unwrap(),
                            )
                            .with_header(
                                Header::from_bytes(
                                    "Access-Control-Allow-Origin",
                                    "*",
                                )
                                .unwrap(),
                            );
                    request.respond(response).ok();
                }

                url if url.starts_with("/css/") || url.starts_with("/js/") => {
                    let file_path = format!("frontend{}", url);
                    match std::fs::read_to_string(&file_path) {
                        Ok(contents) => {
                            let content_type = if url.ends_with(".css") {
                                "text/css"
                            } else {
                                "application/javascript"
                            };
                            let response = Response::from_string(contents)
                                .with_header(
                                    Header::from_bytes("Content-Type", content_type).unwrap()
                                );
                            request.respond(response).ok();
                        }
                        Err(_) => {
                            let response = Response::from_string("Not found")
                                .with_status_code(404);
                            request.respond(response).ok();
                        }
                    }
                }

                // ── 404 for everything else ────────
                _ => {
                    let response =
                        Response::from_string("Not found")
                            .with_status_code(404);
                    request.respond(response).ok();
                }
            }
        });
    }
}