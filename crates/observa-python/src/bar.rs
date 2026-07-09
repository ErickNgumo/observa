use pyo3::prelude::*;
use pyo3::types::PyDict;
use observa_core::bar::Bar;
use crate::error::BridgeError;

/// Converts a Rust Bar into a Python dict.
///
/// The trader's on_bar() receives this dict:
///   bar.open, bar.high, bar.low, bar.close,
///   bar.volume, bar.timestamp
pub fn bar_to_py<'py>(
    py: Python<'py>,
    bar: &Bar,
) -> Result<Bound<'py, PyDict>, BridgeError> {
    let dict = PyDict::new_bound(py);

    dict.set_item("open",      bar.open)?;
    dict.set_item("high",      bar.high)?;
    dict.set_item("low",       bar.low)?;
    dict.set_item("close",     bar.close)?;
    dict.set_item("timestamp", bar.timestamp.to_rfc3339())?;

    match bar.volume {
        Some(v) => dict.set_item("volume", v)?,
        None    => dict.set_item("volume", py.None())?,
    }

    Ok(dict)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use pyo3::Python;

    #[test]
    fn bar_converts_to_py_dict() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let bar = Bar::new(
                Utc::now(),
                1.1376,
                1.13787,
                1.1376,
                1.13786,
                Some(278.19),
            );
            let dict = bar_to_py(py, &bar).unwrap();
            let open: f64 = dict.get_item("open")
                .unwrap().unwrap()
                .extract().unwrap();
            assert!((open - 1.1376).abs() < 0.000001);
        });
    }
}