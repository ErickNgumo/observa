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

    // All open positions with tickets
    let positions_list = pyo3::types::PyList::empty_bound(py);
    for pos in &portfolio.open_positions {
        let pos_dict = PyDict::new_bound(py);
        pos_dict.set_item("ticket",         &pos.ticket)?;
        pos_dict.set_item("direction",      format!("{:?}", pos.direction))?;
        pos_dict.set_item("size",           pos.size)?;
        pos_dict.set_item("entry_price",    pos.entry_price)?;
        pos_dict.set_item("unrealised_pnl", pos.unrealised_pnl)?;
        pos_dict.set_item("sl",
            pos.sl.map_or_else(|| py.None(), |v| v.into_py(py)))?;
        pos_dict.set_item("tp",
            pos.tp.map_or_else(|| py.None(), |v| v.into_py(py)))?;
        positions_list.append(pos_dict)?;
    }
    dict.set_item("open_positions", positions_list)?;

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
