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