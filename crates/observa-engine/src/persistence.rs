//! Run artifact persistence (OBS-0008).
//!
//! Persists the canonical artifacts of a run:
//!
//! * `run.json` — resolved configuration and reproducibility metadata;
//! * `events.jsonl` — the canonical Engine event history, one event per line;
//! * `metrics.json` — derived metrics (never a financial authority).
//!
//! The writer is **create-only**: it refuses to overwrite an existing output
//! directory, writes all artifacts, and on any write failure removes the
//! partially-written directory so partial output can never masquerade as a
//! completed run.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{json, Value};
use thiserror::Error;

use observa_core::bar::Bar;
use observa_core::config::BacktestConfig;
use observa_metrics::metrics::{MetricsEngine, MetricsReport};

use crate::engine::RunResult;
use crate::runevents::{EngineEvent, METRICS_SCHEMA_VERSION, RUN_SCHEMA_VERSION};
use crate::sha256::Sha256;

/// Errors produced by run persistence.
#[derive(Debug, Error)]
pub enum PersistenceError {
    /// The requested output directory already exists (no silent overwrite).
    #[error("output directory already exists: {path}")]
    OutputAlreadyExists { path: String },

    /// The output directory is not a usable path.
    #[error("invalid output path {path}: {reason}")]
    InvalidOutputPath { path: String, reason: String },

    /// An IO error occurred while writing artifacts.
    #[error("io error while persisting run: {0}")]
    Io(#[from] std::io::Error),

    /// Serialization of a persisted value failed.
    #[error("serialization error: {0}")]
    Serialization(String),

    /// No bars were available to derive dataset identity.
    #[error("cannot derive dataset identity without bars")]
    NoBars,
}

/// Metadata identifying the dataset that produced a run.
#[derive(Debug, Clone, Serialize)]
pub struct DatasetIdentity {
    /// Deterministic SHA-256 over the canonical dataset representation.
    pub sha256: String,
    pub bar_count: usize,
    pub first_timestamp: Option<DateTime<Utc>>,
    pub last_timestamp: Option<DateTime<Utc>>,
}

/// Deterministic SHA-256 of the canonical dataset representation (timestamps
/// as RFC 3339, prices/volume as their IEEE-754 little-endian bits).
pub fn dataset_identity(bars: &[Bar]) -> Result<DatasetIdentity, PersistenceError> {
    if bars.is_empty() {
        return Err(PersistenceError::NoBars);
    }
    let mut h = Sha256::new();
    for b in bars {
        h.update(b.timestamp.to_rfc3339().as_bytes());
        h.update(&[0u8]); // field separator
        for price in [b.open, b.high, b.low, b.close] {
            h.update(&price.to_le_bytes());
        }
        h.update(&[0u8]);
        match b.volume {
            Some(v) => {
                h.update(&[1u8]);
                h.update(&v.to_le_bytes());
            }
            None => h.update(&[0u8]),
        }
        h.update(&[0x1f]); // record separator
    }
    Ok(DatasetIdentity {
        sha256: hex(&h.finalize()),
        bar_count: bars.len(),
        first_timestamp: bars.first().map(|b| b.timestamp),
        last_timestamp: bars.last().map(|b| b.timestamp),
    })
}

/// Deterministic SHA-256 of a strategy identity.
///
/// If a source file path is available and readable, the file's bytes are
/// hashed; otherwise the canonical serialized name+parameters are hashed.
pub fn strategy_identity(config: &BacktestConfig) -> Result<String, PersistenceError> {
    let strategy = config
        .strategy
        .as_ref()
        .ok_or_else(|| PersistenceError::Serialization("missing strategy metadata".into()))?;
    if let Some(src) = &strategy.source {
        if let Ok(bytes) = fs::read(src) {
            let mut h = Sha256::new();
            h.update(&bytes);
            return Ok(hex(&h.finalize()));
        }
    }
    // Fall back to canonical name + sorted parameters.
    let params = serde_json::to_string(&strategy.parameters)
        .map_err(|e| PersistenceError::Serialization(e.to_string()))?;
    let payload = format!("{}|{}", strategy.name, params);
    Ok(Sha256::hex(payload.as_bytes()))
}

/// Serializes a value to pretty JSON bytes (used for run.json/metrics.json).
fn to_json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, PersistenceError> {
    let mut bytes = serde_json::to_vec_pretty(value)
        .map_err(|e| PersistenceError::Serialization(e.to_string()))?;
    bytes.push(b'\n');
    Ok(bytes)
}

/// Serializes one event to a single JSON line (no trailing newline added by
/// this function; the writer appends it).
fn event_line(event: &EngineEvent) -> Result<String, PersistenceError> {
    serde_json::to_string(event).map_err(|e| PersistenceError::Serialization(e.to_string()))
}

/// Derives the canonical metrics report from a `RunResult` (metrics consume
/// canonical run data; they are never a financial authority).
fn derive_metrics(result: &RunResult, bars_per_year: f64) -> MetricsReport {
    let initial = result
        .bars
        .first()
        .map(|b| b.snapshot.balance)
        .unwrap_or(0.0);
    let mut m = MetricsEngine::new(initial, bars_per_year);
    for b in &result.bars {
        m.on_snapshot(b.snapshot.timestamp, b.snapshot.equity);
    }
    for trade in &result.trades {
        m.on_trade_closed(trade.net_realized_pnl);
    }
    m.report()
}

/// Serializes a `MetricsReport` to JSON, mapping any non-finite value to
/// `null` (e.g. profit factor when there are no losing trades) instead of
/// emitting invalid JSON or inventing zero.
fn metrics_json(result: &RunResult, bars_per_year: f64) -> Result<Value, PersistenceError> {
    let report = derive_metrics(result, bars_per_year);
    let num = |v: f64| -> Value {
        if v.is_finite() {
            json!(v)
        } else {
            Value::Null
        }
    };
    let val = json!({
        "metrics_schema_version": METRICS_SCHEMA_VERSION,
        "total_return_pct": num(report.total_return_pct),
        "annualised_return_pct": num(report.annualised_return_pct),
        "max_drawdown_pct": num(report.max_drawdown_pct),
        "max_drawdown_start": report.max_drawdown_start,
        "max_drawdown_end": report.max_drawdown_end,
        "current_drawdown_pct": num(report.current_drawdown_pct),
        "sharpe_ratio": report.sharpe_ratio,
        "calmar_ratio": report.calmar_ratio,
        "total_trades": report.total_trades,
        "winning_trades": report.winning_trades,
        "losing_trades": report.losing_trades,
        "win_rate_pct": num(report.win_rate_pct),
        "avg_win": num(report.avg_win),
        "avg_loss": num(report.avg_loss),
        "profit_factor": if report.profit_factor.is_finite() {
            json!(report.profit_factor)
        } else {
            Value::Null
        },
        "expectancy": num(report.expectancy),
        "largest_win": num(report.largest_win),
        "largest_loss": num(report.largest_loss),
        "final_balance": result.final_state.final_balance,
        "final_equity": result.final_state.final_equity,
        "open_positions_remaining": result.final_state.open_positions_remaining,
    });
    Ok(val)
}

/// Writes the canonical artifacts of a completed run into `output_dir`
/// (which must not already exist).
///
/// Returns the path of the created directory.
pub fn persist_completed_run(
    output_dir: &Path,
    config: &BacktestConfig,
    bars: &[Bar],
    events: &[EngineEvent],
    result: &RunResult,
    bars_per_year: f64,
    dataset_source: &str,
) -> Result<PathBuf, PersistenceError> {
    let dir = create_output_dir(output_dir)?;

    let dataset = dataset_identity(bars)?;
    let strategy_sha = strategy_identity(config)?;
    let metrics = metrics_json(result, bars_per_year)?;

    let run_json = json!({
        "run_schema_version": RUN_SCHEMA_VERSION,
        "config_version": config.version,
        "dataset": {
            "source": dataset_source,
            "sha256": dataset.sha256,
            "bar_count": dataset.bar_count,
            "first_timestamp": dataset.first_timestamp,
            "last_timestamp": dataset.last_timestamp,
        },
        "strategy": {
            "name": config.strategy.as_ref().map(|s| s.name.clone()),
            "source": config.strategy.as_ref().and_then(|s| s.source.clone()),
            "params_sha256": strategy_sha,
        },
        "config": config,
        "event_count": events.len(),
        "status": "completed",
        "final_balance": result.final_state.final_balance,
        "final_equity": result.final_state.final_equity,
        "open_positions_remaining": result.final_state.open_positions_remaining,
        "used_margin": result.final_state.used_margin,
        "free_margin": result.final_state.free_margin,
    });

    write_all(&dir, run_json, metrics, events)
}

/// Writes canonical failure artifacts (run.json status=failed + events.jsonl)
/// when a run fails after it started. `metrics.json` is intentionally not
/// produced for failed runs.
pub fn persist_failed_run(
    output_dir: &Path,
    config: &BacktestConfig,
    bars: &[Bar],
    events: &[EngineEvent],
    error_message: &str,
    dataset_source: &str,
) -> Result<PathBuf, PersistenceError> {
    let dir = create_output_dir(output_dir)?;
    let dataset = dataset_identity(bars)?;
    let strategy_sha = strategy_identity(config)?;

    let run_json = json!({
        "run_schema_version": RUN_SCHEMA_VERSION,
        "config_version": config.version,
        "dataset": {
            "source": dataset_source,
            "sha256": dataset.sha256,
            "bar_count": dataset.bar_count,
            "first_timestamp": dataset.first_timestamp,
            "last_timestamp": dataset.last_timestamp,
        },
        "strategy": {
            "name": config.strategy.as_ref().map(|s| s.name.clone()),
            "source": config.strategy.as_ref().and_then(|s| s.source.clone()),
            "params_sha256": strategy_sha,
        },
        "config": config,
        "event_count": events.len(),
        "status": "failed",
        "error": error_message,
    });
    write_all(&dir, run_json, Value::Null, events)
}

fn create_output_dir(output_dir: &Path) -> Result<PathBuf, PersistenceError> {
    if output_dir.exists() {
        return Err(PersistenceError::OutputAlreadyExists {
            path: output_dir.display().to_string(),
        });
    }
    match fs::create_dir(output_dir) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            return Err(PersistenceError::OutputAlreadyExists {
                path: output_dir.display().to_string(),
            })
        }
        Err(e) if output_dir.parent().is_none() => {
            return Err(PersistenceError::InvalidOutputPath {
                path: output_dir.display().to_string(),
                reason: e.to_string(),
            })
        }
        Err(e) => return Err(PersistenceError::Io(e)),
    }
    Ok(output_dir.to_path_buf())
}

/// Writes the three artifacts; on any failure removes the directory so partial
/// output is never presented as a completed run.
fn write_all(
    dir: &Path,
    run_json: Value,
    metrics: Value,
    events: &[EngineEvent],
) -> Result<PathBuf, PersistenceError> {
    let result = (|| -> Result<(), PersistenceError> {
        let run_bytes = to_json_bytes(&run_json)?;
        fs::write(dir.join("run.json"), run_bytes)?;

        let mut events_out = fs::File::create(dir.join("events.jsonl"))?;
        for event in events {
            let line = event_line(event)?;
            events_out.write_all(line.as_bytes())?;
            events_out.write_all(b"\n")?;
        }
        events_out.flush()?;

        if metrics != Value::Null {
            let metrics_bytes = to_json_bytes(&metrics)?;
            fs::write(dir.join("metrics.json"), metrics_bytes)?;
        }
        Ok(())
    })();

    match result {
        Ok(()) => Ok(dir.to_path_buf()),
        Err(e) => {
            let _ = fs::remove_dir_all(dir); // best-effort cleanup
            Err(e)
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    crate::sha256::hex_bytes(bytes)
}
