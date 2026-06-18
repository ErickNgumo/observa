/// Calculates the Calmar ratio.
///
/// Calmar = Annualised Return / Max Drawdown %
///
/// A Calmar > 1.0 means the strategy earns more per year
/// than its worst drawdown percentage.
pub fn calmar_ratio(
    annualised_return_pct: f64,
    max_drawdown_pct:      f64,
) -> Option<f64> {
    if max_drawdown_pct <= 0.0 {
        return None; // No drawdown — ratio undefined
    }
    Some(annualised_return_pct / max_drawdown_pct)
}

/// Annualises a total return given the number of bars
/// and bars per year.
pub fn annualise_return(
    total_return_pct: f64,
    total_bars:       usize,
    bars_per_year:    f64,
) -> f64 {
    if total_bars == 0 {
        return 0.0;
    }
    let years = total_bars as f64 / bars_per_year;
    if years <= 0.0 {
        return 0.0;
    }
    // Compound annualisation
    let growth_factor = 1.0 + total_return_pct / 100.0;
    (growth_factor.powf(1.0 / years) - 1.0) * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calmar_undefined_without_drawdown() {
        assert!(calmar_ratio(20.0, 0.0).is_none());
    }

    #[test]
    fn calmar_calculated_correctly() {
        // 20% annual return, 10% max drawdown = Calmar of 2.0
        let calmar = calmar_ratio(20.0, 10.0).unwrap();
        assert!((calmar - 2.0).abs() < 0.001);
    }

    #[test]
    #[test]
    fn annualise_return_one_year() {
        let annual = annualise_return(
            10.0,
            96 * 252,
            96.0 * 252.0,
        );

        assert!((annual - 10.0).abs() < 1e-6);
    }
}