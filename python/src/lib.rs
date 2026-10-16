//! Observa Python extension (`observa._observa`).
//!
//! This is the thin, canonical binding: Python strategies are wrapped in a
//! Rust [`PyStrategy`] that implements the Engine's `Strategy` trait, so there
//! is exactly one backtesting loop — the canonical [`Engine`]. No execution,
//! portfolio, or event logic is reimplemented here.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, RwLock};

use chrono::{DateTime, TimeZone, Utc};
use pyo3::exceptions::{
    PyFileExistsError, PyFileNotFoundError, PyIndexError, PyRuntimeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PySlice, PyString};
use serde_json::{json, Value};

use observa_core::bar::Bar;
use observa_core::drawings::{DrawingInstruction, DrawingRegistry};
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig, StrategyConfig,
};
use observa_core::types::{Direction, OrderKind};
use observa_data::csv_reader::CsvReader;
use observa_engine::engine::{Engine, RunResult as EngineRunResult};
use observa_engine::error::EngineError;
use observa_engine::persistence::{self, PersistenceError};
use observa_engine::replay::{self as replay_mod};
use observa_engine::runevents::RUN_SCHEMA_VERSION;
use observa_engine::strategy::{PortfolioView, Strategy, StrategyFailure, StrategySignal};
use observa_metrics::metrics::MetricsEngine;

// ────────────────────────────────────────────────
// Error mapping
// ────────────────────────────────────────────────

/// Attaches the stable machine-readable contract (`exc.code`, `exc.details`)
/// to an existing Python exception, preserving its class for compatibility.
fn coded(py: Python<'_>, err: PyErr, code: &str, details: Option<PyObject>) -> PyErr {
    let value = err.value_bound(py);
    let _ = value.setattr("code", code);
    let details_obj = details.unwrap_or_else(|| PyDict::new_bound(py).into_py(py));
    let _ = value.setattr("details", details_obj);
    err
}

/// Builds a `details` dict from known context only (never parsed from text).
fn details(py: Python<'_>, items: Vec<(&str, PyObject)>) -> PyObject {
    let d = PyDict::new_bound(py);
    for (k, v) in items {
        let _ = d.set_item(k, v);
    }
    d.into_py(py)
}

fn config_err(py: Python<'_>, e: impl std::fmt::Display) -> PyErr {
    coded(
        py,
        PyValueError::new_err(format!("invalid configuration: {e}")),
        "CONFIG_INVALID",
        None,
    )
}

fn data_err(py: Python<'_>, e: impl std::fmt::Display) -> PyErr {
    coded(
        py,
        PyValueError::new_err(format!("invalid data: {e}")),
        "DATA_INVALID",
        None,
    )
}

fn engine_err(py: Python<'_>, e: impl std::fmt::Display) -> PyErr {
    coded(
        py,
        PyRuntimeError::new_err(format!("engine error: {e}")),
        "ENGINE_ERROR",
        None,
    )
}

/// Maps an Engine strategy failure to a coded Python exception.
///
/// Drawing-validation failures (OBS-AI-02) carry their specific code
/// (`DRAWING_*`) and structured details; every other strategy failure keeps
/// the OBS-AI-01 default code `STRATEGY_ERROR`. The exception class stays
/// `RuntimeError` so existing handlers keep working.
fn strategy_err(
    py: Python<'_>,
    message: &str,
    bar_index: Option<usize>,
    code: Option<&str>,
    failure_details: Option<&Value>,
) -> PyErr {
    let dict = PyDict::new_bound(py);
    let _ = dict.set_item("message", message);
    if let Some(index) = bar_index {
        let _ = dict.set_item("bar_index", index);
    }
    if let Some(Value::Object(map)) = failure_details {
        for (k, v) in map {
            if let Ok(obj) = value_to_py(py, v) {
                let _ = dict.set_item(k, obj);
            }
        }
    }
    coded(
        py,
        PyRuntimeError::new_err(format!("engine error: strategy failure: {message}")),
        code.unwrap_or("STRATEGY_ERROR"),
        Some(dict.into_py(py)),
    )
}

fn map_persistence(py: Python<'_>, e: PersistenceError) -> PyErr {
    match e {
        PersistenceError::OutputAlreadyExists { path } => coded(
            py,
            PyFileExistsError::new_err(format!(
                "output directory already exists: {path} (Observa persistence is create-only)"
            )),
            "RUN_OUTPUT_EXISTS",
            Some(details(py, vec![("path", path.into_py(py))])),
        ),
        other => coded(
            py,
            PyRuntimeError::new_err(format!("persistence error: {other}")),
            "RUN_PERSIST_FAILED",
            None,
        ),
    }
}

// ────────────────────────────────────────────────
// Unknown-key detection (OBS-TRUST-01)
// ────────────────────────────────────────────────

/// Levenshtein distance, used only to suggest the intended key.
fn edit_distance(a: &str, b: &str) -> usize {
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for (i, ca) in a.chars().enumerate() {
        let mut cur = vec![i + 1; b.len() + 1];
        for (j, cb) in b.iter().enumerate() {
            let cost = usize::from(ca != *cb);
            cur[j + 1] = (prev[j] + cost).min(prev[j + 1] + 1).min(cur[j] + 1);
        }
        prev = cur;
    }
    prev[b.len()]
}

/// The closest allowed key within edit distance 2, if any.
fn closest_key(key: &str, allowed: &[&'static str]) -> Option<&'static str> {
    let k = key.to_ascii_lowercase();
    allowed
        .iter()
        .map(|a| (edit_distance(&k, a), *a))
        .filter(|(d, _)| *d <= 2)
        .min_by_key(|(d, _)| *d)
        .map(|(_, a)| a)
}

/// The eight canonical signal keys (the strategy contract, `spec.json`).
const SIGNAL_FIELDS: [&str; 8] = [
    "direction", "size", "order_type", "price", "sl", "tp", "reason", "ticket",
];

/// Common names for the canonical signal keys (e.g. the portfolio view's own
/// OUTPUT names `stop_loss` / `take_profit`, which are not signal INPUTS).
fn signal_suggestion(key: &str) -> Option<&'static str> {
    let k = key.to_ascii_lowercase();
    let alias = match k.as_str() {
        "stop_loss" | "stoploss" | "sl_price" | "stop_loss_price" | "stop_level" => Some("sl"),
        "take_profit" | "takeprofit" | "tp_price" | "take_profit_price" | "target" => Some("tp"),
        "quantity" | "qty" | "lots" | "lot" | "volume" | "amount" | "units" | "quantity_lots" => {
            Some("size")
        }
        "side" | "action" | "dir" => Some("direction"),
        "type" | "kind" | "ordertype" | "order" => Some("order_type"),
        "limit_price" | "stop_price" | "entry" | "entry_price" | "trigger" | "trigger_price"
        | "limit" => Some("price"),
        "position_id" | "position" | "pos_id" | "id" => Some("ticket"),
        "comment" | "note" | "tag" | "label" | "message" | "why" => Some("reason"),
        _ => None,
    };
    alias.or_else(|| closest_key(&k, &SIGNAL_FIELDS))
}

/// Every key the Python config dict may contain. `observa.Config` produces a
/// subset of these; anything else is a typo that would otherwise silently
/// fall back to a default (e.g. `spred` → the default spread).
const CONFIG_FIELDS: [&str; 26] = [
    "starting_balance", "currency", "leverage",
    "symbol", "base_currency", "quote_currency", "contract_size", "price_decimals",
    "tick_size", "pip_size", "min_quantity", "max_quantity", "quantity_step",
    "order_model", "fill_mode", "spread", "slippage",
    "commission", "commission_mode", "commission_rate_per_unit",
    "interval", "params", "strategy_params", "strategy_name", "strategy_source",
    "dataset_source",
];

const ORDER_MODEL_FIELDS: [&str; 3] = ["market", "limit", "stop"];

fn unknown_config_key(
    py: Python<'_>,
    field: String,
    suggestion: Option<String>,
    allowed: &[&str],
) -> PyErr {
    let hint = suggestion
        .as_ref()
        .map(|s| format!(" — did you mean '{s}'?"))
        .unwrap_or_default();
    coded(
        py,
        PyValueError::new_err(format!(
            "invalid configuration: unknown config field '{field}'{hint} \
             (an unknown field would otherwise be ignored and its default used)"
        )),
        "CONFIG_INVALID",
        Some(details(
            py,
            vec![
                ("field", field.into_py(py)),
                ("suggestion", suggestion.into_py(py)),
                ("allowed", allowed.to_vec().into_py(py)),
            ],
        )),
    )
}

/// Rejects config dict keys that the binding would otherwise silently ignore.
fn check_config_keys(py: Python<'_>, d: &Bound<'_, PyDict>) -> PyResult<()> {
    for (k, v) in d.iter() {
        let key: String = k.extract().map_err(|_| {
            config_err(py, "config keys must be strings")
        })?;
        if !CONFIG_FIELDS.contains(&key.as_str()) {
            let s = closest_key(&key, &CONFIG_FIELDS).map(str::to_string);
            return Err(unknown_config_key(py, key, s, &CONFIG_FIELDS));
        }
        if key == "order_model" {
            if let Ok(om) = v.downcast::<PyDict>() {
                for (ok, _) in om.iter() {
                    let okey: String = ok.extract().map_err(|_| {
                        config_err(py, "order_model keys must be strings")
                    })?;
                    if !ORDER_MODEL_FIELDS.contains(&okey.as_str()) {
                        let s = closest_key(&okey, &ORDER_MODEL_FIELDS)
                            .map(|s| format!("order_model.{s}"));
                        return Err(unknown_config_key(
                            py,
                            format!("order_model.{okey}"),
                            s,
                            &ORDER_MODEL_FIELDS,
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

// ────────────────────────────────────────────────
// Config parsing (Python dict -> canonical BacktestConfig)
// ────────────────────────────────────────────────

fn opt_f64(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<f64>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => Ok(Some(v.extract::<f64>().map_err(|e| {
            PyValueError::new_err(format!("config field '{key}' must be a number: {e}"))
        })?)),
        _ => Ok(None),
    }
}

fn opt_u32(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<u32>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => Ok(Some(v.extract::<u32>().map_err(|e| {
            PyValueError::new_err(format!("config field '{key}' must be an integer: {e}"))
        })?)),
        _ => Ok(None),
    }
}

fn opt_bool(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<bool>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => Ok(Some(v.extract::<bool>().map_err(|e| {
            PyValueError::new_err(format!("config field '{key}' must be a bool: {e}"))
        })?)),
        _ => Ok(None),
    }
}

fn opt_str(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<String>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => Ok(Some(v.extract::<String>().map_err(|e| {
            PyValueError::new_err(format!("config field '{key}' must be a string: {e}"))
        })?)),
        _ => Ok(None),
    }
}

fn parse_fill_mode(s: &str) -> PyResult<FillMode> {
    match s.to_lowercase().replace('-', "_").as_str() {
        "bar_close" | "barclose" => Ok(FillMode::BarClose),
        "next_bar_open" | "nextbaropen" | "next_bar" => Ok(FillMode::NextBarOpen),
        other => Err(PyValueError::new_err(format!(
            "unknown fill_mode '{other}' — use 'bar_close' or 'next_bar_open'"
        ))),
    }
}

fn parse_commission_mode(s: &str) -> PyResult<CommissionMode> {
    match s.to_lowercase().replace('-', "_").as_str() {
        "per_side" | "perside" => Ok(CommissionMode::PerSide),
        "round_trip" | "roundtrip" => Ok(CommissionMode::RoundTrip),
        other => Err(PyValueError::new_err(format!(
            "unknown commission_mode '{other}' — use 'per_side' or 'round_trip'"
        ))),
    }
}

fn parse_interval(s: &str) -> PyResult<BarInterval> {
    let s = s.to_lowercase();
    if s == "1d" || s == "day" || s == "d" {
        Ok(BarInterval::Day)
    } else if s == "1w" || s == "week" || s == "w" {
        Ok(BarInterval::Week)
    } else if s == "1h" || s == "hour" {
        Ok(BarInterval::Hour(1))
    } else if s == "4h" {
        Ok(BarInterval::Hour(4))
    } else if s == "1m" || s == "minute" {
        Ok(BarInterval::Minute(1))
    } else if let Some(n) = s.strip_suffix('m') {
        n.parse::<u32>()
            .map(BarInterval::Minute)
            .map_err(|_| PyValueError::new_err(format!("unknown interval '{s}'")))
    } else if let Some(n) = s.strip_suffix('h') {
        n.parse::<u32>()
            .map(BarInterval::Hour)
            .map_err(|_| PyValueError::new_err(format!("unknown interval '{s}'")))
    } else {
        Err(PyValueError::new_err(format!("unknown interval '{s}'")))
    }
}

/// Parses the Python config dict into a canonical (not yet resolved) config.
fn config_from_dict(d: &Bound<'_, PyDict>) -> PyResult<BacktestConfig> {
    let account = AccountConfig {
        starting_balance: opt_f64(d, "starting_balance")?.unwrap_or(10_000.0),
        currency: opt_str(d, "currency")?.unwrap_or_else(|| "USD".to_string()),
        leverage: opt_f64(d, "leverage")?.unwrap_or(100.0),
    };

    let instrument = InstrumentConfig {
        symbol: opt_str(d, "symbol")?.unwrap_or_else(|| "EURUSD".to_string()),
        base_currency: opt_str(d, "base_currency")?.unwrap_or_else(|| "EUR".to_string()),
        quote_currency: opt_str(d, "quote_currency")?.unwrap_or_else(|| "USD".to_string()),
        contract_size: opt_f64(d, "contract_size")?.unwrap_or(100_000.0),
        price_decimals: opt_u32(d, "price_decimals")?.unwrap_or(5),
        tick_size: opt_f64(d, "tick_size")?,
        pip_size: opt_f64(d, "pip_size")?,
        min_quantity: opt_f64(d, "min_quantity")?.unwrap_or(0.01),
        max_quantity: opt_f64(d, "max_quantity")?.unwrap_or(100.0),
        quantity_step: opt_f64(d, "quantity_step")?.unwrap_or(0.01),
    };

    let order_model = match d.get_item("order_model")? {
        Some(v) if !v.is_none() => {
            let om = v
                .downcast::<PyDict>()
                .map_err(|_| PyValueError::new_err("config field 'order_model' must be a dict"))?;
            OrderModelConfig {
                market: opt_bool(&om, "market")?.unwrap_or(true),
                limit: opt_bool(&om, "limit")?.unwrap_or(true),
                stop: opt_bool(&om, "stop")?.unwrap_or(true),
            }
        }
        _ => OrderModelConfig::default(),
    };

    let execution = ExecutionConfig {
        fill_mode: match opt_str(d, "fill_mode")? {
            Some(s) => parse_fill_mode(&s)?,
            None => FillMode::NextBarOpen,
        },
        spread: opt_f64(d, "spread")?.unwrap_or(0.0002),
        slippage: opt_f64(d, "slippage")?.unwrap_or(0.0001),
        commission: CommissionConfig {
            mode: match opt_str(d, "commission_mode")? {
                Some(s) => parse_commission_mode(&s)?,
                None => CommissionMode::PerSide,
            },
            flat_per_fill: opt_f64(d, "commission")?.unwrap_or(0.0),
            rate_per_unit: opt_f64(d, "commission_rate_per_unit")?.unwrap_or(0.0),
        },
        order_model,
    };

    Ok(BacktestConfig {
        version: observa_core::config::CONFIG_VERSION,
        account,
        instrument,
        execution,
        dataset: None,
        strategy: None,
    })
}

/// Extracts strategy parameters from a Python dict into a deterministic map.
fn params_from_dict(d: &Bound<'_, PyDict>) -> PyResult<BTreeMap<String, Value>> {
    let mut params = BTreeMap::new();
    let key = if d.contains("params")? {
        "params"
    } else if d.contains("strategy_params")? {
        "strategy_params"
    } else {
        return Ok(params);
    };
    if let Some(v) = d.get_item(key)? {
        if !v.is_none() {
            let pd = v.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(format!("config field '{key}' must be a dict"))
            })?;
            for (k, val) in pd.iter() {
                let k: String = k.extract()?;
                params.insert(k, value_from_py(&val)?);
            }
        }
    }
    Ok(params)
}

// ────────────────────────────────────────────────
// serde_json <-> Python conversion
// ────────────────────────────────────────────────

fn value_to_py(py: Python<'_>, value: &Value) -> PyResult<PyObject> {
    match value {
        Value::Null => Ok(py.None()),
        Value::Bool(b) => Ok(b.into_py(py)),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_py(py))
            } else if let Some(u) = n.as_u64() {
                Ok(u.into_py(py))
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_py(py))
            } else {
                Err(PyValueError::new_err("unrepresentable JSON number"))
            }
        }
        Value::String(s) => Ok(s.into_py(py)),
        Value::Array(items) => {
            let list = PyList::empty_bound(py);
            for item in items {
                list.append(value_to_py(py, item)?)?;
            }
            Ok(list.into_py(py))
        }
        Value::Object(map) => {
            let dict = PyDict::new_bound(py);
            for (k, v) in map {
                dict.set_item(k, value_to_py(py, v)?)?;
            }
            Ok(dict.into_py(py))
        }
    }
}

fn value_from_py(obj: &Bound<'_, pyo3::PyAny>) -> PyResult<Value> {
    if obj.is_none() {
        Ok(Value::Null)
    } else if let Ok(b) = obj.extract::<bool>() {
        Ok(Value::Bool(b))
    } else if let Ok(i) = obj.extract::<i64>() {
        Ok(Value::Number(i.into()))
    } else if let Ok(f) = obj.extract::<f64>() {
        serde_json::Number::from_f64(f)
            .map(Value::Number)
            .ok_or_else(|| PyValueError::new_err("non-finite parameter value"))
    } else if let Ok(s) = obj.extract::<String>() {
        Ok(Value::String(s))
    } else if let Ok(list) = obj.downcast::<PyList>() {
        let mut items = Vec::new();
        for item in list.iter() {
            items.push(value_from_py(&item)?);
        }
        Ok(Value::Array(items))
    } else if let Ok(dict) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k, v) in dict.iter() {
            let k: String = k.extract()?;
            map.insert(k, value_from_py(&v)?);
        }
        Ok(Value::Object(map))
    } else {
        Err(PyValueError::new_err("unsupported parameter value type"))
    }
}

// ────────────────────────────────────────────────
// Bar loading
// ────────────────────────────────────────────────

/// Largest magnitude accepted as epoch *seconds* (≈ year 5138). Anything
/// larger is almost certainly milliseconds/microseconds and used to be read
/// as seconds silently (OBS-TRUST-02).
const MAX_EPOCH_SECONDS: f64 = 1e11;

/// Parses an RFC 3339 timestamp that carries an explicit offset (`Z` or
/// `±HH:MM`). A space separator (`2024-01-01 00:00:00+00:00`, the CSV form) is
/// accepted. Timezone-less strings are rejected rather than assumed to be UTC.
fn parse_timestamp_str(s: &str) -> PyResult<DateTime<Utc>> {
    let t = s.trim();
    let normalized = match t.find(' ') {
        Some(10) => t.replacen(' ', "T", 1),
        _ => t.to_string(),
    };
    if let Ok(dt) = DateTime::parse_from_rfc3339(&normalized) {
        return Ok(dt.with_timezone(&Utc));
    }
    let naive = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d"];
    if naive
        .iter()
        .any(|f| chrono::NaiveDateTime::parse_from_str(&normalized, f).is_ok()
            || chrono::NaiveDate::parse_from_str(&normalized, f).is_ok())
    {
        return Err(PyValueError::new_err(format!(
            "timestamp '{s}' has no timezone; append 'Z' for UTC or an explicit offset \
             such as '+00:00' (Observa does not guess a timezone)"
        )));
    }
    Err(PyValueError::new_err(format!(
        "cannot parse timestamp '{s}' (expected RFC 3339 with an offset, e.g. \
         '2024-01-01T00:00:00Z')"
    )))
}

fn epoch_seconds_to_utc(secs: f64, repr: &str) -> PyResult<DateTime<Utc>> {
    if !secs.is_finite() {
        return Err(PyValueError::new_err(format!("invalid epoch timestamp {repr}")));
    }
    if secs.abs() > MAX_EPOCH_SECONDS {
        return Err(PyValueError::new_err(format!(
            "epoch timestamp {repr} is too large for seconds — it looks like milliseconds \
             or microseconds; numeric timestamps must be epoch SECONDS (divide by 1000)"
        )));
    }
    let whole = secs.floor();
    // Keep sub-second precision (to the microsecond) instead of flooring.
    let mut micros = ((secs - whole) * 1e6).round() as i64;
    let mut whole = whole as i64;
    if micros >= 1_000_000 {
        whole += 1;
        micros -= 1_000_000;
    }
    Utc.timestamp_opt(whole, (micros * 1_000) as u32)
        .single()
        .ok_or_else(|| PyValueError::new_err(format!("invalid epoch timestamp {repr}")))
}

/// Accepted timestamp inputs: an RFC 3339 string with an offset, a
/// timezone-aware `datetime` (incl. `pandas.Timestamp`), or epoch seconds
/// (int/float). Ambiguous inputs are rejected with a hint, never guessed.
fn timestamp_from_py(obj: &Bound<'_, pyo3::PyAny>) -> PyResult<DateTime<Utc>> {
    if let Ok(s) = obj.downcast::<PyString>() {
        return parse_timestamp_str(&s.to_string_lossy());
    }
    if obj.is_instance_of::<pyo3::types::PyBool>() {
        return Err(PyValueError::new_err("timestamp must not be a bool"));
    }
    // datetime-like (duck-typed: the abi3 build has no PyDateTime API).
    if obj.hasattr("utcoffset")? && obj.hasattr("isoformat")? {
        if obj.call_method0("utcoffset")?.is_none() {
            let repr = obj.str().map(|s| s.to_string()).unwrap_or_default();
            return Err(PyValueError::new_err(format!(
                "timestamp {repr} is a timezone-naive datetime; attach a timezone \
                 (e.g. dt.replace(tzinfo=timezone.utc)) — Observa does not guess one"
            )));
        }
        let iso: String = obj.call_method0("isoformat")?.extract()?;
        return parse_timestamp_str(&iso);
    }
    if let Ok(i) = obj.extract::<i64>() {
        return epoch_seconds_to_utc(i as f64, &i.to_string());
    }
    if let Ok(secs) = obj.extract::<f64>() {
        return epoch_seconds_to_utc(secs, &secs.to_string());
    }
    Err(PyValueError::new_err(
        "timestamp must be an RFC 3339 string with an offset, a timezone-aware datetime, \
         or epoch seconds",
    ))
}

fn bar_from_py(obj: &Bound<'_, pyo3::PyAny>) -> PyResult<Bar> {
    // dict form: {"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
    if let Ok(d) = obj.downcast::<PyDict>() {
        let ts = d
            .get_item("timestamp")?
            .ok_or_else(|| PyValueError::new_err("bar dict missing 'timestamp'"))?;
        let get = |k: &str| -> PyResult<f64> {
            d.get_item(k)?
                .ok_or_else(|| PyValueError::new_err(format!("bar dict missing '{k}'")))?
                .extract::<f64>()
                .map_err(|e| PyValueError::new_err(format!("bar field '{k}': {e}")))
        };
        // NaN volume is pandas' marker for a missing value; volume has no
        // economic role, so it is treated as missing (∞ is still rejected).
        let volume = match d.get_item("volume")? {
            Some(v) if !v.is_none() => Some(
                v.extract::<f64>()
                    .map_err(|e| PyValueError::new_err(format!("bar field 'volume': {e}")))?,
            )
            .filter(|x| !x.is_nan()),
            _ => None,
        };
        return Ok(Bar::new(
            timestamp_from_py(&ts)?,
            get("open")?,
            get("high")?,
            get("low")?,
            get("close")?,
            volume,
        ));
    }
    // sequence form: [ts, open, high, low, close] or [ts, o, h, l, c, volume]
    if let Ok(seq) = obj.downcast::<PyList>() {
        let items: Vec<Bound<'_, pyo3::PyAny>> = seq.iter().collect();
        if items.len() < 5 {
            return Err(PyValueError::new_err(
                "bar sequence must have at least [timestamp, open, high, low, close]",
            ));
        }
        let volume = if items.len() >= 6 && !items[5].is_none() {
            Some(items[5].extract::<f64>()?).filter(|x| !x.is_nan())
        } else {
            None
        };
        return Ok(Bar::new(
            timestamp_from_py(&items[0])?,
            items[1].extract()?,
            items[2].extract()?,
            items[3].extract()?,
            items[4].extract()?,
            volume,
        ));
    }
    Err(PyValueError::new_err(
        "bar must be a dict or a sequence [timestamp, open, high, low, close, volume?]",
    ))
}

fn bars_from_py(data: &Bound<'_, pyo3::PyAny>) -> PyResult<Vec<Bar>> {
    let py = data.py();
    if let Ok(path) = data.downcast::<PyString>() {
        let path: String = path.extract()?;
        return CsvReader::load(&path).map_err(|e| {
            if let observa_data::error::DataError::FileNotFound { path, .. } = &e {
                let known = path.clone();
                return coded(
                    py,
                    PyFileNotFoundError::new_err(format!("data file not found: {path}")),
                    "DATA_FILE_NOT_FOUND",
                    Some(details(py, vec![("path", known.into_py(py))])),
                );
            }
            use observa_data::error::DataError as DE;
            let line = match &e {
                DE::CsvParseError { row, .. }
                | DE::InvalidTimestamp { row, .. }
                | DE::InvalidPrice { row, .. }
                | DE::InvalidBar { row, .. }
                | DE::NonMonotonicTimestamp { row, .. } => Some(*row),
                _ => None,
            };
            match line {
                // The loader's `row` counts records from 2 (header = 1);
                // expose the zero-based data row, consistent with the list
                // path. (No file line: the csv reader skips blank lines, so
                // the record count is not a reliable line number.)
                Some(line) => coded(
                    py,
                    PyValueError::new_err(format!("invalid data: {e}")),
                    "DATA_INVALID",
                    Some(details(py, vec![("row", line.saturating_sub(2).into_py(py))])),
                ),
                None => data_err(py, e),
            }
        });
    }
    if let Ok(list) = data.downcast::<PyList>() {
        let mut bars = Vec::with_capacity(list.len());
        for (i, item) in list.iter().enumerate() {
            let bar = bar_from_py(&item).map_err(|e| {
                coded(
                    py,
                    e,
                    "DATA_INVALID",
                    Some(details(py, vec![("row", i.into_py(py))])),
                )
            })?;
            // OBS-TRUST-02: the list/DataFrame path applies the same bar
            // invariants as the CSV loader (it used to apply none).
            if let Err(errors) = bar.validate() {
                let violations: Vec<String> = errors.iter().map(|e| e.to_string()).collect();
                return Err(coded(
                    py,
                    PyValueError::new_err(format!(
                        "invalid data: bar at row {i} ({}): {}",
                        bar.timestamp.to_rfc3339(),
                        violations.join("; ")
                    )),
                    "DATA_INVALID",
                    Some(details(
                        py,
                        vec![
                            ("row", i.into_py(py)),
                            ("violations", violations.into_py(py)),
                        ],
                    )),
                ));
            }
            bars.push(bar);
        }
        return Ok(bars);
    }
    Err(coded(
        py,
        PyValueError::new_err(
            "data must be a CSV file path or a list of bars (dicts or sequences)",
        ),
        "DATA_INVALID",
        None,
    ))
}

// ────────────────────────────────────────────────
// Python strategy -> canonical Strategy trait
// ────────────────────────────────────────────────

/// Wraps a Python strategy instance and implements the canonical `Strategy`
/// trait. The Engine drives this wrapper; no Python-side replay loop exists.
struct PyStrategy {
    instance: PyObject,
    class_name: String,
    symbol: String,
    last_error: Option<StrategyFailure>,
    /// Annotations returned by the last `on_bar` call (OBS-AI-02).
    pending_drawings: Vec<DrawingInstruction>,
    /// Per-run drawing id registry used for lifecycle validation.
    drawings: DrawingRegistry,
    /// Zero-based index of the bar currently being processed.
    bar_index: usize,
    /// Append-only copy of the bars the strategy has already observed, shared
    /// by every `History` view handed out (OBS-TRUST-03). Each view records its
    /// own length, so it only ever exposes strictly-prior bars.
    history_store: Arc<RwLock<Vec<Bar>>>,
}

impl PyStrategy {
    fn new(instance: PyObject, class_name: String, symbol: String) -> Self {
        Self {
            instance,
            class_name,
            symbol,
            last_error: None,
            pending_drawings: Vec::new(),
            drawings: DrawingRegistry::new(),
            bar_index: 0,
            history_store: Arc::new(RwLock::new(Vec::new())),
        }
    }

    /// Brings the shared store in line with the Engine's strictly-prior
    /// history (one appended bar per call) and returns an O(1) view of it.
    fn history_view(&self, py: Python<'_>, history: &[Bar]) -> PyResult<Py<HistoryView>> {
        {
            let mut store = self
                .history_store
                .write()
                .map_err(|_| PyRuntimeError::new_err("history store poisoned"))?;
            if store.len() > history.len() {
                store.clear();
            }
            let start = store.len();
            store.extend_from_slice(&history[start..]);
        }
        Py::new(
            py,
            HistoryView {
                store: Arc::clone(&self.history_store),
                len: history.len(),
                cache: Mutex::new(BTreeMap::new()),
            },
        )
    }

    fn return_invalid(&mut self, message: String, received: &str) {
        self.last_error = Some(StrategyFailure::coded(
            "STRATEGY_RETURN_INVALID",
            format!("strategy '{}' {message}", self.class_name),
            json!({ "bar_index": self.bar_index, "received": received }),
        ));
    }
}

// ────────────────────────────────────────────────
// Read-only strategy history (OBS-TRUST-03, issue #6)
// ────────────────────────────────────────────────

/// A read-only, list-like view of the bars strictly before the current one.
///
/// Creating a view is O(1) (the previous adapter rebuilt a list of dicts of
/// every prior bar on every bar: O(N²) per run). Each bar's dict is built
/// lazily on first access and then reused by this view, so — exactly as with
/// the old per-bar list — `history[0] is history[0]` and an in-place edit is
/// visible for the rest of the current bar, while the next bar's view starts
/// from fresh dicts (edits never leak across bars). A view retained from an
/// earlier bar keeps its original length forever.
#[pyclass(name = "History", module = "observa._observa", frozen, sequence)]
struct HistoryView {
    store: Arc<RwLock<Vec<Bar>>>,
    len: usize,
    /// Dicts already materialised by this view (only the accessed indices).
    cache: Mutex<BTreeMap<usize, Py<PyDict>>>,
}

impl HistoryView {
    fn bar_dict(&self, py: Python<'_>, i: usize) -> PyResult<PyObject> {
        let poisoned = || PyRuntimeError::new_err("history store poisoned");
        if let Some(d) = self.cache.lock().map_err(|_| poisoned())?.get(&i) {
            return Ok(d.clone_ref(py).into_py(py));
        }
        // Copy the bar out and release the lock BEFORE creating Python objects:
        // allocation can trigger GC/finalizers that switch threads, and no lock
        // may be held across that (deadlock risk on older CPythons).
        let bar = {
            let store = self.store.read().map_err(|_| poisoned())?;
            store[i].clone()
        };
        let dict = bar_to_py_dict(py, &bar)?.unbind();
        let previous = self
            .cache
            .lock()
            .map_err(|_| poisoned())?
            .insert(i, dict.clone_ref(py));
        drop(previous); // dropped after the lock is released
        Ok(dict.into_py(py))
    }

    fn to_list<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let out = PyList::empty_bound(py);
        for i in 0..self.len {
            out.append(self.bar_dict(py, i)?)?;
        }
        Ok(out)
    }

    fn eq_seq(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<Option<bool>> {
        let items: Vec<Bound<'_, PyAny>> = if let Ok(h) = other.downcast::<HistoryView>() {
            h.get().to_list(py)?.iter().collect()
        } else if let Ok(l) = other.downcast::<PyList>() {
            l.iter().collect()
        } else {
            return Ok(None);
        };
        if items.len() != self.len {
            return Ok(Some(false));
        }
        for (i, item) in items.iter().enumerate() {
            if !self.bar_dict(py, i)?.bind(py).eq(item)? {
                return Ok(Some(false));
            }
        }
        Ok(Some(true))
    }
}

#[pymethods]
impl HistoryView {
    fn __len__(&self) -> usize {
        self.len
    }

    fn __getitem__(&self, py: Python<'_>, index: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        if let Ok(slice) = index.downcast::<PySlice>() {
            let ind = slice.indices(self.len as isize)?;
            let out = PyList::empty_bound(py);
            let mut i = ind.start;
            for _ in 0..ind.slicelength {
                out.append(self.bar_dict(py, i as usize)?)?;
                i += ind.step;
            }
            return Ok(out.into_py(py));
        }
        let mut i: isize = match index.extract() {
            Ok(i) => i,
            Err(_) if index.is_instance_of::<pyo3::types::PyInt>() => {
                return Err(PyIndexError::new_err("history index out of range"))
            }
            Err(_) => {
                return Err(pyo3::exceptions::PyTypeError::new_err(
                    "history indices must be integers or slices",
                ))
            }
        };
        if i < 0 {
            i += self.len as isize;
        }
        if i < 0 || i as usize >= self.len {
            return Err(PyIndexError::new_err("history index out of range"));
        }
        self.bar_dict(py, i as usize)
    }

    fn __iter__(slf: &Bound<'_, Self>) -> HistoryIter {
        HistoryIter {
            view: Some(slf.clone().unbind()),
            next: 0,
            end: slf.get().len,
            reverse: false,
        }
    }

    fn __reversed__(slf: &Bound<'_, Self>) -> HistoryIter {
        HistoryIter {
            view: Some(slf.clone().unbind()),
            next: 0,
            end: slf.get().len,
            reverse: true,
        }
    }

    fn __contains__(&self, py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<bool> {
        for i in 0..self.len {
            if self.bar_dict(py, i)?.bind(py).eq(value)? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    #[pyo3(signature = (value, start=0, stop=None))]
    fn index(
        &self,
        py: Python<'_>,
        value: &Bound<'_, PyAny>,
        start: isize,
        stop: Option<isize>,
    ) -> PyResult<usize> {
        let n = self.len as isize;
        let norm = |x: isize| if x < 0 { (x + n).max(0) } else { x.min(n) };
        let (a, b) = (norm(start), norm(stop.unwrap_or(n)));
        for i in a..b {
            if self.bar_dict(py, i as usize)?.bind(py).eq(value)? {
                return Ok(i as usize);
            }
        }
        Err(PyValueError::new_err("bar is not in history"))
    }

    fn count(&self, py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<usize> {
        let mut c = 0;
        for i in 0..self.len {
            if self.bar_dict(py, i)?.bind(py).eq(value)? {
                c += 1;
            }
        }
        Ok(c)
    }

    /// A mutable `list` copy (the view itself is read-only).
    fn copy<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        self.to_list(py)
    }

    /// `copy.copy(history)` returns a list (like `list.copy()`).
    fn __copy__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        self.to_list(py)
    }

    /// `copy.deepcopy(history)` returns a deep-copied list.
    fn __deepcopy__(&self, py: Python<'_>, memo: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let copy = py.import_bound("copy")?;
        Ok(copy.call_method1("deepcopy", (self.to_list(py)?, memo))?.unbind())
    }

    /// Pickling yields a plain list of bar dicts.
    fn __reduce__(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list_type = py.import_bound("builtins")?.getattr("list")?;
        Ok((list_type, (self.to_list(py)?,)).into_py(py))
    }

    fn __add__(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let out = self.to_list(py)?;
        for item in other.iter()? {
            out.append(item?)?;
        }
        Ok(out.into_py(py))
    }

    fn __radd__(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let out = PyList::empty_bound(py);
        for item in other.iter()? {
            out.append(item?)?;
        }
        for i in 0..self.len {
            out.append(self.bar_dict(py, i)?)?;
        }
        Ok(out.into_py(py))
    }

    fn __richcmp__(
        &self,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        op: pyo3::basic::CompareOp,
    ) -> PyResult<PyObject> {
        use pyo3::basic::CompareOp;
        match op {
            CompareOp::Eq | CompareOp::Ne => match self.eq_seq(py, other)? {
                Some(eq) => Ok((if matches!(op, CompareOp::Eq) { eq } else { !eq }).into_py(py)),
                None => Ok(py.NotImplemented()),
            },
            _ => Ok(py.NotImplemented()),
        }
    }

    fn __repr__(&self) -> String {
        format!("<observa History: {} prior bars (read-only)>", self.len)
    }

    // The cache holds Python dicts; expose them to the cycle collector so a
    // cycle through a view (e.g. a view stored inside one of its own dicts) is
    // freed.
    fn __traverse__(&self, visit: pyo3::PyVisit<'_>) -> Result<(), pyo3::PyTraverseError> {
        if let Ok(cache) = self.cache.try_lock() {
            for d in cache.values() {
                visit.call(d)?;
            }
        }
        Ok(())
    }

    fn __clear__(&self) {
        // Take the dicts out first; drop them after the lock is released.
        let taken = match self.cache.lock() {
            Ok(mut cache) => std::mem::take(&mut *cache),
            Err(_) => return,
        };
        drop(taken);
    }
}

#[pyclass(module = "observa._observa")]
struct HistoryIter {
    view: Option<Py<HistoryView>>,
    next: usize,
    end: usize,
    reverse: bool,
}

#[pymethods]
impl HistoryIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<PyObject>> {
        if self.next >= self.end {
            return Ok(None);
        }
        let view = match &self.view {
            Some(v) => v.clone_ref(py),
            None => return Ok(None),
        };
        let i = if self.reverse { self.end - 1 - self.next } else { self.next };
        self.next += 1;
        Ok(Some(view.get().bar_dict(py, i)?))
    }

    fn __traverse__(&self, visit: pyo3::PyVisit<'_>) -> Result<(), pyo3::PyTraverseError> {
        if let Some(v) = &self.view {
            visit.call(v)?;
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.view = None;
    }
}

// ────────────────────────────────────────────────
// Python → JSON conversion (drawing payloads)
// ────────────────────────────────────────────────

/// Converts a Python value into `serde_json::Value` for strict drawing
/// validation. Only the JSON-representable subset is accepted (mappings,
/// sequences, str, bool, int, float, None); anything else is reported as a
/// drawing value error rather than silently coerced.
fn py_to_json(obj: &Bound<'_, pyo3::PyAny>) -> Result<Value, String> {
    if obj.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(b) = obj.downcast::<pyo3::types::PyBool>() {
        return Ok(Value::Bool(b.is_true()));
    }
    if let Ok(i) = obj.extract::<i64>() {
        return Ok(json!(i));
    }
    if let Ok(f) = obj.extract::<f64>() {
        return Ok(json!(f));
    }
    if let Ok(s) = obj.downcast::<PyString>() {
        return Ok(Value::String(s.to_string_lossy().into_owned()));
    }
    if let Ok(d) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::with_capacity(d.len());
        for (k, v) in d.iter() {
            let key = match k.downcast::<PyString>() {
                Ok(s) => s.to_string_lossy().into_owned(),
                Err(_) => return Err("drawing keys must be strings".to_string()),
            };
            map.insert(key, py_to_json(&v)?);
        }
        return Ok(Value::Object(map));
    }
    if let Ok(list) = obj.downcast::<PyList>() {
        let mut out = Vec::with_capacity(list.len());
        for item in list.iter() {
            out.push(py_to_json(&item)?);
        }
        return Ok(Value::Array(out));
    }
    if let Ok(t) = obj.downcast::<pyo3::types::PyTuple>() {
        let mut out = Vec::with_capacity(t.len());
        for item in t.iter() {
            out.push(py_to_json(&item)?);
        }
        return Ok(Value::Array(out));
    }
    Err(format!(
        "unsupported drawing value of type '{}'",
        obj.get_type().name().map(|n| n.to_string()).unwrap_or_else(|_| "?".to_string())
    ))
}

fn bar_to_py_dict<'py>(py: Python<'py>, bar: &Bar) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("open", bar.open)?;
    d.set_item("high", bar.high)?;
    d.set_item("low", bar.low)?;
    d.set_item("close", bar.close)?;
    // Canonical strategy-facing format (issue #8, documented and test-pinned):
    // UTC, `YYYY-MM-DDTHH:MM:SS[.fff]+00:00`, whatever the input form was.
    // `timestamp_ms` is the unambiguous join key for external data.
    d.set_item("timestamp", bar.timestamp.to_rfc3339())?;
    d.set_item("timestamp_ms", bar.timestamp.timestamp_millis())?;
    match bar.volume {
        Some(v) => d.set_item("volume", v)?,
        None => d.set_item("volume", py.None())?,
    }
    Ok(d)
}

fn portfolio_to_py_dict<'py>(
    py: Python<'py>,
    view: &PortfolioView,
    symbol: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("balance", view.balance)?;
    d.set_item("equity", view.equity)?;
    d.set_item("used_margin", view.used_margin)?;
    d.set_item("free_margin", view.free_margin)?;
    d.set_item("has_open_position", view.has_open_position)?;
    d.set_item("unrealised_pnl", view.unrealised_pnl)?;

    let positions = PyList::empty_bound(py);
    for pos in &view.open_positions {
        let pd = PyDict::new_bound(py);
        pd.set_item("position_id", &pos.ticket)?;
        pd.set_item("ticket", &pos.ticket)?;
        pd.set_item("symbol", symbol)?;
        pd.set_item("direction", format!("{:?}", pos.direction))?;
        pd.set_item("quantity", pos.size)?;
        pd.set_item("size", pos.size)?;
        pd.set_item("entry_price", pos.entry_price)?;
        pd.set_item("unrealized_pnl", pos.unrealised_pnl)?;
        pd.set_item("unrealised_pnl", pos.unrealised_pnl)?;
        pd.set_item(
            "stop_loss",
            pos.sl.map_or_else(|| py.None(), |v| v.into_py(py)),
        )?;
        pd.set_item(
            "take_profit",
            pos.tp.map_or_else(|| py.None(), |v| v.into_py(py)),
        )?;
        positions.append(pd)?;
    }
    d.set_item("open_positions", positions)?;
    Ok(d)
}

fn parse_order_kind(s: &str) -> PyResult<OrderKind> {
    match s.to_lowercase().as_str() {
        "market" => Ok(OrderKind::Market),
        "limit" => Ok(OrderKind::Limit),
        "stop" => Ok(OrderKind::Stop),
        other => Err(PyValueError::new_err(format!(
            "unknown order_type '{other}' — use 'market', 'limit', or 'stop'"
        ))),
    }
}

/// Rejects signal keys the Engine would otherwise silently ignore
/// (OBS-TRUST-01): e.g. `stop_loss` instead of `sl` used to open a position
/// with no stop at all.
fn check_signal_keys(
    d: &Bound<'_, PyDict>,
    class_name: &str,
    bar_index: usize,
    signal_index: usize,
) -> Result<(), StrategyFailure> {
    for (k, _) in d.iter() {
        let key = match k.downcast::<PyString>() {
            Ok(s) => s.to_string_lossy().into_owned(),
            Err(_) => {
                return Err(StrategyFailure::coded(
                    "SIGNAL_FIELD_UNKNOWN",
                    format!("strategy '{class_name}': signal keys must be strings"),
                    json!({ "bar_index": bar_index, "signal_index": signal_index,
                            "field": k.str().map(|s| s.to_string()).unwrap_or_default(),
                            "suggestion": Value::Null, "allowed": SIGNAL_FIELDS }),
                ))
            }
        };
        if SIGNAL_FIELDS.contains(&key.as_str()) {
            continue;
        }
        let suggestion = signal_suggestion(&key);
        let hint = suggestion
            .map(|s| format!(" — did you mean '{s}'?"))
            .unwrap_or_default();
        return Err(StrategyFailure::coded(
            "SIGNAL_FIELD_UNKNOWN",
            format!(
                "strategy '{class_name}' returned a signal with unknown field '{key}'{hint} \
                 (signal {signal_index} on bar {bar_index}; allowed: {})",
                SIGNAL_FIELDS.join(", ")
            ),
            json!({ "bar_index": bar_index, "signal_index": signal_index, "field": key,
                    "suggestion": suggestion, "allowed": SIGNAL_FIELDS }),
        ));
    }
    Ok(())
}

fn signal_from_py(obj: &Bound<'_, pyo3::PyAny>) -> PyResult<StrategySignal> {
    let d = obj
        .downcast::<PyDict>()
        .map_err(|_| PyValueError::new_err("signal must be a dict"))?;

    let direction = d
        .get_item("direction")?
        .ok_or_else(|| PyValueError::new_err("signal missing 'direction'"))?
        .extract::<String>()?
        .to_lowercase();
    let direction = match direction.as_str() {
        "buy" => Direction::Buy,
        "sell" => Direction::Sell,
        "close" => Direction::Close,
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown direction '{other}' — use 'buy', 'sell', or 'close'"
            )))
        }
    };

    let size: f64 = d
        .get_item("size")?
        .ok_or_else(|| PyValueError::new_err("signal missing 'size'"))?
        .extract()?;

    let order_type = match d.get_item("order_type")? {
        Some(v) if !v.is_none() => parse_order_kind(&v.extract::<String>()?)?,
        _ => OrderKind::Market,
    };

    let get_f = |k: &str| -> PyResult<Option<f64>> {
        match d.get_item(k)? {
            Some(v) if !v.is_none() => Ok(Some(v.extract()?)),
            _ => Ok(None),
        }
    };
    let intended_price = get_f("price")?.unwrap_or(0.0);
    let sl = get_f("sl")?;
    let tp = get_f("tp")?;
    // OBS-SCHEMA-01: an absent/None reason means "no reason given" and must
    // never be replaced by placeholder prose, which would be indistinguishable
    // from a real authored reason once persisted.
    let reason = match d.get_item("reason")? {
        Some(v) if !v.is_none() => v.extract::<String>()?,
        _ => String::new(),
    };
    let ticket = match d.get_item("ticket")? {
        Some(v) if !v.is_none() => Some(v.extract::<String>()?),
        _ => None,
    };

    Ok(StrategySignal {
        direction,
        order_type,
        size,
        intended_price,
        sl,
        tp,
        reason,
        ticket,
    })
}

impl Strategy for PyStrategy {
    fn initialize_with_params(&mut self, params: Option<&BTreeMap<String, Value>>) {
        let result = Python::with_gil(|py| {
            let dict = PyDict::new_bound(py);
            if let Some(p) = params {
                for (k, v) in p {
                    if let Ok(pv) = value_to_py(py, v) {
                        dict.set_item(k, pv).ok();
                    }
                }
            }
            self.instance
                .call_method1(py, "initialize", (dict,))
                .map(|_| ())
        });
        if let Err(e) = result {
            self.last_error = Some(StrategyFailure::new(format!(
                "strategy '{}' initialize() failed: {e}",
                self.class_name
            )));
        }
    }

    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        history: &[Bar],
    ) -> Vec<StrategySignal> {
        Python::with_gil(|py| {
            let py_bar = match bar_to_py_dict(py, bar) {
                Ok(d) => d,
                Err(e) => {
                    self.last_error = Some(StrategyFailure::new(format!("bar conversion failed: {e}")));
                    return vec![];
                }
            };
            let py_portfolio = match portfolio_to_py_dict(py, portfolio, &self.symbol) {
                Ok(d) => d,
                Err(e) => {
                    self.last_error = Some(StrategyFailure::new(format!("portfolio conversion failed: {e}")));
                    return vec![];
                }
            };
            let py_history = match self.history_view(py, history) {
                Ok(h) => h,
                Err(e) => {
                    self.last_error = Some(StrategyFailure::new(format!("history conversion failed: {e}")));
                    return vec![];
                }
            };

            let result =
                match self
                    .instance
                    .call_method1(py, "on_bar", (py_bar, py_portfolio, py_history))
                {
                    Ok(r) => r,
                    Err(e) => {
                        self.last_error = Some(StrategyFailure::new(format!(
                            "strategy '{}' on_bar() failed: {e}",
                            self.class_name
                        )));
                        return vec![];
                    }
                };

            // Accept either a plain list of signal dicts or
            // {'signals': [...], 'drawings': [...]}. Anything else fails the
            // run (OBS-TRUST-01): a bare signal dict, `None` (a forgotten
            // `return`) or a misspelled envelope key used to be ignored,
            // producing a "successful" run with the intent silently lost.
            //
            // Annotations are descriptive only (OBS-AI-02): they are validated
            // strictly, recorded on the canonical timeline and never fed into
            // order processing. Malformed annotations fail the run instead of
            // being silently discarded.
            let bound = result.bind(py);
            if bound.is_none() {
                self.return_invalid(
                    "on_bar() returned None — return [] for no action (is a `return` \
                     statement missing on some path?)"
                        .to_string(),
                    "NoneType",
                );
                return vec![];
            }
            let mut list_opt = Some(result.clone_ref(py).into_bound(py));
            if let Ok(d) = result.downcast_bound::<PyDict>(py) {
                if d.contains("direction").unwrap_or(false) && !d.contains("signals").unwrap_or(false) {
                    self.return_invalid(
                        "on_bar() returned a bare signal dict — wrap it in a list: \
                         return [signal]"
                            .to_string(),
                        "dict",
                    );
                    return vec![];
                }
                let mut extra = Vec::new();
                for (k, _) in d.iter() {
                    let key = k.str().map(|s| s.to_string()).unwrap_or_default();
                    if key != "signals" && key != "drawings" {
                        extra.push(key);
                    }
                }
                if !extra.is_empty() {
                    let hint = if extra.iter().any(|k| closest_key(k, &["signals"]).is_some()) {
                        " — did you mean 'signals'?"
                    } else {
                        ""
                    };
                    self.return_invalid(
                        format!(
                            "on_bar() returned a dict with unknown key(s) {}{hint} (allowed: \
                             'signals', 'drawings')",
                            extra.iter().map(|k| format!("'{k}'")).collect::<Vec<_>>().join(", ")
                        ),
                        "dict",
                    );
                    return vec![];
                }
                list_opt = d.get_item("signals").ok().flatten();
                if list_opt.is_none() {
                    self.return_invalid(
                        "on_bar() returned a dict without a 'signals' key — use \
                         {'signals': [...], 'drawings': [...]} (signals may be [])"
                            .to_string(),
                        "dict",
                    );
                    return vec![];
                }
                if let Some(sig) = &list_opt {
                    if !sig.is_instance_of::<PyList>() {
                        let t = sig.get_type().name().map(|n| n.to_string()).unwrap_or_default();
                        self.return_invalid(
                            format!("on_bar() returned 'signals' of type {t}; it must be a list"),
                            &t,
                        );
                        return vec![];
                    }
                }
                match d.get_item("drawings") {
                    Ok(Some(drawings_obj)) => {
                        let values = match py_to_json(&drawings_obj) {
                            Ok(Value::Array(items)) => items,
                            Ok(_) => {
                                self.last_error = Some(StrategyFailure::coded(
                                    "DRAWING_TYPE_INVALID",
                                    format!(
                                        "strategy '{}': 'drawings' must be a list",
                                        self.class_name
                                    ),
                                    json!({ "bar_index": self.bar_index }),
                                ));
                                return vec![];
                            }
                            Err(message) => {
                                self.last_error = Some(StrategyFailure::coded(
                                    "DRAWING_VALUE_INVALID",
                                    format!("strategy '{}': {message}", self.class_name),
                                    json!({ "bar_index": self.bar_index }),
                                ));
                                return vec![];
                            }
                        };
                        match self.drawings.parse_bar(&values, self.bar_index) {
                            Ok(parsed) => self.pending_drawings = parsed,
                            Err(e) => {
                                self.last_error = Some(StrategyFailure::coded(
                                    e.code.clone(),
                                    format!("strategy '{}': {}", self.class_name, e.message),
                                    e.details.clone(),
                                ));
                                return vec![];
                            }
                        }
                    }
                    Ok(None) => {}
                    Err(e) => {
                        self.last_error = Some(StrategyFailure::new(format!(
                            "strategy '{}': 'drawings' could not be read: {e}",
                            self.class_name
                        )));
                        return vec![];
                    }
                }
            }
            let mut out = Vec::new();
            if let Some(list_obj) = list_opt {
                if let Ok(list) = list_obj.downcast::<PyList>() {
                    for (signal_index, item) in list.iter().enumerate() {
                        if let Ok(d) = item.downcast::<PyDict>() {
                            if let Err(f) =
                                check_signal_keys(d, &self.class_name, self.bar_index, signal_index)
                            {
                                self.last_error = Some(f);
                                return vec![];
                            }
                        }
                        match signal_from_py(&item) {
                            Ok(s) => out.push(s),
                            Err(e) => {
                                self.last_error = Some(StrategyFailure::new(format!(
                                    "strategy '{}' returned an invalid signal: {e}",
                                    self.class_name
                                )));
                                return vec![];
                            }
                        }
                    }
                } else {
                    let t = list_obj.get_type().name().map(|n| n.to_string()).unwrap_or_default();
                    self.return_invalid(
                        format!(
                            "on_bar() returned a {t}; it must return a list of signal dicts or \
                             a dict with 'signals'"
                        ),
                        &t,
                    );
                    return vec![];
                }
            }
            self.bar_index += 1;
            out
        })
    }

    fn take_strategy_error(&mut self) -> Option<StrategyFailure> {
        self.last_error.take()
    }

    fn take_drawings(&mut self) -> Vec<DrawingInstruction> {
        std::mem::take(&mut self.pending_drawings)
    }

    fn teardown(&mut self) {
        Python::with_gil(|py| {
            if let Err(e) = self.instance.call_method0(py, "teardown") {
                self.last_error = Some(StrategyFailure::new(format!(
                    "strategy '{}' teardown() failed: {e}",
                    self.class_name
                )));
            }
        });
    }
}

// ────────────────────────────────────────────────
// Metrics (derived, non-authoritative)
// ────────────────────────────────────────────────

fn num_or_null(v: f64) -> Value {
    if v.is_finite() {
        json!(v)
    } else {
        Value::Null
    }
}

fn metrics_value(result: &EngineRunResult, bars_per_year: f64) -> Value {
    let initial = result
        .bars
        .first()
        .map(|b| b.snapshot.balance)
        .unwrap_or(0.0);
    let mut m = MetricsEngine::new(initial, bars_per_year);
    for b in &result.bars {
        m.on_snapshot(b.snapshot.timestamp, b.snapshot.equity);
    }
    for t in &result.trades {
        m.on_trade_closed(t.net_realized_pnl);
    }
    let r = m.report();
    json!({
        "metrics_schema_version": 1,
        "total_return_pct": num_or_null(r.total_return_pct),
        "annualised_return_pct": num_or_null(r.annualised_return_pct),
        "max_drawdown_pct": num_or_null(r.max_drawdown_pct),
        "max_drawdown_start": r.max_drawdown_start,
        "max_drawdown_end": r.max_drawdown_end,
        "current_drawdown_pct": num_or_null(r.current_drawdown_pct),
        "sharpe_ratio": match r.sharpe_ratio { Some(v) if v.is_finite() => json!(v), _ => Value::Null },
        "calmar_ratio": match r.calmar_ratio { Some(v) if v.is_finite() => json!(v), _ => Value::Null },
        "total_trades": r.total_trades,
        "winning_trades": r.winning_trades,
        "losing_trades": r.losing_trades,
        "win_rate_pct": num_or_null(r.win_rate_pct),
        "avg_win": num_or_null(r.avg_win),
        "avg_loss": num_or_null(r.avg_loss),
        "profit_factor": if r.profit_factor.is_finite() { json!(r.profit_factor) } else { Value::Null },
        "expectancy": num_or_null(r.expectancy),
        "largest_win": num_or_null(r.largest_win),
        "largest_loss": num_or_null(r.largest_loss),
        "final_balance": result.final_state.final_balance,
        "final_equity": result.final_state.final_equity,
        "open_positions_remaining": result.final_state.open_positions_remaining,
    })
}

// ────────────────────────────────────────────────
// Result object
// ────────────────────────────────────────────────

/// The Python-facing result of a canonical run.
#[pyclass(name = "RunResult")]
struct RunResult {
    config: BacktestConfig,
    bars: Vec<Bar>,
    result: EngineRunResult,
    bars_per_year: f64,
    dataset_source: String,
    artifact_dir: Option<String>,
    /// Derived metrics are expensive to compute; cache the canonical derived
    /// value so `metrics` / `summary()` never recompute it repeatedly.
    metrics_cache: RefCell<Option<serde_json::Value>>,
}

fn trade_to_dict(py: Python<'_>, t: &observa_engine::engine::TradeRecord) -> PyResult<PyObject> {
    let d = PyDict::new_bound(py);
    d.set_item("bar_index", t.bar_index)?;
    d.set_item("position_id", t.position_id.to_string())?;
    d.set_item("direction", format!("{:?}", t.direction))?;
    d.set_item("quantity_lots", t.quantity_lots)?;
    d.set_item("entry_price", t.entry_price)?;
    d.set_item("exit_price", t.exit_price)?;
    d.set_item("exit_reason", format!("{:?}", t.exit_reason))?;
    d.set_item("gross_realized_pnl", t.gross_realized_pnl)?;
    d.set_item("total_commission", t.total_commission)?;
    d.set_item("net_realized_pnl", t.net_realized_pnl)?;
    Ok(d.into_py(py))
}

fn order_to_dict(py: Python<'_>, o: &observa_engine::engine::OrderRecord) -> PyResult<PyObject> {
    let d = PyDict::new_bound(py);
    d.set_item("seq", o.seq)?;
    d.set_item("order_type", format!("{:?}", o.order_type).to_lowercase())?;
    d.set_item("side", format!("{:?}", o.side))?;
    d.set_item("quantity_lots", o.quantity_lots)?;
    d.set_item("created_bar", o.created_bar)?;
    d.set_item("state", format!("{:?}", o.state))?;
    d.set_item(
        "position_id",
        o.position_id.map(|u| u.to_string()).into_py(py),
    )?;
    d.set_item("filled_bar", o.filled_bar.into_py(py))?;
    d.set_item("executed_price", o.executed_price.into_py(py))?;
    d.set_item("rejection", o.rejection.clone().into_py(py))?;
    Ok(d.into_py(py))
}

fn fill_to_dict(py: Python<'_>, f: &observa_engine::engine::RuntimeFill) -> PyResult<PyObject> {
    let d = PyDict::new_bound(py);
    d.set_item("bar_index", f.bar_index)?;
    d.set_item("order_seq", f.order_seq.into_py(py))?;
    d.set_item("reason", format!("{:?}", f.reason))?;
    d.set_item("side", format!("{:?}", f.side))?;
    d.set_item("quantity_lots", f.quantity_lots)?;
    d.set_item("raw_reference", f.raw_reference)?;
    d.set_item("executed_price", f.executed_price)?;
    d.set_item("spread_applied", f.spread_applied)?;
    d.set_item("slippage_applied", f.slippage_applied)?;
    d.set_item("commission_amount", f.commission_amount)?;
    d.set_item(
        "position_id",
        f.position_id.map(|u| u.to_string()).into_py(py),
    )?;
    d.set_item("timestamp", f.timestamp.to_rfc3339())?;
    Ok(d.into_py(py))
}

#[pymethods]
impl RunResult {
    #[getter]
    fn final_balance(&self) -> f64 {
        self.result.final_state.final_balance
    }

    #[getter]
    fn final_equity(&self) -> f64 {
        self.result.final_state.final_equity
    }

    #[getter]
    fn total_bars(&self) -> usize {
        self.result.total_bars
    }

    #[getter]
    fn open_positions(&self) -> usize {
        self.result.final_state.open_positions_remaining
    }

    #[getter]
    fn artifact_dir(&self) -> Option<String> {
        self.artifact_dir.clone()
    }

    #[getter]
    fn trades(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for t in &self.result.trades {
            list.append(trade_to_dict(py, t)?)?;
        }
        Ok(list.into_py(py))
    }

    #[getter]
    fn orders(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for o in &self.result.orders {
            list.append(order_to_dict(py, o)?)?;
        }
        Ok(list.into_py(py))
    }

    #[getter]
    fn fills(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for f in &self.result.fills {
            list.append(fill_to_dict(py, f)?)?;
        }
        Ok(list.into_py(py))
    }

    #[getter]
    fn events(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for e in &self.result.events {
            let v = serde_json::to_value(e)
                .map_err(|e| PyRuntimeError::new_err(format!("event serialization: {e}")))?;
            list.append(value_to_py(py, &v)?)?;
        }
        Ok(list.into_py(py))
    }

    #[getter]
    fn metrics(&self, py: Python<'_>) -> PyResult<PyObject> {
        value_to_py(py, &self.metrics_value_cached())
    }

    /// Structured, agent-oriented summary of the canonical run.
    ///
    /// Values are canonical (stored Engine result / derived metrics); arrays
    /// such as trades/orders/fills/events are summarised by count only.
    fn summary(&self, py: Python<'_>) -> PyResult<PyObject> {
        let d = PyDict::new_bound(py);
        d.set_item("status", "completed")?;
        d.set_item("artifact_dir", self.artifact_dir.clone())?;
        d.set_item("total_bars", self.result.total_bars)?;
        d.set_item("trades", self.result.trades.len())?;
        d.set_item(
            "open_positions",
            self.result.final_state.open_positions_remaining,
        )?;
        d.set_item("final_balance", self.result.final_state.final_balance)?;
        d.set_item("final_equity", self.result.final_state.final_equity)?;
        d.set_item("events", self.result.events.len())?;
        d.set_item("metrics", value_to_py(py, &self.metrics_value_cached())?)?;
        d.set_item("dataset_source", &self.dataset_source)?;
        d.set_item("run_schema_version", RUN_SCHEMA_VERSION)?;
        Ok(d.into_py(py))
    }

    /// Persists the canonical artifacts (run.json / events.jsonl /
    /// metrics.json) to `output_dir`. Create-only: refuses to overwrite.
    fn save(&mut self, py: Python<'_>, output_dir: String) -> PyResult<String> {
        let path = std::path::PathBuf::from(&output_dir);
        let dir = persistence::persist_completed_run(
            &path,
            &self.config,
            &self.bars,
            &self.result.events,
            &self.result,
            self.bars_per_year,
            &self.dataset_source,
        )
        .map_err(|e| map_persistence(py, e))?;
        self.artifact_dir = Some(dir.display().to_string());
        Ok(dir.display().to_string())
    }
}

impl RunResult {
    /// Computes the derived metrics once and reuses them afterwards.
    fn metrics_value_cached(&self) -> serde_json::Value {
        if let Some(cached) = self.metrics_cache.borrow().as_ref() {
            return cached.clone();
        }
        let value = metrics_value(&self.result, self.bars_per_year);
        *self.metrics_cache.borrow_mut() = Some(value.clone());
        value
    }
}

// ────────────────────────────────────────────────
// Public entry point
// ────────────────────────────────────────────────

/// Runs a canonical backtest with a Python strategy.
///
/// `data` is a CSV path or a list of bars; `config` is a dict of canonical
/// config fields; `output` optionally persists the canonical artifacts.
#[pyfunction]
#[pyo3(signature = (strategy, data, config=None, output=None, bars_per_year=252.0))]
fn run(
    py: Python<'_>,
    strategy: &Bound<'_, pyo3::PyAny>,
    data: &Bound<'_, pyo3::PyAny>,
    config: Option<&Bound<'_, PyDict>>,
    output: Option<String>,
    bars_per_year: f64,
) -> PyResult<RunResult> {
    let bars = bars_from_py(data)?;

    if let Some(d) = config {
        check_config_keys(py, d)?;
    }
    let mut cfg = match config {
        Some(d) => config_from_dict(d).map_err(|e| config_err(py, e))?,
        None => BacktestConfig::default(),
    };

    // Strategy identity + parameters (resolved from the config dict).
    let class_name = strategy
        .getattr("__class__")
        .and_then(|c| c.getattr("__name__"))
        .and_then(|n| n.extract::<String>())
        .unwrap_or_else(|_| "Strategy".to_string());
    if let Some(d) = config {
        // Type-checked even though it is not recorded yet (see note below).
        opt_str(d, "strategy_name").map_err(|e| config_err(py, e))?;
    }
    // NOTE: `strategy_name` is accepted but not yet recorded: recording it as
    // the strategy `name` would change the strategy identity hash
    // (`params_sha256`). Deferred to a run-schema change (trust audit §8).
    let params = match config {
        Some(d) => params_from_dict(d).map_err(|e| config_err(py, e))?,
        None => BTreeMap::new(),
    };
    let strategy_source = match config {
        Some(d) => opt_str(d, "strategy_source").map_err(|e| config_err(py, e))?,
        None => None,
    };
    let dataset_source = match config {
        Some(d) => opt_str(d, "dataset_source")
            .map_err(|e| config_err(py, e))?
            .unwrap_or_else(|| "python".to_string()),
        None => "python".to_string(),
    };
    let interval = match config {
        Some(d) => match opt_str(d, "interval").map_err(|e| config_err(py, e))? {
            Some(s) => parse_interval(&s).map_err(|e| config_err(py, e))?,
            None => BarInterval::Day,
        },
        None => BarInterval::Day,
    };

    cfg.dataset = Some(DatasetConfig {
        source: dataset_source.clone(),
        hash: None,
        interval,
        start: bars.first().map(|b| b.timestamp),
        end: bars.last().map(|b| b.timestamp),
        bar_count: Some(bars.len() as u64),
    });
    cfg.strategy = Some(StrategyConfig {
        name: class_name.clone(),
        source: strategy_source,
        source_hash: None,
        parameters: params,
    });

    cfg.validate().map_err(|e| config_err(py, e))?;

    let mut engine = Engine::new(cfg.clone()).map_err(|e| engine_err(py, e))?;
    let mut py_strategy = PyStrategy::new(
        strategy.clone().unbind(),
        class_name,
        cfg.instrument.symbol.clone(),
    );

    match engine.run(&bars, &mut py_strategy) {
        Ok(result) => {
            let mut rr = RunResult {
                config: cfg,
                bars,
                result,
                bars_per_year,
                dataset_source,
                artifact_dir: None,
                metrics_cache: RefCell::new(None),
            };
            if let Some(out) = output {
                let _ = rr.save(py, out)?; // persists (create-only); raises on conflict
            }
            Ok(rr)
        }
        Err(e) => {
            // Best-effort failure artifacts when an output dir was requested.
            if let Some(out) = &output {
                let _ = persistence::persist_failed_run(
                    std::path::Path::new(out),
                    &cfg,
                    &bars,
                    engine.events(),
                    &e.to_string(),
                    &dataset_source,
                );
            }
            match &e {
                EngineError::StrategyFailure {
                    message,
                    bar_index,
                    code,
                    details: failure_details,
                } => Err(strategy_err(
                    py,
                    message,
                    *bar_index,
                    code.as_deref(),
                    failure_details.as_ref(),
                )),
                _ => Err(engine_err(py, e)),
            }
        }
    }
}

/// Loads a persisted canonical run directory and returns the replay payload
/// consumed by the frontend (canonical events + bars when recoverable).
#[pyfunction]
#[pyo3(name = "replay_payload")]
fn replay_payload_fn(py: Python<'_>, dir_path: &str) -> PyResult<PyObject> {
    let dir = std::path::PathBuf::from(dir_path);
    let loaded = replay_mod::load_persisted_run(&dir).map_err(|e| match &e {
        replay_mod::ReplayLoadError::MissingArtifact { path, .. } => coded(
            py,
            PyFileNotFoundError::new_err(format!("persisted run not found: {path}")),
            "REPLAY_RUN_NOT_FOUND",
            Some(details(py, vec![("path", path.clone().into_py(py))])),
        ),
        replay_mod::ReplayLoadError::InvalidRunJson { path, .. } => coded(
            py,
            PyValueError::new_err(format!(
                "invalid run artifacts at {path}: {e} (delete and re-run, or pass a valid run directory)"
            )),
            "REPLAY_ARTIFACTS_INVALID",
            Some(details(py, vec![("path", path.clone().into_py(py))])),
        ),
        replay_mod::ReplayLoadError::InvalidEventLine { path, line, .. } => coded(
            py,
            PyValueError::new_err(format!(
                "invalid events.jsonl at {path} (line {line}): {e}"
            )),
            "REPLAY_ARTIFACTS_INVALID",
            Some(details(
                py,
                vec![
                    ("path", path.clone().into_py(py)),
                    ("line", (*line).into_py(py)),
                ],
            )),
        ),
    })?;
    let meta = replay_mod::run_meta_from_run_json(&loaded.run_json);

    // Recover canonical bars only when the recorded dataset source still
    // exists and matches the persisted dataset hash.
    let bars = recover_persisted_bars(&loaded.run_json);

    let payload = replay_mod::replay_payload(
        &bars,
        &loaded.events,
        &meta,
        loaded.metrics.as_ref(),
    );
    value_to_py(py, &payload)
}

/// Best-effort recovery of dataset bars for a persisted run (see CLI).
fn recover_persisted_bars(run_json: &serde_json::Value) -> Vec<Bar> {
    let sha = match run_json["dataset"]["sha256"].as_str() {
        Some(s) => s,
        None => return Vec::new(),
    };
    let source = match run_json["dataset"]["source"].as_str() {
        Some(s) => s,
        None => return Vec::new(),
    };
    if !source.to_lowercase().ends_with(".csv") {
        return Vec::new();
    }
    match CsvReader::load(source) {
        Ok(bars) => match persistence::dataset_identity(&bars) {
            Ok(identity) if identity.sha256 == sha => bars,
            _ => Vec::new(),
        },
        Err(_) => Vec::new(),
    }
}

/// Native extension module.
#[pymodule]
fn _observa(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add_function(wrap_pyfunction!(replay_payload_fn, m)?)?;
    m.add_class::<RunResult>()?;
    m.add_class::<HistoryView>()?;
    m.add_class::<HistoryIter>()?;
    Ok(())
}
