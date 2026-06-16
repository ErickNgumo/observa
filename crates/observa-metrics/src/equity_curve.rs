use chrono::{DateTime, Utc};

/// A single point on the equity curve
#[derive(Debug, Clone)]
pub struct EquityPoint {
    pub timestamp: DateTime<Utc>,
    pub equity:    f64,
}

/// Tracks equity over time, built from PortfolioSnapshotEvents
#[derive(Debug, Default)]
pub struct EquityCurve {
    pub points: Vec<EquityPoint>,
}

impl EquityCurve {
    pub fn new() -> Self {
        Self { points: Vec::new() }
    }

    /// Add a new equity point
    pub fn push(&mut self, timestamp: DateTime<Utc>, equity: f64) {
        // Avoid duplicate timestamps
        if let Some(last) = self.points.last() {
            if last.timestamp == timestamp {
                return;
            }
        }
        self.points.push(EquityPoint { timestamp, equity });
    }

    /// Returns the initial equity (first point)
    pub fn initial(&self) -> Option<f64> {
        self.points.first().map(|p| p.equity)
    }

    /// Returns the final equity (last point)
    pub fn final_equity(&self) -> Option<f64> {
        self.points.last().map(|p| p.equity)
    }

    /// Returns total return as a percentage
    pub fn total_return_pct(&self) -> f64 {
        match (self.initial(), self.final_equity()) {
            (Some(initial), Some(final_eq)) if initial > 0.0 => {
                ((final_eq - initial) / initial) * 100.0
            }
            _ => 0.0,
        }
    }

    /// Returns equity values as a plain Vec<f64>
    /// Used by Sharpe and other calculations
    pub fn values(&self) -> Vec<f64> {
        self.points.iter().map(|p| p.equity).collect()
    }

    pub fn is_empty(&self) -> bool {
        self.points.is_empty()
    }

    pub fn len(&self) -> usize {
        self.points.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn ts(offset_secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(1640000000 + offset_secs, 0).unwrap()
    }

    #[test]
    fn total_return_calculated_correctly() {
        let mut curve = EquityCurve::new();
        curve.push(ts(0),    10_000.0);
        curve.push(ts(3600), 11_000.0);
        curve.push(ts(7200), 10_500.0);

        let ret = curve.total_return_pct();
        assert!((ret - 5.0).abs() < 0.001); // 5% return
    }

    #[test]
    fn duplicate_timestamps_ignored() {
        let mut curve = EquityCurve::new();
        curve.push(ts(0), 10_000.0);
        curve.push(ts(0), 11_000.0); // same timestamp — ignored
        assert_eq!(curve.len(), 1);
        assert_eq!(curve.final_equity(), Some(10_000.0));
    }

    #[test]
    fn empty_curve_returns_zero() {
        let curve = EquityCurve::new();
        assert_eq!(curve.total_return_pct(), 0.0);
        assert!(curve.initial().is_none());
    }
}