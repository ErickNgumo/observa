use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;

use serde_json;
use tiny_http::{Header, Response, Server};

use observa_core::bar::Bar;
use observa_core::events::{Event, EventMetadata, OrderIntentCreatedEvent};
use observa_data::csv_reader::CsvReader;
use observa_engine::strategy::{PortfolioView, Strategy};
use observa_execution::execution::{ExecutionConfig, ExecutionModel, FillResult};
use observa_metrics::metrics::MetricsEngine;
use observa_portfolio::portfolio::PortfolioManager;
use observa_python::strategy::{detect_strategy_class, PyStrategy};
use uuid::Uuid;

// ────────────────────────────────────────────────
// CLI Arguments
// ────────────────────────────────────────────────

/// Parsed command line arguments for `observa run`
struct CliArgs {
    /// Path to the Python strategy file
    strategy_file: PathBuf,

    /// Name of the strategy class inside the file
    /// If None, auto-detected from the file
    class_name: Option<String>,

    /// Path to the CSV data file
    data_file: PathBuf,

    /// Initial account balance
    initial_balance: f64,

    /// Fixed spread in price units
    spread: f64,

    /// Fixed slippage in price units
    slippage: f64,

    /// Commission per trade
    commission: f64,

    /// Port to serve the visualization on
    port: u16,
}

impl CliArgs {
    fn parse() -> Result<Self, String> {
        let args: Vec<String> = std::env::args().collect();

        // Minimum: observa-cli --strategy file.py --data file.csv
        if args.len() < 5 {
            return Err(Self::usage());
        }

        // First arg after binary name must be "run"
        if args[1] != "run" {
            return Err(format!(
                "Unknown command '{}'\n\n{}", args[1], Self::usage()
            ));
        }

        let mut strategy_file: Option<PathBuf> = None;
        let mut class_name:    Option<String>  = None;
        let mut data_file:     Option<PathBuf> = None;
        let mut initial_balance = 10_000.0_f64;
        let mut spread           = 0.0002_f64;
        let mut slippage         = 0.0001_f64;
        let mut commission       = 7.0_f64;
        let mut port             = 7878_u16;

        let mut i = 2;
        while i < args.len() {
            match args[i].as_str() {
                "--strategy" | "-s" => {
                    i += 1;
                    strategy_file = Some(PathBuf::from(&args[i]));
                }
                "--class" | "-c" => {
                    i += 1;
                    class_name = Some(args[i].clone());
                }
                "--data" | "-d" => {
                    i += 1;
                    data_file = Some(PathBuf::from(&args[i]));
                }
                "--balance" | "-b" => {
                    i += 1;
                    initial_balance = args[i].parse().map_err(|_| {
                        format!("Invalid balance: {}", args[i])
                    })?;
                }
                "--spread" => {
                    i += 1;
                    spread = args[i].parse().map_err(|_| {
                        format!("Invalid spread: {}", args[i])
                    })?;
                }
                "--slippage" => {
                    i += 1;
                    slippage = args[i].parse().map_err(|_| {
                        format!("Invalid slippage: {}", args[i])
                    })?;
                }
                "--commission" => {
                    i += 1;
                    commission = args[i].parse().map_err(|_| {
                        format!("Invalid commission: {}", args[i])
                    })?;
                }
                "--port" | "-p" => {
                    i += 1;
                    port = args[i].parse().map_err(|_| {
                        format!("Invalid port: {}", args[i])
                    })?;
                }
                "--help" | "-h" => {
                    println!("{}", Self::usage());
                    std::process::exit(0);
                }
                unknown => {
                    return Err(format!(
                        "Unknown argument: {}\n\n{}", unknown, Self::usage()
                    ));
                }
            }
            i += 1;
        }

        Ok(CliArgs {
            strategy_file: strategy_file.ok_or(
                "--strategy is required".to_string()
            )?,
            class_name,
            data_file: data_file.ok_or(
                "--data is required".to_string()
            )?,
            initial_balance,
            spread,
            slippage,
            commission,
            port,
        })
    }

    fn usage() -> String {
        r#"
Observa — Visual Backtesting Engine

USAGE:
    observa run --strategy <file.py> --data <file.csv> [OPTIONS]

REQUIRED:
    --strategy, -s <path>     Python strategy file
    --data,     -d <path>     CSV data file (OHLCV)

OPTIONAL:
    --class,    -c <name>     Strategy class name (auto-detected if omitted)
    --balance,  -b <amount>   Initial balance (default: 10000)
    --spread       <value>    Fixed spread in price units (default: 0.0002)
    --slippage     <value>    Fixed slippage in price units (default: 0.0001)
    --commission   <value>    Commission per trade (default: 7.0)
    --port,     -p <port>     Visualization server port (default: 7878)
    --help,     -h            Show this help

EXAMPLE:
    observa run --strategy ema_crossover.py --data EURUSD_M15.csv
    observa run -s my_strategy.py -d EURUSD.csv -b 50000 --spread 0.0001
        "#.trim().to_string()
    }
}

// ────────────────────────────────────────────────
// Backtest runner
// ────────────────────────────────────────────────

fn run_backtest(
    bars: Vec<Bar>,
    strategy: &mut dyn Strategy,
    initial_balance: f64,
    execution_config: ExecutionConfig,
) -> Vec<String> {
    let mut events: Vec<String> = Vec::new();

    let run_id        = Uuid::new_v4();
    let mut portfolio = PortfolioManager::new(run_id, initial_balance, execution_config.commission);
    let execution     = ExecutionModel::new(execution_config);
    let mut metrics   = MetricsEngine::new(initial_balance, 96.0 * 252.0);

    strategy.initialize();

    let mut history: Vec<Bar> = Vec::new();

    let push = |event: &Event, store: &mut Vec<String>| {
        if let Ok(json) = serde_json::to_string(event) {
            store.push(json);
        }
    };

    for bar in &bars {
        // Check SL/TP
        if let Some(pe) = portfolio.check_sl_tp(bar) {
            if let Some(closed) = pe.position_closed {
                metrics.on_trade_closed(closed.pnl);
                push(&Event::PositionClosed(closed), &mut events);
            }
            metrics.on_snapshot(bar.timestamp, pe.snapshot.equity);
            push(&Event::PortfolioSnapshot(pe.snapshot), &mut events);
        }

        // Emit bar event with current indicator state
        // (indicators are managed inside the Python strategy
        //  so we emit a basic bar event here)
        let bar_json = serde_json::json!({
            "event_type": "BarReceived",
            "timestamp":  bar.timestamp,
            "open":       bar.open,
            "high":       bar.high,
            "low":        bar.low,
            "close":      bar.close,
            "volume":     bar.volume,
            "ema_fast":   null,
            "ema_slow":   null,
        });
        events.push(bar_json.to_string());

        // Build portfolio view
        let open_pos       = portfolio.open_position();
        let portfolio_view = PortfolioView {
            balance:              portfolio.balance(),
            equity:               portfolio.balance(),
            has_open_position:    open_pos.is_some(),
            position_direction:   open_pos.map(|p| p.direction),
            position_entry_price: open_pos.map(|p| p.entry_price),
            unrealised_pnl:       0.0,
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
                intended_price: if signal.intended_price == 0.0 {
                    bar.close // default to bar close if not specified
                } else {
                    signal.intended_price
                },
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
                                push(&Event::PositionOpened(opened), &mut events);
                            }
                            if let Some(closed) = pe.position_closed {
                                metrics.on_trade_closed(closed.pnl);
                                push(&Event::PositionClosed(closed), &mut events);
                            }
                            metrics.on_snapshot(bar.timestamp, pe.snapshot.equity);
                            push(&Event::PortfolioSnapshot(pe.snapshot), &mut events);
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

    // Emit final metrics
    let report = metrics.report();
    println!();
    println!("════════════════════════════════════════");
    println!("  BACKTEST COMPLETE");
    println!("════════════════════════════════════════");
    println!("  Total Return:   {:.2}%", report.total_return_pct);
    println!("  Max Drawdown:   {:.2}%", report.max_drawdown_pct);
    println!("  Win Rate:       {:.1}%", report.win_rate_pct);
    println!("  Profit Factor:  {:.2}",  report.profit_factor);
    println!("  Total Trades:   {}",     report.total_trades);
    println!("  Final Balance:  ${:.2}", report.total_return_pct / 100.0
        * 10_000.0 + 10_000.0);
    println!("════════════════════════════════════════");

    let report_json = serde_json::json!({
        "event_type": "MetricsReport",
        "report": report,
    });
    events.push(report_json.to_string());

    events
}

// ────────────────────────────────────────────────
// HTTP Server — same as observa-server
// ────────────────────────────────────────────────

fn serve(events: Vec<String>, port: u16) {
    let events_json = Arc::new(format!("[{}]", events.join(",")));
    let addr        = format!("0.0.0.0:{}", port);
    let server      = Server::http(&addr).expect("Failed to start server");

    println!();
    println!("  Open http://localhost:{} in your browser", port);
    println!("  Press Ctrl+C to stop");
    println!();

    for request in server.incoming_requests() {
        let url         = request.url().to_string();
        let events_json = events_json.clone();

        thread::spawn(move || {
            match url.as_str() {
                "/" => {
                    let html = include_str!("../../../frontend/index.html");
                    let response = Response::from_string(html)
                        .with_header(
                            Header::from_bytes("Content-Type",
                                "text/html; charset=utf-8").unwrap()
                        );
                    request.respond(response).ok();
                }

                "/api/events" => {
                    let response =
                        Response::from_string((*events_json).clone())
                            .with_header(
                                Header::from_bytes("Content-Type",
                                    "application/json").unwrap()
                            )
                            .with_header(
                                Header::from_bytes(
                                    "Access-Control-Allow-Origin", "*").unwrap()
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
                                    Header::from_bytes(
                                        "Content-Type", content_type).unwrap()
                                );
                            request.respond(response).ok();
                        }
                        Err(_) => {
                            request.respond(
                                Response::from_string("Not found")
                                    .with_status_code(404)
                            ).ok();
                        }
                    }
                }

                _ => {
                    request.respond(
                        Response::from_string("Not found")
                            .with_status_code(404)
                    ).ok();
                }
            }
        });
    }
}

// ────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────

fn main() {
    let args = match CliArgs::parse() {
        Ok(a)  => a,
        Err(e) => {
            eprintln!("Error: {}", e);
            std::process::exit(1);
        }
    };

    println!("╔══════════════════════════════════════╗");
    println!("║         OBSERVA v0.1                 ║");
    println!("╚══════════════════════════════════════╝");
    println!();

    // ── Detect or use provided class name ─────
    let class_name = match args.class_name {
        Some(name) => {
            println!("  Strategy class: {}", name);
            name
        }
        None => {
            println!("  Detecting strategy class...");
            match detect_strategy_class(&args.strategy_file) {
                Ok(name) => {
                    println!("  Found: {}", name);
                    name
                }
                Err(e) => {
                    eprintln!("  Error: {}", e);
                    eprintln!(
                        "  Tip: use --class <ClassName> to specify manually"
                    );
                    std::process::exit(1);
                }
            }
        }
    };

    // ── Load Python strategy ───────────────────
    println!("  Loading strategy: {}",
        args.strategy_file.display());

    let mut strategy = match PyStrategy::load(
        &args.strategy_file,
        &class_name,
    ) {
        Ok(s)  => s,
        Err(e) => {
            eprintln!("  Failed to load strategy: {}", e);
            std::process::exit(1);
        }
    };

    // ── Load market data ───────────────────────
    println!("  Loading data: {}", args.data_file.display());
    let bars = match CsvReader::load(&args.data_file) {
        Ok(b)  => b,
        Err(e) => {
            eprintln!("  Failed to load data: {}", e);
            std::process::exit(1);
        }
    };
    println!("  Loaded {} bars", bars.len());

    // ── Run backtest ───────────────────────────
    println!();
    println!("  Running backtest...");

    let execution_config = ExecutionConfig {
        spread:            args.spread,
        slippage:          args.slippage,
        commission:        args.commission,
        min_stop_distance: 0.0010,
        min_lot_size:      0.01,
        max_lot_size:      100.0,
        fill_mode:         observa_execution::execution::FillMode::NextBarOpen,
    };

    let events = run_backtest(
        bars,
        &mut strategy,
        args.initial_balance,
        execution_config,
    );

    // ── Serve visualization ────────────────────
    serve(events, args.port);
}
