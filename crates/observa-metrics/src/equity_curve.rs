use chrono::{DateTime, Utc};

/// A single point on the equity curve
#[derive(Debug, Clone)]
pub struct EquityPoint {
    pub timestamp: DateTime<Utc>,
    pub equity: f64,
}

/// Tracks equity over time, built from PortfolioSnapshotEvents
#[derive(Debug, Default)]
pub struct EquityCurve{
    pub points: Vec<EquityPoint>,
}

impl EquityCurve {
    pub fn new() -> Self{
        Self { points: Vec::new()}
    }

    // Add a new equity point
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
        self.points.last().map(|p|p.equity)
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
    /// Used by sharpe and other calculations
    pub fn values(&self) -> Vec<f64> {
        self.points.iter().map(|p|p.equity).collect()
    }

    pub fn is_empty(&self) -> bool {
        self.points.is_empty()
    }

    pub fn len(&self) -> usize {
        self.points.len()
    }
}

