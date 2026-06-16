use chrono::{DateTime, Utc};
use crate::equity_curve::EquityCurve;

/// A single drawdown period — from peak to trough
#[derive(Debug, Clone)]
pub struct DrawdownPeriod {
    /// When the peak equity occurred
    pub peak_time:   DateTime<Utc>,
    /// Peak equity value
    pub peak_equity: f64,
    /// When the trough occurred
    pub trough_time:   DateTime<Utc>,
    /// Trough equity value
    pub trough_equity: f64,
    /// Drawdown depth as a percentage
    pub depth_pct: f64,
}

impl DrawdownPeriod {
    pub fn new(
        peak_time:     DateTime<Utc>,
        peak_equity:   f64,
        trough_time:   DateTime<Utc>,
        trough_equity: f64,
    ) -> Self {
        let depth_pct = if peak_equity > 0.0 {
            ((peak_equity - trough_equity) / peak_equity) * 100.0
        } else {
            0.0
        };
        Self { peak_time, peak_equity, trough_time, trough_equity, depth_pct }
    }
}

/// Tracks drawdown incrementally as equity points arrive
#[derive(Debug)]
pub struct DrawdownTracker {
    /// Current running peak
    peak_equity: f64,
    peak_time:   Option<DateTime<Utc>>,

    /// Current drawdown trough
    trough_equity: f64,
    trough_time:   Option<DateTime<Utc>>,

    /// The worst drawdown seen so far
    pub max_drawdown: Option<DrawdownPeriod>,

    /// Current drawdown percentage
    pub current_drawdown_pct: f64,
}

impl DrawdownTracker {
    pub fn new(initial_equity: f64) -> Self {
        Self {
            peak_equity:          initial_equity,
            peak_time:            None,
            trough_equity:        initial_equity,
            trough_time:          None,
            max_drawdown:         None,
            current_drawdown_pct: 0.0,
        }
    }

    /// Update tracker with a new equity point.
    /// Call this for every PortfolioSnapshotEvent.
    pub fn update(&mut self, timestamp: DateTime<Utc>, equity: f64) {
        // New peak — reset trough tracking
        if equity >= self.peak_equity {
            self.peak_equity  = equity;
            self.peak_time    = Some(timestamp);
            self.trough_equity = equity;
            self.trough_time   = Some(timestamp);
            self.current_drawdown_pct = 0.0;
            return;
        }

        // Below peak — update trough if new low
        if equity < self.trough_equity {
            self.trough_equity = equity;
            self.trough_time   = Some(timestamp);
        }

        // Calculate current drawdown
        self.current_drawdown_pct = if self.peak_equity > 0.0 {
            ((self.peak_equity - equity) / self.peak_equity) * 100.0
        } else {
            0.0
        };

        // Check if this is the worst drawdown so far
        let is_worst = match &self.max_drawdown {
            None     => true,
            Some(dd) => self.current_drawdown_pct > dd.depth_pct,
        };

        if is_worst {
            if let (Some(pt), Some(tt)) = (self.peak_time, self.trough_time) {
                self.max_drawdown = Some(DrawdownPeriod::new(
                    pt,
                    self.peak_equity,
                    tt,
                    self.trough_equity,
                ));
            }
        }
    }

    /// Compute max drawdown directly from a complete equity curve.
    /// Used for post-run analysis.
    pub fn from_curve(curve: &EquityCurve) -> Option<DrawdownPeriod> {
        if curve.is_empty() {
            return None;
        }

        let initial = curve.points[0].equity;
        let mut tracker = DrawdownTracker::new(initial);

        for point in &curve.points {
            tracker.update(point.timestamp, point.equity);
        }

        tracker.max_drawdown
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use crate::equity_curve::EquityCurve;

    fn ts(offset_secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(1640000000 + offset_secs, 0).unwrap()
    }

    #[test]
    fn identifies_correct_max_drawdown() {
        // Sequence: 10000 → 10500 → 10200 → 9800 → 10100 → 9600 → 10300
        // Max drawdown: 10500 → 9600 = 8.57%
        let mut curve = EquityCurve::new();
        curve.push(ts(0),     10_000.0);
        curve.push(ts(3600),  10_500.0);
        curve.push(ts(7200),  10_200.0);
        curve.push(ts(10800),  9_800.0);
        curve.push(ts(14400), 10_100.0);
        curve.push(ts(18000),  9_600.0);
        curve.push(ts(21600), 10_300.0);

        let dd = DrawdownTracker::from_curve(&curve).unwrap();

        assert!((dd.peak_equity   - 10_500.0).abs() < 0.001);
        assert!((dd.trough_equity -  9_600.0).abs() < 0.001);
        assert!((dd.depth_pct - 8.571).abs() < 0.01);
    }

    #[test]
    fn no_drawdown_on_rising_curve() {
        let mut curve = EquityCurve::new();
        curve.push(ts(0),    10_000.0);
        curve.push(ts(3600), 10_500.0);
        curve.push(ts(7200), 11_000.0);

        let dd = DrawdownTracker::from_curve(&curve);
        // No drawdown — always rising
        assert!(dd.is_none() || dd.unwrap().depth_pct < 0.001);
    }

    #[test]
    fn incremental_update_matches_batch() {
        let mut curve = EquityCurve::new();
        curve.push(ts(0),     10_000.0);
        curve.push(ts(3600),  10_500.0);
        curve.push(ts(7200),   9_800.0);
        curve.push(ts(10800), 10_200.0);

        // Batch
        let batch_dd = DrawdownTracker::from_curve(&curve).unwrap();

        // Incremental
        let mut tracker = DrawdownTracker::new(10_000.0);
        for p in &curve.points {
            tracker.update(p.timestamp, p.equity);
        }
        let incremental_dd = tracker.max_drawdown.unwrap();

        assert!((batch_dd.depth_pct - incremental_dd.depth_pct).abs() < 0.001);
    }
}