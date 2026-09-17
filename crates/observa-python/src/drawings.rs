//! Python → JSON conversion for strategy annotations.
//!
//! The strict validation itself lives in `observa_core::drawings` so the
//! shipped wheel, the dev CLI bridge and Rust tests all enforce exactly the
//! same contract (OBS-AI-02). This module only converts Python objects into
//! the `serde_json::Value` shape the shared parser consumes.

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyString, PyTuple};

use serde_json::Value;

use crate::error::BridgeError;

/// Converts the `drawings` value returned by `on_bar` into a list of JSON
/// values ready for `DrawingRegistry::parse_bar`.
///
/// Only JSON-representable values are accepted; anything else is reported as a
/// bridge error (which the Engine converts into a coded run failure) rather
/// than being silently coerced.
pub fn drawings_from_py(_py: Python, obj: &Bound<PyAny>) -> Result<Vec<Value>, BridgeError> {
    let list = obj
        .downcast::<PyList>()
        .map_err(|_| BridgeError::InvalidSignal("'drawings' must be a list".to_string()))?;
    list.iter()
        .map(|item| {
            py_to_json(&item).map_err(|message| {
                BridgeError::InvalidSignal(format!("'drawings' entry could not be read: {message}"))
            })
        })
        .collect()
}

/// Python value → `serde_json::Value` for the JSON-representable subset.
fn py_to_json(obj: &Bound<PyAny>) -> Result<Value, String> {
    if obj.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(b) = obj.downcast::<PyBool>() {
        return Ok(Value::Bool(b.is_true()));
    }
    if let Ok(i) = obj.extract::<i64>() {
        return Ok(serde_json::json!(i));
    }
    if let Ok(f) = obj.extract::<f64>() {
        return Ok(serde_json::json!(f));
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
    if let Ok(t) = obj.downcast::<PyTuple>() {
        let mut out = Vec::with_capacity(t.len());
        for item in t.iter() {
            out.push(py_to_json(&item)?);
        }
        return Ok(Value::Array(out));
    }
    Err(format!(
        "unsupported value of type '{}'",
        obj.get_type()
            .name()
            .map(|n| n.to_string())
            .unwrap_or_else(|_| "?".to_string())
    ))
}
