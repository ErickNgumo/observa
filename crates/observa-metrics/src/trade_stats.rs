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