/// Statistics derived from closed trades
#[derive(Debug, Default, Clone)]
pub struct TradeStats {
    pub total_trades:   u64,
    pub winning_trades: u64,
    pub losing_trades:  u64,
    pub gross_profit:   f64,
    pub gross_loss:     f64,
    pub largest_win:    f64,
    pub largest_loss:   f64,
}

impl TradeStats {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record a closed trade's PnL
    pub fn record(&mut self, pnl: f64) {
        self.total_trades += 1;
        if pnl >= 0.0 {
            self.winning_trades += 1;
            self.gross_profit   += pnl;
            if pnl > self.largest_win {
                self.largest_win = pnl;
            }
        } else {
            self.losing_trades += 1;
            self.gross_loss    += pnl.abs();
            if pnl.abs() > self.largest_loss {
                self.largest_loss = pnl.abs();
            }
        }
    }

    /// Win rate as a percentage
    pub fn win_rate_pct(&self) -> f64 {
        if self.total_trades == 0 {
            return 0.0;
        }
        (self.winning_trades as f64 / self.total_trades as f64) * 100.0
    }

    /// Average winning trade
    pub fn avg_win(&self) -> f64 {
        if self.winning_trades == 0 {
            return 0.0;
        }
        self.gross_profit / self.winning_trades as f64
    }

    /// Average losing trade
    pub fn avg_loss(&self) -> f64 {
        if self.losing_trades == 0 {
            return 0.0;
        }
        self.gross_loss / self.losing_trades as f64
    }

    /// Profit factor — gross profit divided by gross loss
    /// > 1.0 means the strategy makes more than it loses
    pub fn profit_factor(&self) -> f64 {
        if self.gross_loss == 0.0 {
            return f64::INFINITY;
        }
        self.gross_profit / self.gross_loss
    }

    /// Expectancy — average PnL per trade
    pub fn expectancy(&self) -> f64 {
        if self.total_trades == 0 {
            return 0.0;
        }
        (self.gross_profit - self.gross_loss) / self.total_trades as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn win_rate_correct() {
        let mut stats = TradeStats::new();
        stats.record(100.0);
        stats.record(-50.0);
        stats.record(200.0);
        stats.record(-75.0);

        assert_eq!(stats.total_trades,   4);
        assert_eq!(stats.winning_trades, 2);
        assert_eq!(stats.losing_trades,  2);
        assert!((stats.win_rate_pct() - 50.0).abs() < 0.001);
    }

    #[test]
    fn profit_factor_correct() {
        let mut stats = TradeStats::new();
        stats.record(300.0);
        stats.record(-100.0);

        // Profit factor = 300 / 100 = 3.0
        assert!((stats.profit_factor() - 3.0).abs() < 0.001);
    }

    #[test]
    fn avg_win_and_loss_correct() {
        let mut stats = TradeStats::new();
        stats.record(100.0);
        stats.record(200.0);
        stats.record(-50.0);
        stats.record(-150.0);

        assert!((stats.avg_win() - 150.0).abs() < 0.001);
        assert!((stats.avg_loss() - 100.0).abs() < 0.001);
    }

    #[test]
    fn expectancy_correct() {
        let mut stats = TradeStats::new();
        stats.record(100.0);
        stats.record(-50.0);

        // Expectancy = (100 - 50) / 2 = 25
        assert!((stats.expectancy() - 25.0).abs() < 0.001);
    }
}