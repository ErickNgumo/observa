use serde::{Deserialize, Serialize};

/// Defines the contract specifications for a tradeable instrument.
///
/// This struct is the single source of truth for converting
/// between position size (lots/shares/contracts) and monetary
/// values (notional exposure, risk amount, margin).
///
/// Without this, percentage calculations mix units —
/// dividing a quantity (lots) by money (balance) produces
/// a number with no financial meaning.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstrumentSpec {
    /// Instrument identifier e.g. "EURUSD", "XAUUSD", "AAPL"
    pub symbol: String,

    /// Number of base units per lot/contract/share
    ///   Forex standard lot: 100,000
    ///   Gold (oz):          100
    ///   Stocks:             1
    ///   Crypto (BTC):       1
    pub contract_size: f64,

    /// Monetary value of one pip movement per lot
    ///   EURUSD: $10 per pip per standard lot
    ///   XAUUSD: $1 per $0.01 move per oz contract
    ///   Stocks: $0.01 per cent move per share
    pub pip_value: f64,

    /// Number of decimal places in the price
    ///   EURUSD: 5 (1.13456)
    ///   XAUUSD: 2 (1923.45)
    ///   AAPL:   2 (182.50)
    pub price_decimals: u32,

    /// Margin requirement as a fraction of notional value
    ///   0.01  = 1%  margin (100:1 leverage)
    ///   0.02  = 2%  margin (50:1 leverage)
    ///   0.25  = 25% margin (4:1 leverage, typical for stocks)
    ///   1.0   = 100% margin (no leverage)
    pub margin_rate: f64,
}

impl InstrumentSpec {
    /// Notional value of a position in account currency
    ///
    /// notional = size × contract_size × price
    pub fn notional_value(&self, size: f64, price: f64) -> f64 {
        size * self.contract_size * price
    }

    /// Exposure as a percentage of equity
    ///
    /// Answers: "How large is this position relative to my account?"
    pub fn exposure_pct(&self, size: f64, price: f64, equity: f64) -> f64 {
        if equity <= 0.0 { return 0.0; }
        (self.notional_value(size, price) / equity) * 100.0
    }

    /// Risk amount in account currency if stop loss is hit
    ///
    /// risk = |entry - sl| × size × contract_size
    pub fn risk_amount(
        &self,
        size:        f64,
        entry_price: f64,
        sl_price:    f64,
    ) -> f64 {
        let distance = (entry_price - sl_price).abs();
        distance * size * self.contract_size
    }

    /// Risk as a percentage of equity
    ///
    /// Answers: "What % of my account is at risk if SL is hit?"
    pub fn risk_pct(
        &self,
        size:        f64,
        entry_price: f64,
        sl_price:    f64,
        equity:      f64,
    ) -> f64 {
        if equity <= 0.0 { return 0.0; }
        (self.risk_amount(size, entry_price, sl_price) / equity) * 100.0
    }

    /// Margin required to open a position
    ///
    /// margin = notional × margin_rate
    pub fn margin_required(&self, size: f64, price: f64) -> f64 {
        self.notional_value(size, price) * self.margin_rate
    }

    /// Margin as a percentage of equity
    pub fn margin_pct(&self, size: f64, price: f64, equity: f64) -> f64 {
        if equity <= 0.0 { return 0.0; }
        (self.margin_required(size, price) / equity) * 100.0
    }

    // ── Preset constructors ──────────────────────

    /// Standard EURUSD forex settings
    pub fn eurusd() -> Self {
        Self {
            symbol:         "EURUSD".to_string(),
            contract_size:  100_000.0,
            pip_value:      10.0,
            price_decimals: 5,
            margin_rate:    0.01,
        }
    }

    /// Gold (XAUUSD) settings
    pub fn xauusd() -> Self {
        Self {
            symbol:         "XAUUSD".to_string(),
            contract_size:  100.0,
            pip_value:      1.0,
            price_decimals: 2,
            margin_rate:    0.005,
        }
    }

    /// Generic stock settings (1 share per lot)
    pub fn stock(symbol: impl Into<String>) -> Self {
        Self {
            symbol:         symbol.into(),
            contract_size:  1.0,
            pip_value:      0.01,
            price_decimals: 2,
            margin_rate:    0.25,
        }
    }

    /// Generic crypto settings
    pub fn crypto(symbol: impl Into<String>) -> Self {
        Self {
            symbol:         symbol.into(),
            contract_size:  1.0,
            pip_value:      1.0,
            price_decimals: 2,
            margin_rate:    0.1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eurusd_notional_value_correct() {
        let spec = InstrumentSpec::eurusd();
        // 1 standard lot at 1.13786
        // = 1 × 100,000 × 1.13786 = $113,786
        let notional = spec.notional_value(1.0, 1.13786);
        assert!((notional - 113_786.0).abs() < 0.01);
    }

    #[test]
    fn eurusd_exposure_pct_correct() {
        let spec   = InstrumentSpec::eurusd();
        let equity = 10_000.0;
        // 1 lot at 1.13786 with $10k equity
        // = 113,786 / 10,000 = 1137.86%
        let pct = spec.exposure_pct(1.0, 1.13786, equity);
        assert!((pct - 1137.86).abs() < 0.1);
    }

    #[test]
    fn eurusd_risk_amount_correct() {
        let spec = InstrumentSpec::eurusd();
        // 1 lot, entry 1.13786, SL 1.13486 (30 pip stop)
        // = 0.003 × 1 × 100,000 = $300
        let risk = spec.risk_amount(1.0, 1.13786, 1.13486);
        assert!((risk - 300.0).abs() < 0.01);
    }

    #[test]
    fn eurusd_risk_pct_correct() {
        let spec   = InstrumentSpec::eurusd();
        let equity = 10_000.0;
        // $300 risk on $10k account = 3%
        let pct = spec.risk_pct(1.0, 1.13786, 1.13486, equity);
        assert!((pct - 3.0).abs() < 0.01);
    }

    #[test]
    fn eurusd_margin_correct() {
        let spec = InstrumentSpec::eurusd();
        // 1 lot at 1.13786, 1% margin
        // = 113,786 × 0.01 = $1,137.86
        let margin = spec.margin_required(1.0, 1.13786);
        assert!((margin - 1_137.86).abs() < 0.01);
    }

    #[test]
    fn stock_notional_correct() {
        let spec = InstrumentSpec::stock("AAPL");
        // 100 shares at $182.50 = $18,250
        let notional = spec.notional_value(100.0, 182.50);
        assert!((notional - 18_250.0).abs() < 0.01);
    }

    #[test]
    fn zero_equity_returns_zero_pct() {
        let spec = InstrumentSpec::eurusd();
        assert_eq!(spec.exposure_pct(1.0, 1.13786, 0.0), 0.0);
        assert_eq!(spec.risk_pct(1.0, 1.13786, 1.13486, 0.0), 0.0);
        assert_eq!(spec.margin_pct(1.0, 1.13786, 0.0), 0.0);
    }
}