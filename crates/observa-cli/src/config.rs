use serde::{Deserialize, Serialize};

// ────────────────────────────────────────────────
// LEGACY configuration types
// ────────────────────────────────────────────────
//
// NOTE (OBS-0004): the canonical, authoritative configuration model is
// `observa_core::config::BacktestConfig`. The types below are the historical
// CLI configuration representation and are retained ONLY as a temporary
// compatibility loader until the CLI is refactored to the canonical model in
// OBS-0007. New components must not use them.

/// User-facing configuration file (config.yaml)
/// All fields are optional - defaults are provided
#[derive(Debug, Serialize, Deserialize)]
pub struct ObservaConfig {
    #[serde(default)]
    pub execution: ExecutionSettings,

    #[serde(default)]
    pub account: AccountSettings,

    #[serde(default)]
    pub instrument: InstrumentSettings,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExecutionSettings {
    /// Fixed spread in price units (default: 0.0002 = 2 pips)
    #[serde(default = "default_spread")]
    pub spread: f64,

    /// Fixed slippage in price units (defualt: 0.0001 = 1 pip)
    #[serde(default = "default_slippage")]
    pub slippage: f64,

    /// Commission per trade in account currency (default: 7.0)
    #[serde(default = "default_commission")]
    pub commission: f64,

    /// Minimum stop distance in price units (default: 0.0010)
    #[serde(default = "default_min_stop")]
    pub min_stop_distance: f64,

    /// Minimum lot size (default: 0.01)
    #[serde(default = "default_min_lot")]
    pub min_lot_size: f64,

    /// Maximum lot size (default: 100.0)
    #[serde(default = "default_max_lot")]
    pub max_lot_size: f64,

    /// Fill mode: next_bar_open or this_bar_close
    #[serde(default = "default_fill_mode")]
    pub fill_mode: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AccountSettings {
    /// Starting capital (default: 10000.0)
    #[serde(default = "default_balance")]
    pub initial_balance: f64,

    /// Account currency (default: USD)
    #[serde(default = "default_currency")]
    pub currency: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InstrumentSettings {
    #[serde(default = "default_symbol")]
    pub symbol:         String,
    #[serde(default = "default_contract_size")]
    pub contract_size:  f64,
    #[serde(default = "default_pip_value")]
    pub pip_value:      f64,
    #[serde(default = "default_price_decimals")]
    pub price_decimals: u32,
    #[serde(default = "default_margin_rate")]
    pub margin_rate:    f64,
}

impl Default for ExecutionSettings {
    fn default() -> Self {
        Self {
            spread:            default_spread(),
            slippage:          default_slippage(),
            commission:        default_commission(),
            min_stop_distance: default_min_stop(),
            min_lot_size:      default_min_lot(),
            max_lot_size:      default_max_lot(),
            fill_mode:         default_fill_mode(),
        }
    }
}

impl Default for AccountSettings {
    fn default() -> Self {
        Self {
            initial_balance: default_balance(),
            currency:        default_currency(),
        }
    }
}

impl Default for ObservaConfig {
    fn default() -> Self {
        Self {
            execution: ExecutionSettings::default(),
            account:   AccountSettings::default(),
            instrument: InstrumentSettings::default(),
        }
    }
}

impl Default for InstrumentSettings {
    fn default() -> Self {
        Self {
            symbol:         default_symbol(),
            contract_size:  default_contract_size(),
            pip_value:      default_pip_value(),
            price_decimals: default_price_decimals(),
            margin_rate:    default_margin_rate(),
        }
    }
}


// ── Defaults ─────────────────────────────────────

fn default_spread()      -> f64    { 0.0002 }
fn default_slippage()    -> f64    { 0.0001 }
fn default_commission()  -> f64    { 7.0    }
fn default_min_stop()    -> f64    { 0.0010 }
fn default_min_lot()     -> f64    { 0.01   }
fn default_max_lot()     -> f64    { 100.0  }
fn default_balance()     -> f64    { 10_000.0 }
fn default_fill_mode()   -> String { "next_bar_open".to_string() }
fn default_currency()    -> String { "USD".to_string() }

fn default_symbol()         -> String { "EURUSD".to_string() }
fn default_contract_size()  -> f64    { 100_000.0 }
fn default_pip_value()      -> f64    { 10.0 }
fn default_price_decimals() -> u32    { 5 }
fn default_margin_rate()    -> f64    { 0.01 }

// ── Loader ───────────────────────────────────────

/// Loads config from a file path.
/// Returns defaults if file doesn't exist.
pub fn load_config(path: &std::path::Path) -> ObservaConfig {
    if !path.exists() {
        return ObservaConfig::default();
    }

    let contents = match std::fs::read_to_string(path) {
        Ok(c)  => c,
        Err(e) => {
            eprintln!("Warning: could not read config file: {}", e);
            return ObservaConfig::default();
        }
    };

    match serde_yaml::from_str(&contents) {
        Ok(config) => config,
        Err(e) => {
            eprintln!("Warning: invalid config file: {}", e);
            eprintln!("Using defaults.");
            ObservaConfig::default()
        }
    }
}

/// Generates a default config.yaml with comments
pub fn generate_default_config() -> String {
    r#"# Observa Configuration
# All values are optional — defaults are shown

execution:
  spread:            0.0002   # Fixed spread in price units (2 pips for EURUSD)
  slippage:          0.0001   # Fixed slippage in price units (1 pip)
  commission:        7.0      # Commission per trade in account currency
  min_stop_distance: 0.0010   # Minimum distance from entry to SL/TP
  min_lot_size:      0.01     # Minimum position size in lots
  max_lot_size:      100.0    # Maximum position size in lots
  fill_mode:         next_bar_open  # next_bar_open | this_bar_close

account:
  initial_balance: 10000.0   # Starting capital
  currency:        USD        # Account currency

  # Instrument contract specifications
# These determine how lot size converts to monetary exposure
instrument:
  symbol:         EURUSD    # Instrument identifier
  contract_size:  100000    # Units per lot (100k for forex)
  pip_value:      10.0      # $ value of 1 pip per lot
  price_decimals: 5         # Decimal places in price
  margin_rate:    0.01      # Margin requirement (1% = 100:1 leverage)

# Examples for other instruments:
#
# Gold (XAUUSD):
#   symbol: XAUUSD
#   contract_size: 100
#   pip_value: 1.0
#   price_decimals: 2
#   margin_rate: 0.005
#
# US Stocks:
#   symbol: AAPL
#   contract_size: 1
#   pip_value: 0.01
#   price_decimals: 2
#   margin_rate: 0.25
#
# Crypto:
#   symbol: BTC/USD
#   contract_size: 1
#   pip_value: 1.0
#   price_decimals: 2
#   margin_rate: 0.1
"#.to_string()
}
