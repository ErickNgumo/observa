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