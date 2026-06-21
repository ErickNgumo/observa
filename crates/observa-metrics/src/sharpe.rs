// Calculates the Sharpe ratio from an equity curve.
///
/// Sharpe = (mean return - risk free rate) / std dev of returns
///
/// We use period returns (equity[i] / equity[i-1] - 1)
/// and annualise assuming 252 trading days.
pub fn sharpe_ratio(
    equity_values: &[f64],
    risk_free_rate: f64,   // annual, e.g. 0.05 for 5%
    periods_per_year: f64, // e.g. 252 for daily, 96 for 15min bars
) -> Option<f64> {
    // Require a meaningful minimum sample size —
    // Sharpe on fewer than 30 periods is unreliable
    if equity_values.len() < 30 {
        return None;
    }

    // Calculate period returns
    let returns: Vec<f64> = equity_values
        .windows(2)
        .map(|w| w[1] / w[0] - 1.0)
        .collect();

    if returns.is_empty() {
        return None;
    }

    // Mean return
    let mean = returns.iter().sum::<f64>() / returns.len() as f64;

    // Standard deviation
    let variance = returns
        .iter()
        .map(|r| (r - mean).powi(2))
        .sum::<f64>()
        / returns.len() as f64;

    let std_dev = variance.sqrt();

    if std_dev == 0.0 {
        return None;
    }

    // Period risk free rate
    let period_rf = risk_free_rate / periods_per_year;

    // Annualised Sharpe
    let sharpe = ((mean - period_rf) / std_dev) * periods_per_year.sqrt();

    Some(sharpe)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sharpe_requires_at_least_two_points() {
        assert!(sharpe_ratio(&[10_000.0], 0.0, 252.0).is_none());
        assert!(sharpe_ratio(&[], 0.0, 252.0).is_none());
    }

    #[test]
    fn sharpe_positive_for_growing_equity() {
        // Steadily growing equity should have positive Sharpe
        let equity: Vec<f64> = (0..50)
            .map(|i| 10_000.0 + i as f64 * 100.0).
            collect();
        let sharpe = sharpe_ratio(&equity, 0.0, 252.0);
        assert!(sharpe.is_some());
        assert!(sharpe.unwrap() > 0.0);
    }

    #[test]
    fn sharpe_negative_for_declining_equity() {
        // Steadily declining equity should have negative Sharpe
        let equity: Vec<f64> = (0..50)
            .map(|i| 10_000.0 - i as f64 * 100.0)
            .collect();
        let sharpe = sharpe_ratio(&equity, 0.0, 252.0);
        assert!(sharpe.is_some());
        assert!(sharpe.unwrap() < 0.0);
    }
}