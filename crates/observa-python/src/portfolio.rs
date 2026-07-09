use pyo3::prelude::*;
use pyo3::types::PyDict;
use observa_engine::strategy::PortfolioView;
use crate::error::BridgeError;

/// Converts a Rust PortfolioView into a Python dict.
///
/// The trader's on_bar() receives this as the
/// second argument:
///   portfolio.balance, portfolio.equity,
///   portfolio.has_open_position,
///   portfolio.position_direction,
///   portfolio.position_entry_price,
///   portfolio.unrealised_pnl
pub fn portfolio_to_py<'py>(
    py: Python<'py>,
    portfolio: &PortfolioView,
) -> Result<Bound<'py, PyDict>, BridgeError> {
    let dict = PyDict::new_bound(py);

    dict.set_item("balance",           portfolio.balance)?;
    dict.set_item("equity",            portfolio.equity)?;
    dict.set_item("has_open_position", portfolio.has_open_position)?;
    dict.set_item("unrealised_pnl",    portfolio.unrealised_pnl)?;

    match portfolio.position_direction {
        Some(dir) => dict.set_item(
            "position_direction",
            format!("{:?}", dir),
        )?,
        None => dict.set_item("position_direction", py.None())?,
    }

    match portfolio.position_entry_price {
        Some(price) => dict.set_item("position_entry_price", price)?,
        None        => dict.set_item("position_entry_price", py.None())?,
    }

    Ok(dict)
}

#[cfg(test)]
mod tests {
    use super::*;
    use observa_engine::strategy::PortfolioView;
    use pyo3::Python;

    #[test]
    fn portfolio_converts_to_py_dict() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let view = PortfolioView::empty(10_000.0);
            let dict = portfolio_to_py(py, &view).unwrap();

            let balance: f64 = dict.get_item("balance")
                .unwrap().unwrap()
                .extract().unwrap();
            assert!((balance - 10_000.0).abs() < 0.001);

            let has_pos: bool = dict.get_item("has_open_position")
                .unwrap().unwrap()
                .extract().unwrap();
            assert!(!has_pos);
        });
    }
}
