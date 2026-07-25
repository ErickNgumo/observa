use serde::{Deserialize, Serialize};

/// User-facing configuration file (config.yaml)
/// All fields are optional - defaults are provided
#[derive(Debug, Serialize, Deserialize)]
pub struct ObservaConfig {
    #[serde(default)]
    pub execution: ExecutionSettings,

    #[serde(default)]
    pub account: AccountSettings,
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
"#.to_string()
}
