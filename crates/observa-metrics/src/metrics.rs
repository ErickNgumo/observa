use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::drawdown::{DrawdownPeriod, DrawdownTracker};
use crate::equity_curve::EquityCurve;
use crate::trade_stats::TradeStats;
use crate::sharpe::sharpe_ratio;
use crate::calmar::{annualise_return, calmar_ratio};

/// The complete metrics report for a run.
/// Assembled from equity curve and trade statistics.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricsReport {
    // ── Return metrics ─────────────────────────
    pub total_return_pct:      f64,
    pub annualised_return_pct: f64,

    // ── Risk metrics ───────────────────────────
    pub max_drawdown_pct:      f64,
    pub max_drawdown_start:    Option<DateTime<Utc>>,
    pub max_drawdown_end:      Option<DateTime<Utc>>,
    pub current_drawdown_pct:  f64,
    pub sharpe_ratio:          Option<f64>,
    pub calmar_ratio:          Option<f64>,

    // ── Trade statistics ───────────────────────
    pub total_trades:          u64,
    pub winning_trades:        u64,
    pub losing_trades:         u64,
    pub win_rate_pct:          f64,
    pub avg_win:               f64,
    pub avg_loss:              f64,
    pub profit_factor:         f64,
    pub expectancy:            f64,
    pub largest_win:           f64,
    pub largest_loss:          f64,
}

/// Assembles and updates metrics incrementally during a run
pub struct MetricsEngine {
    pub equity_curve:     EquityCurve,
    pub trade_stats:      TradeStats,
    pub drawdown_tracker: DrawdownTracker,
    initial_balance:      f64,
    bars_per_year:        f64,
    total_bars:           usize,
}

impl MetricsEngine {
    /// Creates a new MetricsEngine
    /// 
    /// 'bars_per_year' - how many bars make one trading year
    /// for 15 -minute bar: 96 bars/day * 252 days = 24,192
    pub fn new(initial_balance: f64, bars_per_year: f64) -> Self {
        Self {
            equity_curve:     EquityCurve::new(),
            trade_stats:      TradeStats::new(),
            drawdown_tracker:  DrawdownTracker::new(initial_balance),
            initial_balance,
            bars_per_year,
            total_bars: 0,
        }
    }

    /// Call this for every PortfolioSnapshotEvent
    pub fn on_snapshot(&mut self, timestamp: DateTime<Utc>, equity: f64) {
        self.equity_curve.push(timestamp, equity);
        self.drawdown_tracker.update(timestamp, equity);
        self.total_bars += 1;
    }

    /// Call this for every PositionClosedEvent
    pub fn on_trade_closed(&mut self, pnl: f64) {
        self.trade_stats.record(pnl);
    }

    /// Builds the complete metrics report from current state
    pub fn report(&self) -> MetricsReport {
        let total_return_pct = self.equity_curve.total_return_pct();

        let annualised_return_pct = annualise_return(
            total_return_pct,
            self.total_bars,
            self.bars_per_year,
        );

        let (max_dd_pct, max_dd_start, max_dd_end) =
            match &self.drawdown_tracker.max_drawdown {
                Some(dd) => (dd.depth_pct, Some(dd.peak_time), Some(dd.trough_time)),
                None     => (0.0, None, None),
            };

        let sharpe = sharpe_ratio(
            &self.equity_curve.values(),
            0.0,               // risk free rate
            self.bars_per_year,
        );

        let calmar = calmar_ratio(annualised_return_pct, max_dd_pct);

        MetricsReport {
            total_return_pct,
            annualised_return_pct,
            max_drawdown_pct:     max_dd_pct,
            max_drawdown_start:   max_dd_start,
            max_drawdown_end:     max_dd_end,
            current_drawdown_pct: self.drawdown_tracker.current_drawdown_pct,
            sharpe_ratio:         sharpe,
            calmar_ratio:         calmar,
            total_trades:         self.trade_stats.total_trades,
            winning_trades:       self.trade_stats.winning_trades,
            losing_trades:        self.trade_stats.losing_trades,
            win_rate_pct:         self.trade_stats.win_rate_pct(),
            avg_win:              self.trade_stats.avg_win(),
            avg_loss:             self.trade_stats.avg_loss(),
            profit_factor:        self.trade_stats.profit_factor(),
            expectancy:           self.trade_stats.expectancy(),
            largest_win:          self.trade_stats.largest_win,
            largest_loss:         self.trade_stats.largest_loss,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn ts(offset: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(1640000000 + offset, 0).unwrap()
    }

    #[test]
    fn full_metrics_report_assembles_correctly() {
        let mut engine = MetricsEngine::new(10_000.0, 24_192.0);

        // Simulate equity curve
        engine.on_snapshot(ts(0),     10_000.0);
        engine.on_snapshot(ts(900),   10_500.0);
        engine.on_snapshot(ts(1800),   9_800.0);
        engine.on_snapshot(ts(2700),  10_200.0);
        engine.on_snapshot(ts(3600),  11_000.0);

        // Simulate trades
        engine.on_trade_closed(500.0);
        engine.on_trade_closed(-200.0);
        engine.on_trade_closed(700.0);

        let report = engine.report();

        // Total return: (11000 - 10000) / 10000 = 10%
        assert!((report.total_return_pct - 10.0).abs() < 0.001);

        // Max drawdown: 10500 → 9800 = 6.67%
        assert!(report.max_drawdown_pct > 0.0);
        assert!(report.max_drawdown_pct < 10.0);

        // Trade stats
        assert_eq!(report.total_trades,   3);
        assert_eq!(report.winning_trades, 2);
        assert_eq!(report.losing_trades,  1);
        assert!((report.win_rate_pct - 66.67).abs() < 0.1);
        assert!(report.profit_factor > 1.0);
    }
}


