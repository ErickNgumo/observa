use std::path::PathBuf;
use std::sync::Arc;
use std::thread;

use serde_json;
use tiny_http::{Header, Response, Server};

mod config;
use config::load_config;
use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig, StrategyConfig,
};
use observa_core::types::ExitReason;
use observa_data::csv_reader::CsvReader;
use observa_engine::engine::Engine;
use observa_engine::persistence::{self, PersistenceError};
use observa_engine::runevents::EngineEventPayload;
use observa_metrics::metrics::MetricsEngine;
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
    class_name: Option<String>,
    /// Path to the CSV data file
    data_file: PathBuf,
    /// .yaml configuration file (defaults to config.yaml in the CWD)
    config_file: Option<PathBuf>,
    /// Port to serve the visualization on
    port: u16,
    /// Optional run-artifact output directory (run.json/events.jsonl/metrics.json)
    output: Option<PathBuf>,
}

impl CliArgs {
    fn parse() -> Result<Self, String> {
        let args: Vec<String> = std::env::args().collect();
        if args.len() < 5 {
            return Err(Self::usage());
        }
        if args[1] != "run" {
            return Err(format!(
                "Unknown command '{}'\n\n{}",
                args[1],
                Self::usage()
            ));
        }

        let mut strategy_file: Option<PathBuf> = None;
        let mut class_name: Option<String> = None;
        let mut data_file: Option<PathBuf> = None;
        let mut config_file: Option<PathBuf> = None;
        let mut port = 7878_u16;
        let mut output: Option<PathBuf> = None;

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
                "--config" => {
                    i += 1;
                    config_file = Some(PathBuf::from(&args[i]));
                }
                "--port" | "-p" => {
                    i += 1;
                    port = args[i]
                        .parse()
                        .map_err(|_| format!("Invalid port: {}", args[i]))?;
                }
                "--output" | "-o" => {
                    i += 1;
                    output = Some(PathBuf::from(&args[i]));
                }
                "--help" | "-h" => {
                    println!("{}", Self::usage());
                    std::process::exit(0);
                }
                unknown => {
                    return Err(format!(
                        "Unknown argument: {}\n\n{}",
                        unknown,
                        Self::usage()
                    ));
                }
            }
            i += 1;
        }

        Ok(CliArgs {
            strategy_file: strategy_file.ok_or("--strategy is required".to_string())?,
            class_name,
            data_file: data_file.ok_or("--data is required".to_string())?,
            config_file,
            port,
            output,
        })
    }

    fn usage() -> String {
        r#"
Observa — Visual Backtesting Engine

USAGE:
    observa init
    observa run --strategy <file.py> --data <file.csv> [OPTIONS]

COMMANDS:
    init     Generate a default config.yaml in the current directory
    run      Run a backtest

REQUIRED (run):
    --strategy, -s <path>   Python strategy file
    --data,     -d <path>   CSV data file (OHLCV)

OPTIONAL (run):
    --config,   -c <path>   Config file (default: config.yaml)
    --class        <name>   Strategy class name (auto-detected if omitted)
    --port,     -p <port>   Visualization server port (default: 7878)
    --output,   -o <dir>    Persist run artifacts to <dir> (create-only dir)
    --help,     -h          Show this help

EXAMPLE:
    observa init
    observa run --strategy ema_crossover.py --data EURUSD_M15.csv
    observa run -s my_strategy.py -d EURUSD.csv --config my_config.yaml
    "#
        .trim()
        .to_string()
    }
}

// ────────────────────────────────────────────────
// Legacy config → canonical BacktestConfig mapping
// ────────────────────────────────────────────────

/// Maps the (legacy) CLI YAML configuration onto the canonical resolved
/// `BacktestConfig` consumed by the Engine. Only input adaptation lives here —
/// the CLI performs no backtest economics.
fn build_canonical_config(
    legacy: &config::ObservaConfig,
    strategy_file: &std::path::Path,
    class_name: &str,
    bars: &[Bar],
) -> Result<BacktestConfig, String> {
    // Legacy flat commission is a per-trade fee charged once at close.
    let commission_mode = CommissionMode::RoundTrip;
    let flat_per_fill = legacy.execution.commission;

    let quote_currency = if legacy.account.currency.trim().is_empty() {
        "USD".to_string()
    } else {
        legacy.account.currency.trim().to_uppercase()
    };
    // MVP requires account == quote currency. Legacy configs quote in the
    // account currency by construction; mismatch is rejected clearly.
    let base_currency = derive_base_currency(&legacy.instrument.symbol);

    let fill_mode = match legacy.execution.fill_mode.trim().to_lowercase().as_str() {
        "bar_close" | "this_bar_close" => FillMode::BarClose,
        _ => FillMode::NextBarOpen, // default
    };

    let dataset = DatasetConfig {
        source: "csv".to_string(),
        hash: None,
        interval: detect_interval(bars),
        start: bars.first().map(|b| b.timestamp),
        end: bars.last().map(|b| b.timestamp),
        bar_count: Some(bars.len() as u64),
    };

    let config = BacktestConfig {
        version: 1,
        account: AccountConfig {
            starting_balance: legacy.account.initial_balance,
            currency: quote_currency.clone(),
            leverage: if legacy.instrument.margin_rate.is_finite()
                && legacy.instrument.margin_rate > 0.0
            {
                1.0 / legacy.instrument.margin_rate
            } else {
                100.0
            },
        },
        instrument: InstrumentConfig {
            symbol: legacy.instrument.symbol.clone(),
            base_currency,
            quote_currency,
            contract_size: legacy.instrument.contract_size,
            min_quantity: legacy.execution.min_lot_size.max(0.0),
            max_quantity: legacy
                .execution
                .max_lot_size
                .max(legacy.execution.min_lot_size),
            quantity_step: 0.01,
            ..Default::default()
        },
        execution: CoreExecutionConfig {
            fill_mode,
            spread: legacy.execution.spread,
            slippage: legacy.execution.slippage,
            commission: CommissionConfig {
                mode: commission_mode,
                flat_per_fill,
                rate_per_unit: 0.0,
            },
            ..Default::default()
        },
        dataset: Some(dataset),
        strategy: Some(StrategyConfig {
            name: class_name.to_string(),
            source: Some(strategy_file.to_string_lossy().to_string()),
            source_hash: None,
            parameters: Default::default(),
        }),
    };

    config.validate().map_err(|e| e.to_string())?;
    if !config.is_resolved() {
        return Err("internal: resolved configuration incomplete".to_string());
    }
    Ok(config)
}

/// Deterministic interval detection from the first two bars (presentation
/// metadata; the loader already guarantees chronological order).
fn detect_interval(bars: &[Bar]) -> BarInterval {
    if bars.len() < 2 {
        return BarInterval::Minute(15);
    }
    let secs = (bars[1].timestamp - bars[0].timestamp).num_seconds().max(1);
    if secs % 604_800 == 0 {
        BarInterval::Week
    } else if secs % 86_400 == 0 {
        BarInterval::Day
    } else if secs % 3_600 == 0 {
        BarInterval::Hour((secs / 3_600) as u32)
    } else if secs % 60 == 0 {
        BarInterval::Minute((secs / 60) as u32)
    } else {
        BarInterval::Minute(15)
    }
}

fn derive_base_currency(symbol: &str) -> String {
    // Deterministic best-effort for legacy configs (informational).
    if symbol.len() >= 3 && symbol[..3].chars().all(|c| c.is_ascii_alphabetic()) {
        symbol[..3].to_uppercase()
    } else {
        "XXX".to_string()
    }
}

// ────────────────────────────────────────────────
// Presentation (console summary + UI event synthesis)
// ────────────────────────────────────────────────

/// Snake-case event type label (matches the persisted `"type"` tag).
fn event_type_label(payload: &EngineEventPayload) -> &'static str {
    match payload {
        EngineEventPayload::RunStarted { .. } => "run_started",
        EngineEventPayload::RunCompleted { .. } => "run_completed",
        EngineEventPayload::RunFailed { .. } => "run_failed",
        EngineEventPayload::StrategyInitialized { .. } => "strategy_initialized",
        EngineEventPayload::StrategyError { .. } => "strategy_error",
        EngineEventPayload::StrategyTeardown { .. } => "strategy_teardown",
        EngineEventPayload::BarProcessed { .. } => "bar_processed",
        EngineEventPayload::StrategyDecision { .. } => "strategy_decision",
        EngineEventPayload::OrderCreated { .. } => "order_created",
        EngineEventPayload::OrderPending { .. } => "order_pending",
        EngineEventPayload::OrderTriggered { .. } => "order_triggered",
        EngineEventPayload::OrderFilled { .. } => "order_filled",
        EngineEventPayload::OrderRejected { .. } => "order_rejected",
        EngineEventPayload::OrderExpired { .. } => "order_expired",
        EngineEventPayload::PositionOpened { .. } => "position_opened",
        EngineEventPayload::PositionClosed { .. } => "position_closed",
        EngineEventPayload::PortfolioSnapshot { .. } => "portfolio_snapshot",
    }
}

/// Prints the persisted-run summary (events count/bounds, economics, and the
/// reproducibility hashes recorded in run.json).
fn print_run_artifact_summary(
    result: &observa_engine::engine::RunResult,
    bars: &[Bar],
    config: &BacktestConfig,
) {
    println!();
    println!("  Artifact summary:");
    println!("    Events:           {}", result.events.len());
    match (result.events.first(), result.events.last()) {
        (Some(first), Some(last)) => {
            println!("    First event:      {}", event_type_label(&first.payload));
            println!("    Last event:       {}", event_type_label(&last.payload));
        }
        _ => {}
    }
    println!(
        "    Final balance:    ${:.2}",
        result.final_state.final_balance
    );
    println!(
        "    Final equity:     ${:.2}",
        result.final_state.final_equity
    );
    println!("    Trades:           {}", result.trades.len());
    println!(
        "    Open positions:   {}",
        result.final_state.open_positions_remaining
    );
    match observa_engine::persistence::dataset_identity(bars) {
        Ok(identity) => {
            println!("    Dataset sha256:   {}", identity.sha256);
            println!("    Dataset bars:     {}", identity.bar_count);
        }
        Err(_) => {}
    }
    match observa_engine::persistence::strategy_identity(config) {
        Ok(sha) => println!("    Strategy sha256:  {}", sha),
        Err(_) => {}
    }
}

fn print_summary(result: &observa_engine::engine::RunResult, metrics: &MetricsReportView) {
    println!();
    println!("════════════════════════════════════════");
    println!("  BACKTEST COMPLETE");
    println!("════════════════════════════════════════");
    println!("  Bars processed: {}", result.total_bars);
    println!("  Total trades:   {}", result.trades.len());
    println!("  Total Return:   {:.2}%", metrics.total_return_pct);
    println!("  Max Drawdown:   {:.2}%", metrics.max_drawdown_pct);
    println!("  Final Balance:  ${:.2}", result.final_state.final_balance);
    println!("  Final Equity:   ${:.2}", result.final_state.final_equity);
    println!(
        "  Open Positions: {}",
        result.final_state.open_positions_remaining
    );
    println!("════════════════════════════════════════");
}

struct MetricsReportView {
    total_return_pct: f64,
    max_drawdown_pct: f64,
}

/// Builds the event JSON stream presented to the replay UI. This is
/// presentation only — the economics come entirely from the Engine result.
fn build_ui_events(
    result: &observa_engine::engine::RunResult,
    bars: &[Bar],
    metrics_report: &serde_json::Value,
) -> Vec<String> {
    let mut events: Vec<String> = Vec::new();
    let run_id = result.run_id;

    for (i, bar_rec) in result.bars.iter().enumerate() {
        let b = &bars[i];
        let bar_json = serde_json::json!({
            "event_type": "BarReceived",
            "timestamp":  bar_rec.timestamp,
            "open":       b.open,
            "high":       b.high,
            "low":        b.low,
            "close":      b.close,
            "volume":     b.volume,
            "ema_fast":   null,
            "ema_slow":   null,
        });
        events.push(bar_json.to_string());

        for fill in result.fills.iter().filter(|f| f.bar_index == i) {
            match fill.reason {
                observa_engine::engine::FillReason::MarketClose
                | observa_engine::engine::FillReason::StopLoss
                | observa_engine::engine::FillReason::TakeProfit => {}
                _ => {
                    if let Some(pid) = fill.position_id {
                        let opened = serde_json::json!({
                            "event_type": "PositionOpened",
                            "event_id": Uuid::new_v4().to_string(),
                            "run_id": run_id.to_string(),
                            "timestamp": bar_rec.timestamp,
                            "position_id": pid.to_string(),
                            "direction": format!("{:?}", fill.side),
                            "size": fill.quantity_lots,
                            "entry_price": fill.executed_price,
                            "sl": null,
                            "tp": null,
                            "pnl": 0.0,
                        });
                        events.push(opened.to_string());
                    }
                }
            }
        }

        for trade in result.trades.iter().filter(|t| t.bar_index == i) {
            let reason = match trade.exit_reason {
                ExitReason::TakeProfit => "Take Profit",
                ExitReason::StopLoss => "Stop Loss",
                ExitReason::Signal => "Signal",
            };
            let closed = serde_json::json!({
                "event_type": "PositionClosed",
                "event_id": Uuid::new_v4().to_string(),
                "run_id": run_id.to_string(),
                "timestamp": bar_rec.timestamp,
                "position_id": trade.position_id.to_string(),
                "direction": format!("{:?}", trade.direction),
                "size": trade.quantity_lots,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "exit_reason": reason,
                "pnl": trade.net_realized_pnl,
            });
            events.push(closed.to_string());
        }

        let snap = &bar_rec.snapshot;
        let snapshot = serde_json::json!({
            "event_type": "PortfolioSnapshot",
            "event_id": Uuid::new_v4().to_string(),
            "run_id": run_id.to_string(),
            "timestamp": snap.timestamp,
            "balance": snap.balance,
            "equity": snap.equity,
            "margin": snap.used_margin,
            "free_margin": snap.free_margin,
            "unrealised_pnl": snap.unrealised_pnl,
            "realised_pnl": snap.realised_pnl,
            "open_positions": snap.open_positions.len(),
        });
        events.push(snapshot.to_string());

        if !bar_rec.drawings.is_empty() {
            let drawing_json = serde_json::json!({
                "event_type": "DrawingsEmitted",
                "event_id": Uuid::new_v4().to_string(),
                "run_id": run_id.to_string(),
                "timestamp": bar_rec.timestamp,
                "bar_timestamp": bar_rec.timestamp,
                "drawings": bar_rec.drawings,
            });
            events.push(drawing_json.to_string());
        }
    }

    events.push(metrics_report.to_string());
    events
}

// ────────────────────────────────────────────────
// HTTP server (unchanged presentation layer)
// ────────────────────────────────────────────────

fn serve(events: Vec<String>, port: u16) {
    let events_json = Arc::new(format!("[{}]", events.join(",")));
    let addr = format!("0.0.0.0:{}", port);
    let server = Server::http(&addr).expect("Failed to start server");

    println!();
    println!("  Open http://localhost:{} in your browser", port);
    println!("  Press Ctrl+C to stop");
    println!();

    for request in server.incoming_requests() {
        let url = request.url().to_string();
        let events_json = events_json.clone();

        thread::spawn(move || match url.as_str() {
            "/" => {
                let html = include_str!("../../../frontend/index.html");
                let response = Response::from_string(html).with_header(
                    Header::from_bytes("Content-Type", "text/html; charset=utf-8").unwrap(),
                );
                request.respond(response).ok();
            }
            "/api/events" => {
                let response = Response::from_string((*events_json).clone())
                    .with_header(Header::from_bytes("Content-Type", "application/json").unwrap())
                    .with_header(Header::from_bytes("Access-Control-Allow-Origin", "*").unwrap());
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
                            .with_header(Header::from_bytes("Content-Type", content_type).unwrap());
                        request.respond(response).ok();
                    }
                    Err(_) => {
                        request
                            .respond(Response::from_string("Not found").with_status_code(404))
                            .ok();
                    }
                }
            }
            _ => {
                request
                    .respond(Response::from_string("Not found").with_status_code(404))
                    .ok();
            }
        });
    }
}

// ────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = std::env::args().collect();

    // Handle "observa init" before full argument parsing.
    if args.len() > 1 && args[1] == "init" {
        let content = config::generate_default_config();
        std::fs::write("config.yaml", content).expect("Failed to write config.yaml");
        println!("Created config.yaml — edit it to match your setup.");
        std::process::exit(0);
    }

    let args = match CliArgs::parse() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("Error: {}", e);
            std::process::exit(1);
        }
    };

    println!("╔══════════════════════════════════════╗");
    println!("║         OBSERVA v0.1                 ║");
    println!("╚══════════════════════════════════════╝");
    println!();

    // ── Detect or use provided class name ──
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
                    eprintln!("  Tip: use --class <ClassName> to specify manually");
                    std::process::exit(1);
                }
            }
        }
    };

    // ── Load Python strategy ──
    println!("  Loading strategy: {}", args.strategy_file.display());
    let mut strategy = match PyStrategy::load(&args.strategy_file, &class_name) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("  Failed to load strategy: {}", e);
            std::process::exit(1);
        }
    };

    // ── Load market data ──
    println!("  Loading data: {}", args.data_file.display());
    let bars = match CsvReader::load(&args.data_file) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("  Failed to load data: {}", e);
            std::process::exit(1);
        }
    };
    println!("  Loaded {} bars", bars.len());

    // ── Load configuration and resolve into the canonical model ──
    let config_path = args
        .config_file
        .unwrap_or_else(|| PathBuf::from("config.yaml"));
    let legacy = load_config(&config_path);

    println!("  Spread:     {}", legacy.execution.spread);
    println!("  Slippage:   {}", legacy.execution.slippage);
    println!("  Commission: ${}", legacy.execution.commission);
    println!("  Balance:    ${}", legacy.account.initial_balance);
    println!();

    let config = match build_canonical_config(&legacy, &args.strategy_file, &class_name, &bars) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("  Invalid configuration: {}", e);
            std::process::exit(1);
        }
    };

    // ── Invoke the canonical Engine ──
    println!("  Running backtest...");
    let mut engine = match Engine::new(config) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("  Failed to construct engine: {}", e);
            std::process::exit(1);
        }
    };

    let dataset_source = args.data_file.display().to_string();
    let result = match engine.run(&bars, &mut strategy) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("  Backtest failed: {}", e);
            if let Some(out) = &args.output {
                // Failure artifacts from the Engine's retained partial event
                // history (metrics.json is intentionally not produced).
                match persistence::persist_failed_run(
                    out,
                    engine.config(),
                    &bars,
                    engine.events(),
                    &e.to_string(),
                    &dataset_source,
                ) {
                    Ok(dir) => {
                        println!();
                        println!("  Failure artifacts persisted:");
                        println!("    {}", dir.join("run.json").display());
                        println!("    {}", dir.join("events.jsonl").display());
                    }
                    Err(pe) => eprintln!("  Failed to persist failure artifacts: {}", pe),
                }
            }
            std::process::exit(1);
        }
    };

    // ── Optional artifact persistence (create-only; thin passthrough) ──
    if let Some(out) = &args.output {
        match persistence::persist_completed_run(
            out,
            engine.config(),
            &bars,
            &result.events,
            &result,
            4.0 * 24.0 * 252.0,
            &dataset_source,
        ) {
            Ok(dir) => {
                println!();
                println!("  Run artifacts persisted:");
                println!("    {}", dir.join("run.json").display());
                println!("    {}", dir.join("events.jsonl").display());
                println!("    {}", dir.join("metrics.json").display());
                print_run_artifact_summary(&result, &bars, engine.config());
            }
            Err(PersistenceError::OutputAlreadyExists { path }) => {
                eprintln!("  Refusing to overwrite existing run output: {path}");
                eprintln!("  Choose a different --output directory and re-run.");
                std::process::exit(1);
            }
            Err(e) => {
                eprintln!("  Failed to persist run artifacts: {}", e);
                std::process::exit(1);
            }
        }
    }

    // ── Derive presentation metrics from the canonical result ──
    let initial_balance = result
        .bars
        .first()
        .map(|b| b.snapshot.balance)
        .unwrap_or(legacy.account.initial_balance);
    let mut metrics = MetricsEngine::new(initial_balance, 4.0 * 24.0 * 252.0);
    for b in &result.bars {
        metrics.on_snapshot(b.snapshot.timestamp, b.snapshot.equity);
    }
    for trade in &result.trades {
        metrics.on_trade_closed(trade.net_realized_pnl);
    }
    let report = metrics.report();

    let metrics_view = MetricsReportView {
        total_return_pct: report.total_return_pct,
        max_drawdown_pct: report.max_drawdown_pct,
    };
    print_summary(&result, &metrics_view);

    let metrics_report = serde_json::json!({
        "event_type": "MetricsReport",
        "report": report,
    });

    // ── Serve the replay UI (presentation only) ──
    let ui_events = build_ui_events(&result, &bars, &metrics_report);
    serve(ui_events, args.port);
}
