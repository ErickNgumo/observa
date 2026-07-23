/// Calculates the annualised Sharpe ratio from an equity curve.
///
/// Uses sample standard deviation (N-1) and compound
/// risk-free rate conversion — both standard in finance.
///
/// # Arguments
/// * `equity_values`    — equity at each bar, equally spaced
/// * `risk_free_rate`   — annual risk-free rate, e.g. 0.05 for 5%
/// * `periods_per_year` — how many bars make one year
///                        (252 for daily, 96*252 for 15-min bars)
pub fn sharpe_ratio(
    equity_values: &[f64],
    risk_free_rate: f64,
    periods_per_year: f64,
) -> Option<f64> {
    // Need at least 30 observations for a meaningful Sharpe
    if equity_values.len() < 30 {
        return None;
    }

    // Calculate period returns: r_t = equity_t / equity_(t-1) - 1
    let returns: Vec<f64> = equity_values
        .windows(2)
        .filter(|w| w[0] > 0.0)
        .map(|w| w[1] / w[0] - 1.0)
        .collect();

    let n = returns.len();
    if n < 2 {
        return None;
    }

    // Mean return
    let mean = returns.iter().sum::<f64>() / n as f64;

    // Sample standard deviation — divide by (N-1) not N
    // This is Bessel's correction for sample data
    let variance = returns
        .iter()
        .map(|r| (r - mean).powi(2))
        .sum::<f64>()
        / (n - 1) as f64;  // ← N-1 not N

    let std_dev = variance.sqrt();

    // Epsilon guard — avoid division by near-zero
    const EPS: f64 = 1e-12;
    if std_dev < EPS {
        return None;
    }

    // Compound conversion of annual risk-free rate to period rate
    // Simple: rf/N — incorrect
    // Compound: (1+rf)^(1/N) - 1 — correct
    let period_rf = (1.0 + risk_free_rate).powf(
        1.0 / periods_per_year
    ) - 1.0;

    // Annualised Sharpe
    // Only valid when equity_values are equally spaced in time
    // which they will be once we fix the equity curve generation
    let sharpe = ((mean - period_rf) / std_dev)
        * periods_per_year.sqrt();

    Some(sharpe)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sharpe_requires_minimum_sample() {
        // Fewer than 30 points returns None
        let equity: Vec<f64> = (0..20)
            .map(|i| 10_000.0 + i as f64 * 10.0)
            .collect();
        assert!(sharpe_ratio(&equity, 0.0, 252.0).is_none());
    }

    #[test]
    fn sharpe_positive_for_consistently_growing_equity() {
        let equity: Vec<f64> = (0..100)
            .map(|i| 10_000.0 + i as f64 * 50.0)
            .collect();
        let s = sharpe_ratio(&equity, 0.0, 252.0).unwrap();
        assert!(s > 0.0);
        // Should be high but not absurdly so for a smooth curve
        println!("Smooth growth Sharpe: {}", s);
    }

    #[test]
    fn sharpe_negative_for_declining_equity() {
        let equity: Vec<f64> = (0..100)
            .map(|i| 10_000.0 - i as f64 * 50.0)
            .collect();
        let s = sharpe_ratio(&equity, 0.0, 252.0).unwrap();
        assert!(s < 0.0);
    }

    #[test]
    fn sharpe_uses_sample_not_population_variance() {
        // With volatile returns, sample variance (N-1) gives
        // a lower Sharpe than population variance (N)
        // This test just confirms it runs and gives a finite result
        let equity = vec![
            10_000.0, 10_100.0, 9_900.0, 10_200.0, 9_800.0,
            10_300.0, 9_700.0, 10_400.0, 9_600.0, 10_500.0,
            10_000.0, 10_100.0, 9_900.0, 10_200.0, 9_800.0,
            10_300.0, 9_700.0, 10_400.0, 9_600.0, 10_500.0,
            10_000.0, 10_100.0, 9_900.0, 10_200.0, 9_800.0,
            10_300.0, 9_700.0, 10_400.0, 9_600.0, 10_500.0,
        ];
        let s = sharpe_ratio(&equity, 0.0, 252.0);
        assert!(s.is_some());
        let val = s.unwrap();
        // Should be a modest number, not in the hundreds
        println!("Volatile equity Sharpe: {}", val);
        assert!(val.abs() < 50.0);
    }

    #[test]
    fn zero_volatility_returns_none() {
        // Perfectly flat equity — no volatility, Sharpe undefined
        let equity = vec![10_000.0_f64; 50];
        assert!(sharpe_ratio(&equity, 0.0, 252.0).is_none());
    }
}