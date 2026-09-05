//! Observa Python extension (`observa._observa`).
//!
//! This is the thin, canonical binding: Python strategies are wrapped in a
//! Rust [`PyStrategy`] that implements the Engine's `Strategy` trait, so there
//! is exactly one backtesting loop — the canonical [`Engine`]. No execution,
//! portfolio, or event logic is reimplemented here.

use std::collections::BTreeMap;

use chrono::{DateTime, TimeZone, Utc};
use pyo3::exceptions::{PyFileExistsError, PyFileNotFoundError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};
use serde_json::{json, Value};

use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig, StrategyConfig,
};
use observa_core::types::{Direction, OrderKind};
use observa_data::csv_reader::CsvReader;
use observa_engine::engine::{Engine, RunResult as EngineRunResult};
use observa_engine::persistence::{self, PersistenceError};
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use observa_metrics::metrics::MetricsEngine;

// ────────────────────────────────────────────────
// Error mapping
// ────────────────────────────────────────────────

fn config_err(e: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(format!("invalid configuration: {e}"))
}

fn data_err(e: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(format!("invalid data: {e}"))
}

fn engine_err(e: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(format!("engine error: {e}"))
}

fn map_persistence(e: PersistenceError) -> PyErr {
    match e {
        PersistenceError::OutputAlreadyExists { path } => {
            PyFileExistsError::new_err(format!("output directory already exists: {path}"))
        }
        other => PyRuntimeError::new_err(format!("persistence error: {other}")),
    }
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

fn timestamp_from_py(obj: &Bound<'_, pyo3::PyAny>) -> PyResult<DateTime<Utc>> {
    if let Ok(s) = obj.extract::<String>() {
        return chrono::DateTime::parse_from_rfc3339(&s)
            .map(|t| t.with_timezone(&Utc))
            .or_else(|_| {
                chrono::NaiveDateTime::parse_from_str(&s, "%Y-%m-%d %H:%M:%S")
                    .map(|n| Utc.from_utc_datetime(&n))
            })
            .map_err(|_| PyValueError::new_err(format!("cannot parse timestamp '{s}'")));
    }
    if let Ok(secs) = obj.extract::<f64>() {
        return Utc
            .timestamp_opt(secs.floor() as i64, 0)
            .single()
            .ok_or_else(|| PyValueError::new_err(format!("invalid epoch timestamp {secs}")));
    }
    Err(PyValueError::new_err(
        "timestamp must be an RFC 3339 string or epoch seconds",
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
        let volume = match d.get_item("volume")? {
            Some(v) if !v.is_none() => Some(v.extract::<f64>()?),
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
            Some(items[5].extract::<f64>()?)
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
    if let Ok(path) = data.downcast::<PyString>() {
        let path: String = path.extract()?;
        return CsvReader::load(&path).map_err(|e| {
            if let observa_data::error::DataError::FileNotFound { path, .. } = &e {
                return PyFileNotFoundError::new_err(format!("data file not found: {path}"));
            }
            data_err(e)
        });
    }
    if let Ok(list) = data.downcast::<PyList>() {
        let mut bars = Vec::with_capacity(list.len());
        for item in list.iter() {
            bars.push(bar_from_py(&item)?);
        }
        return Ok(bars);
    }
    Err(PyValueError::new_err(
        "data must be a CSV file path or a list of bars (dicts or sequences)",
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
    last_error: Option<String>,
}

impl PyStrategy {
    fn new(instance: PyObject, class_name: String, symbol: String) -> Self {
        Self {
            instance,
            class_name,
            symbol,
            last_error: None,
        }
    }
}

fn bar_to_py_dict<'py>(py: Python<'py>, bar: &Bar) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("open", bar.open)?;
    d.set_item("high", bar.high)?;
    d.set_item("low", bar.low)?;
    d.set_item("close", bar.close)?;
    d.set_item("timestamp", bar.timestamp.to_rfc3339())?;
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
    let reason = match d.get_item("reason")? {
        Some(v) if !v.is_none() => v.extract::<String>()?,
        _ => "Python strategy signal".to_string(),
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
            self.last_error = Some(format!(
                "strategy '{}' initialize() failed: {e}",
                self.class_name
            ));
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
                    self.last_error = Some(format!("bar conversion failed: {e}"));
                    return vec![];
                }
            };
            let py_portfolio = match portfolio_to_py_dict(py, portfolio, &self.symbol) {
                Ok(d) => d,
                Err(e) => {
                    self.last_error = Some(format!("portfolio conversion failed: {e}"));
                    return vec![];
                }
            };
            let py_history = PyList::empty_bound(py);
            for h in history {
                if let Ok(d) = bar_to_py_dict(py, h) {
                    py_history.append(d).ok();
                }
            }

            let result =
                match self
                    .instance
                    .call_method1(py, "on_bar", (py_bar, py_portfolio, py_history))
                {
                    Ok(r) => r,
                    Err(e) => {
                        self.last_error = Some(format!(
                            "strategy '{}' on_bar() failed: {e}",
                            self.class_name
                        ));
                        return vec![];
                    }
                };

            // Accept either a plain list of signal dicts or
            // {'signals': [...]} (drawings are ignored for the MVP).
            let list_opt = if let Ok(d) = result.downcast_bound::<PyDict>(py) {
                d.get_item("signals").ok().flatten()
            } else {
                Some(result.clone_ref(py).into_bound(py))
            };
            let mut out = Vec::new();
            if let Some(list_obj) = list_opt {
                if let Ok(list) = list_obj.downcast::<PyList>() {
                    for item in list.iter() {
                        match signal_from_py(&item) {
                            Ok(s) => out.push(s),
                            Err(e) => {
                                self.last_error = Some(format!(
                                    "strategy '{}' returned an invalid signal: {e}",
                                    self.class_name
                                ));
                            }
                        }
                    }
                } else if !list_obj.is_none() {
                    self.last_error = Some(format!(
                        "strategy '{}' on_bar() must return a list or a dict with 'signals'",
                        self.class_name
                    ));
                }
            }
            out
        })
    }

    fn take_strategy_error(&mut self) -> Option<String> {
        self.last_error.take()
    }

    fn teardown(&mut self) {
        Python::with_gil(|py| {
            if let Err(e) = self.instance.call_method0(py, "teardown") {
                self.last_error = Some(format!(
                    "strategy '{}' teardown() failed: {e}",
                    self.class_name
                ));
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
        value_to_py(py, &metrics_value(&self.result, self.bars_per_year))
    }

    /// Persists the canonical artifacts (run.json / events.jsonl /
    /// metrics.json) to `output_dir`. Create-only: refuses to overwrite.
    fn save(&mut self, output_dir: String) -> PyResult<String> {
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
        .map_err(map_persistence)?;
        self.artifact_dir = Some(dir.display().to_string());
        Ok(dir.display().to_string())
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
    strategy: &Bound<'_, pyo3::PyAny>,
    data: &Bound<'_, pyo3::PyAny>,
    config: Option<&Bound<'_, PyDict>>,
    output: Option<String>,
    bars_per_year: f64,
) -> PyResult<RunResult> {
    let bars = bars_from_py(data)?;

    let mut cfg = match config {
        Some(d) => config_from_dict(d)?,
        None => BacktestConfig::default(),
    };

    // Strategy identity + parameters (resolved from the config dict).
    let class_name = strategy
        .getattr("__class__")
        .and_then(|c| c.getattr("__name__"))
        .and_then(|n| n.extract::<String>())
        .unwrap_or_else(|_| "Strategy".to_string());
    let params = match config {
        Some(d) => params_from_dict(d)?,
        None => BTreeMap::new(),
    };
    let strategy_source = match config {
        Some(d) => opt_str(d, "strategy_source")?,
        None => None,
    };
    let dataset_source = match config {
        Some(d) => opt_str(d, "dataset_source")?.unwrap_or_else(|| "python".to_string()),
        None => "python".to_string(),
    };
    let interval = match config {
        Some(d) => match opt_str(d, "interval")? {
            Some(s) => parse_interval(&s)?,
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

    cfg.validate().map_err(config_err)?;

    let mut engine = Engine::new(cfg.clone()).map_err(engine_err)?;
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
            };
            if let Some(out) = output {
                let _ = rr.save(out)?; // persists (create-only); raises on conflict
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
            Err(engine_err(e))
        }
    }
}

/// Native extension module.
#[pymodule]
fn _observa(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add_class::<RunResult>()?;
    Ok(())
}
