//! Canonical-event → replay presentation (OBS-0010).
//!
//! The visual replay is a *view of canonical events*; it is never an economic
//! authority. This module builds the deterministic frontend payload from
//! canonical run inputs and provides a loader for persisted canonical
//! artifacts (`run.json` / `events.jsonl` / `metrics.json`).
//!
//! The adapter may rename/pre-group/annotate for display, but it never
//! calculates fills, chooses which position closed, computes P&L, or infers
//! SL/TP outcomes — every economic fact it emits comes from the canonical
//! Engine event stream or the canonical `RunResult`.

use std::fs;
use std::path::Path;

use serde_json::{json, Value};
use thiserror::Error;

use observa_core::bar::Bar;
use observa_core::drawings::DrawingInstruction;

use crate::runevents::EngineEvent;

/// Run-level facts presented alongside the event stream (never recomputed).
#[derive(Debug, Clone, Default)]
pub struct RunMeta {
    pub status: String,
    pub total_bars: usize,
    pub final_balance: Option<f64>,
    pub final_equity: Option<f64>,
    pub open_positions: Option<usize>,
    pub error_category: Option<String>,
    pub error_message: Option<String>,
    pub instrument_symbol: Option<String>,
}

fn bar_to_json(b: &Bar) -> Value {
    json!({
        "time": b.timestamp.to_rfc3339(),
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    })
}

fn event_to_json(e: &EngineEvent) -> Value {
    serde_json::to_value(e)
        .unwrap_or_else(|_| json!({ "event_seq": e.event_seq, "type": "unserializable_event" }))
}

/// Builds the deterministic replay payload consumed by the frontend.
///
/// * `drawings_by_bar` is index-aligned with `bars` (each bar's Engine
///   recorded drawings, or empty).
/// * `metrics` is the canonical derived metrics object (may be `None` for
///   failed runs).
pub fn replay_payload(
    bars: &[Bar],
    events: &[EngineEvent],
    drawings_by_bar: &[Vec<DrawingInstruction>],
    run: &RunMeta,
    metrics: Option<&Value>,
) -> Value {
    let bar_values: Vec<Value> = bars.iter().map(bar_to_json).collect();
    let event_values: Vec<Value> = events.iter().map(event_to_json).collect();
    let drawings: Vec<Value> = drawings_by_bar
        .iter()
        .map(|d| serde_json::to_value(d).unwrap_or(Value::Array(Vec::new())))
        .collect();

    json!({
        "schema_version": 1,
        "run": {
            "status": run.status,
            "total_bars": run.total_bars,
            "final_balance": run.final_balance,
            "final_equity": run.final_equity,
            "open_positions": run.open_positions,
            "error_category": run.error_category,
            "error_message": run.error_message,
            "symbol": run.instrument_symbol,
        },
        "bars": bar_values,
        "events": event_values,
        "drawings": drawings,
        "metrics": metrics,
    })
}

// ────────────────────────────────────────────────
// Persisted-run loading
// ────────────────────────────────────────────────

/// Errors produced while loading a persisted canonical run for replay.
#[derive(Debug, Error)]
pub enum ReplayLoadError {
    #[error("cannot open persisted run at {path}: {message}")]
    MissingArtifact { path: String, message: String },

    #[error("invalid run.json at {path}: {message}")]
    InvalidRunJson { path: String, message: String },

    #[error("invalid events.jsonl at {path} (line {line}): {message}")]
    InvalidEventLine {
        path: String,
        line: usize,
        message: String,
    },
}

/// A persisted canonical run loaded for replay.
#[derive(Debug)]
pub struct LoadedPersistedRun {
    pub run_json: Value,
    pub events: Vec<EngineEvent>,
    pub metrics: Option<Value>,
}

/// Loads `run.json` + `events.jsonl` (+ optional `metrics.json`) from a run
/// directory. Canonical OHLC bars are not part of the OBS-0008 artifacts, so
/// they are intentionally not fabricated here; the caller decides whether the
/// dataset can be recovered from `dataset.source`.
pub fn load_persisted_run(dir: &Path) -> Result<LoadedPersistedRun, ReplayLoadError> {
    let run_path = dir.join("run.json");
    let run_bytes = fs::read(&run_path).map_err(|e| ReplayLoadError::MissingArtifact {
        path: run_path.display().to_string(),
        message: e.to_string(),
    })?;
    let run_json: Value =
        serde_json::from_slice(&run_bytes).map_err(|e| ReplayLoadError::InvalidRunJson {
            path: run_path.display().to_string(),
            message: e.to_string(),
        })?;

    let events_path = dir.join("events.jsonl");
    let raw = fs::read_to_string(&events_path).map_err(|e| ReplayLoadError::MissingArtifact {
        path: events_path.display().to_string(),
        message: e.to_string(),
    })?;

    let mut events = Vec::new();
    for (i, line) in raw.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let ev: EngineEvent =
            serde_json::from_str(line).map_err(|e| ReplayLoadError::InvalidEventLine {
                path: events_path.display().to_string(),
                line: i + 1,
                message: e.to_string(),
            })?;
        events.push(ev);
    }

    // metrics.json is optional (failed runs intentionally have none).
    let metrics_path = dir.join("metrics.json");
    let metrics =
        match fs::read_to_string(&metrics_path) {
            Ok(text) if !text.trim().is_empty() => Some(serde_json::from_str(&text).map_err(
                |e| ReplayLoadError::InvalidRunJson {
                    path: metrics_path.display().to_string(),
                    message: e.to_string(),
                },
            )?),
            _ => None,
        };

    Ok(LoadedPersistedRun {
        run_json,
        events,
        metrics,
    })
}

/// Run metadata extracted from a persisted `run.json` (never recomputed).
pub fn run_meta_from_run_json(run_json: &Value) -> RunMeta {
    RunMeta {
        status: run_json
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
        total_bars: run_json
            .get("dataset")
            .and_then(|d| d.get("bar_count"))
            .and_then(Value::as_u64)
            .unwrap_or(0) as usize,
        final_balance: run_json.get("final_balance").and_then(Value::as_f64),
        final_equity: run_json.get("final_equity").and_then(Value::as_f64),
        open_positions: run_json
            .get("open_positions_remaining")
            .and_then(Value::as_u64)
            .map(|v| v as usize),
        error_category: run_json
            .get("error")
            .and_then(Value::as_str)
            .map(|_| "run_failed".to_string()),
        error_message: run_json
            .get("error")
            .and_then(Value::as_str)
            .map(String::from),
        instrument_symbol: run_json
            .get("config")
            .and_then(|c| c.get("instrument"))
            .and_then(|i| i.get("symbol"))
            .and_then(Value::as_str)
            .map(String::from),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::io::Write;

    use chrono::{TimeZone, Utc};
    use observa_core::config::{
        AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode,
        DatasetConfig, ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig,
        OrderModelConfig, StrategyConfig,
    };
    use observa_core::types::{Direction, OrderKind};

    use crate::engine::Engine;
    use crate::persistence;
    use crate::strategy::{PortfolioView, Strategy, StrategySignal};

    fn ts(i: i64) -> chrono::DateTime<Utc> {
        Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
    }

    fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
        Bar::new(ts(i), o, h, l, c, None)
    }

    fn config() -> BacktestConfig {
        BacktestConfig {
            version: 1,
            account: AccountConfig {
                starting_balance: 10_000.0,
                currency: "USD".to_string(),
                leverage: 100.0,
            },
            instrument: InstrumentConfig {
                symbol: "EURUSD".to_string(),
                base_currency: "EUR".to_string(),
                quote_currency: "USD".to_string(),
                contract_size: 100_000.0,
                min_quantity: 0.01,
                max_quantity: 100.0,
                quantity_step: 0.01,
                ..Default::default()
            },
            execution: CoreExecutionConfig {
                fill_mode: FillMode::BarClose,
                spread: 0.0,
                slippage: 0.0,
                commission: CommissionConfig {
                    mode: CommissionMode::PerSide,
                    flat_per_fill: 0.0,
                    rate_per_unit: 0.0,
                },
                order_model: OrderModelConfig::default(),
            },
            dataset: Some(DatasetConfig {
                source: "test.csv".to_string(),
                hash: None,
                interval: BarInterval::Minute(15),
                start: None,
                end: None,
                bar_count: None,
            }),
            strategy: Some(StrategyConfig {
                name: "TestStrategy".to_string(),
                source: None,
                source_hash: None,
                parameters: BTreeMap::new(),
            }),
        }
    }

    struct BuyOnce {
        sent: bool,
    }
    impl Strategy for BuyOnce {
        fn on_bar(
            &mut self,
            bar: &Bar,
            _view: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![StrategySignal {
                    direction: Direction::Buy,
                    order_type: OrderKind::Market,
                    size: 1.0,
                    intended_price: bar.close,
                    sl: None,
                    tp: None,
                    reason: "buy".to_string(),
                    ticket: None,
                }];
            }
            vec![]
        }
    }

    fn run_fixture() -> (Vec<Bar>, crate::engine::RunResult, BacktestConfig) {
        let bars = vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)];
        let mut engine = Engine::new(config()).unwrap();
        let mut s = BuyOnce { sent: false };
        let result = engine.run(&bars, &mut s).unwrap();
        (bars, result, config())
    }

    #[test]
    fn payload_preserves_all_events_in_order() {
        let (bars, result, _cfg) = run_fixture();
        let drawings: Vec<Vec<DrawingInstruction>> =
            result.bars.iter().map(|b| b.drawings.clone()).collect();
        let meta = RunMeta {
            status: "completed".to_string(),
            total_bars: result.total_bars,
            final_balance: Some(result.final_state.final_balance),
            final_equity: Some(result.final_state.final_equity),
            open_positions: Some(result.final_state.open_positions_remaining),
            ..Default::default()
        };
        let payload = replay_payload(&bars, &result.events, &drawings, &meta, None);

        let evs = payload["events"].as_array().unwrap();
        assert_eq!(evs.len(), result.events.len(), "no event loss");
        assert_eq!(payload["bars"].as_array().unwrap().len(), bars.len());
        for (i, ev) in evs.iter().enumerate() {
            assert_eq!(
                ev["event_seq"].as_u64().unwrap() as usize,
                i,
                "order preserved"
            );
        }
        assert_eq!(payload["run"]["status"], "completed");
        assert_eq!(
            payload["run"]["final_equity"],
            json!(result.final_state.final_equity)
        );
    }

    #[test]
    fn load_persisted_run_round_trips() {
        let (bars, result, config) = run_fixture();
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("run");
        persistence::persist_completed_run(
            &dir,
            &config,
            &bars,
            &result.events,
            &result,
            24.0 * 252.0,
            "test.csv",
        )
        .unwrap();

        let loaded = load_persisted_run(&dir).unwrap();
        assert_eq!(loaded.events.len(), result.events.len());
        for (a, b) in loaded.events.iter().zip(result.events.iter()) {
            assert_eq!(a.event_seq, b.event_seq);
            assert_eq!(
                serde_json::to_value(a).unwrap(),
                serde_json::to_value(b).unwrap(),
                "persisted events must round-trip identically"
            );
        }
        assert!(loaded.metrics.is_some());
        let meta = run_meta_from_run_json(&loaded.run_json);
        assert_eq!(meta.status, "completed");
        assert_eq!(meta.total_bars, bars.len());
    }

    #[test]
    fn load_failed_run_has_no_metrics_and_reports_error() {
        let bars = vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)];
        let mut engine = Engine::new(config()).unwrap();

        struct Failing;
        impl Strategy for Failing {
            fn on_bar(
                &mut self,
                _bar: &Bar,
                _view: &PortfolioView,
                _history: &[Bar],
            ) -> Vec<StrategySignal> {
                vec![]
            }
            fn take_strategy_error(&mut self) -> Option<String> {
                Some("scripted failure".to_string())
            }
        }
        let mut s = Failing;
        let err = engine.run(&bars, &mut s).unwrap_err();

        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("failed");
        persistence::persist_failed_run(
            &dir,
            &config(),
            &bars,
            engine.events(),
            &err.to_string(),
            "test.csv",
        )
        .unwrap();

        let loaded = load_persisted_run(&dir).unwrap();
        assert!(loaded.metrics.is_none());
        assert!(!loaded.events.is_empty());
        let last = loaded.events.last().unwrap();
        assert_eq!(
            serde_json::to_value(&last.payload).unwrap()["type"],
            "run_failed"
        );
        let meta = run_meta_from_run_json(&loaded.run_json);
        assert_eq!(meta.status, "failed");
        assert!(meta.error_message.is_some());
    }

    #[test]
    fn malformed_event_line_is_a_structured_error() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path();
        fs::write(dir.join("run.json"), r#"{"status":"completed"}"#).unwrap();
        let mut f = fs::File::create(dir.join("events.jsonl")).unwrap();
        writeln!(f, "not json").unwrap();
        let err = load_persisted_run(dir).unwrap_err();
        assert!(matches!(err, ReplayLoadError::InvalidEventLine { .. }));
    }
}
