use pyo3::prelude::*;
use pyo3::types::PyDict;
use observa_core::types::Direction;
use observa_engine::strategy::StrategySignal;
use crate::error::BridgeError;

/// Converts a Python signal dict into a Rust StrategySignal.
///
/// The trader returns a dict from on_bar() like:
///   {
///     "direction": "buy" | "sell" | "close",
///     "size":      1.0,
///     "price":     1.1376,   # optional
///     "sl":        1.1350,   # optional
///     "tp":        1.1420,   # optional
///     "reason":    "EMA crossover",  # optional
///   }
pub fn signal_from_py(
    py: Python,
    obj: &Bound<PyAny>,
) -> Result<StrategySignal, BridgeError> {
    // The signal must be a dict
    let dict = obj.downcast::<PyDict>().map_err(|_| {
        BridgeError::InvalidSignal(
            "signal must be a dict".to_string()
        )
    })?;

    // direction is required
    let direction_str: String = dict
        .get_item("direction")
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            "'direction' key is required".to_string()
        ))?
        .extract()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?;

    let direction = match direction_str.to_lowercase().as_str() {
        "buy"   => Direction::Buy,
        "sell"  => Direction::Sell,
        "close" => Direction::Close,
        other   => return Err(BridgeError::InvalidSignal(
            format!("unknown direction '{}' — use 'buy', 'sell', or 'close'", other)
        )),
    };

    // size is required
    let size: f64 = dict
        .get_item("size")
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?
        .ok_or_else(|| BridgeError::InvalidSignal(
            "'size' key is required".to_string()
        ))?
        .extract()
        .map_err(|e| BridgeError::InvalidSignal(e.to_string()))?;

    // price is optional — defaults to 0.0
    // (engine uses current bar close if 0.0)
    let intended_price: f64 = extract_optional_f64(
        dict, "price", py
    )?.unwrap_or(0.0);

    // sl and tp are optional
    let sl = extract_optional_f64(dict, "sl", py)?;
    let tp = extract_optional_f64(dict, "tp", py)?;

    // reason is optional
    let reason: String = dict
        .get_item("reason")
        .ok()
        .flatten()
        .and_then(|v| v.extract::<String>().ok())
        .unwrap_or_else(|| "Python strategy signal".to_string());

    Ok(StrategySignal {
        direction,
        size,
        intended_price,
        sl,
        tp,
        reason,
    })
}

/// Extracts an optional f64 from a Python dict.
/// Returns None if the key is absent or is Python None.
fn extract_optional_f64(
    dict: &Bound<PyDict>,
    key: &str,
    _py: Python,
) -> Result<Option<f64>, BridgeError> {
    match dict.get_item(key) {
        Ok(Some(val)) => {
            if val.is_none() {
                Ok(None)
            } else {
                val.extract::<f64>()
                    .map(Some)
                    .map_err(|e| BridgeError::InvalidSignal(
                        format!("field '{}': {}", key, e)
                    ))
            }
        }
        Ok(None) => Ok(None),
        Err(e)   => Err(BridgeError::InvalidSignal(e.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::Python;
    use pyo3::types::PyDict;

    #[test]
    fn buy_signal_parses_correctly() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let dict = PyDict::new_bound(py);
            dict.set_item("direction", "buy").unwrap();
            dict.set_item("size",      1.0).unwrap();
            dict.set_item("price",     1.1376).unwrap();
            dict.set_item("sl",        1.1350).unwrap();
            dict.set_item("tp",        1.1420).unwrap();
            dict.set_item("reason",    "test").unwrap();

            let signal = signal_from_py(
                py, dict.as_any()
            ).unwrap();

            assert_eq!(signal.direction, Direction::Buy);
            assert_eq!(signal.size, 1.0);
            assert_eq!(signal.sl,   Some(1.1350));
            assert_eq!(signal.tp,   Some(1.1420));
        });
    }

    #[test]
    fn close_signal_parses_correctly() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let dict = PyDict::new_bound(py);
            dict.set_item("direction", "close").unwrap();
            dict.set_item("size", 1.0).unwrap();

            let signal = signal_from_py(
                py, dict.as_any()
            ).unwrap();
            assert_eq!(signal.direction, Direction::Close);
        });
    }

    #[test]
    fn missing_direction_returns_error() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let dict = PyDict::new_bound(py);
            dict.set_item("size", 1.0).unwrap();
            let result = signal_from_py(py, dict.as_any());
            assert!(result.is_err());
        });
    }

    #[test]
    fn invalid_direction_returns_error() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let dict = PyDict::new_bound(py);
            dict.set_item("direction", "long").unwrap();
            dict.set_item("size", 1.0).unwrap();
            let result = signal_from_py(py, dict.as_any());
            assert!(result.is_err());
        });
    }
}