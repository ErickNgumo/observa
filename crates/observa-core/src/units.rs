//! Canonical financial unit vocabulary and derivations.
//!
//! Observa's financial model distinguishes these quantities (OBS-0003 §14):
//!
//! * **quantity_lots** — the user/strategy-facing position size, in lots or
//!   contracts (a float such as `1.0` or `0.01`).
//! * **contract_size** — instrument base units per one lot (configurable;
//!   e.g. 100,000 for EURUSD, 100 for XAUUSD, 1 for an equity).
//! * **units** — actual base units of the instrument:
//!   `units = quantity_lots × contract_size`.
//! * **price** — quote-currency amount per base unit (e.g. USD per EUR).
//! * **notional** — monetary exposure: `notional = units × price`
//!   (in the quote currency).
//!
//! P&L is computed in the instrument quote currency as
//!
//! ```text
//! pnl = (exit_price - entry_price) × quantity_lots × contract_size × direction
//! ```
//!
//! where `direction` is `+1` for a long and `-1` for a short.
//!
//! In the MVP the account currency must equal the instrument quote currency
//! (no FX conversion); money produced by these helpers is therefore account
//! currency as well.
//!
//! All derivations live here so that execution, portfolio and metrics never
//! recompute unit conversions independently with subtly different constants.

use crate::config::ConfigError;

/// Base units for a quantity expressed in lots.
///
/// `units = quantity_lots × contract_size`.
pub fn units_from_lots(quantity_lots: f64, contract_size: f64) -> f64 {
    quantity_lots * contract_size
}

/// Monetary exposure for a given number of base units at a price.
///
/// `notional = units × price` (quote currency).
pub fn notional_from_units(units: f64, price: f64) -> f64 {
    units * price
}

/// Monetary exposure for a quantity in lots at a price.
///
/// `notional = quantity_lots × contract_size × price` (quote currency).
pub fn notional_from_lots(quantity_lots: f64, contract_size: f64, price: f64) -> f64 {
    notional_from_units(units_from_lots(quantity_lots, contract_size), price)
}

/// Money value of one pip per lot:
/// `pip_value = pip_size × contract_size` (quote currency).
pub fn pip_value_per_lot(pip_size: f64, contract_size: f64) -> f64 {
    pip_size * contract_size
}

/// Money value of one tick per lot:
/// `tick_value = tick_size × contract_size` (quote currency).
pub fn tick_value_per_lot(tick_size: f64, contract_size: f64) -> f64 {
    tick_size * contract_size
}

/// Margin required to hold a position, from leverage:
/// `margin_required = notional / leverage`.
pub fn margin_required_from_lots(
    quantity_lots: f64,
    contract_size: f64,
    price: f64,
    leverage: f64,
) -> Result<f64, ConfigError> {
    if !leverage.is_finite() || leverage <= 0.0 {
        return Err(ConfigError::InvalidField {
            field: "account.leverage".into(),
            reason: format!("leverage must be a finite positive number, got {leverage}"),
        });
    }
    Ok(notional_from_lots(quantity_lots, contract_size, price) / leverage)
}

/// Margin rate implied by a leverage value: `margin_rate = 1 / leverage`.
pub fn margin_rate_from_leverage(leverage: f64) -> Option<f64> {
    if leverage.is_finite() && leverage > 0.0 {
        Some(1.0 / leverage)
    } else {
        None
    }
}

/// P&L amount for a closed or open position in the quote currency:
///
/// `pnl = (exit - entry) × quantity_lots × contract_size × direction`
///
/// where `direction` is `+1` for a long and `-1` for a short.
pub fn pnl_amount(
    entry_price: f64,
    exit_price: f64,
    quantity_lots: f64,
    contract_size: f64,
    direction_multiplier: f64,
) -> f64 {
    (exit_price - entry_price) * quantity_lots * contract_size * direction_multiplier
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn units_from_lots_uses_contract_size() {
        // 1 lot EURUSD = 100,000 base units.
        assert_eq!(units_from_lots(1.0, 100_000.0), 100_000.0);
        // 100 shares of a contract_size-1 instrument = 100 units.
        assert_eq!(units_from_lots(100.0, 1.0), 100.0);
    }

    #[test]
    fn notional_is_units_times_price() {
        // EURUSD: 1 lot @ 1.10 → 100,000 EUR × 1.10 = 110,000 USD.
        let notional = notional_from_lots(1.0, 100_000.0, 1.10);
        assert!((notional - 110_000.0).abs() < 1e-6);
        // AAPL: 100 shares @ 182.50 → 18,250 USD.
        let stock = notional_from_lots(100.0, 1.0, 182.50);
        assert!((stock - 18_250.0).abs() < 1e-6);
    }

    #[test]
    fn pip_and_tick_values_are_derived() {
        // EURUSD: pip 0.0001 × 100,000 = $10/pip/lot.
        assert!((pip_value_per_lot(0.0001, 100_000.0) - 10.0).abs() < 1e-9);
        // Gold: tick 0.01 × 100 oz = $1/tick/lot.
        assert!((tick_value_per_lot(0.01, 100.0) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn margin_is_notional_over_leverage() {
        // 1 lot EURUSD @ 1.10 notional 110,000; leverage 100 → 1,100 margin.
        let m = margin_required_from_lots(1.0, 100_000.0, 1.10, 100.0).unwrap();
        assert!((m - 1_100.0).abs() < 1e-6);
        // 100 AAPL shares @ 182.50 notional 18,250; leverage 4 (25%) → 4,562.50.
        let s = margin_required_from_lots(100.0, 1.0, 182.50, 4.0).unwrap();
        assert!((s - 4_562.50).abs() < 1e-6);
    }

    #[test]
    fn invalid_leverage_is_rejected_by_margin_helper() {
        for bad in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert!(margin_required_from_lots(1.0, 100_000.0, 1.10, bad).is_err());
            assert!(margin_rate_from_leverage(bad).is_none());
        }
        assert_eq!(margin_rate_from_leverage(100.0), Some(0.01));
        assert_eq!(margin_rate_from_leverage(4.0), Some(0.25));
    }

    #[test]
    fn pnl_formula_uses_contract_size_and_direction() {
        // EURUSD long: 10 pips (0.0010) on 1 lot = +$100.
        let long = pnl_amount(1.10000, 1.10100, 1.0, 100_000.0, 1.0);
        assert!((long - 100.0).abs() < 1e-6);
        // EURUSD short: +10 pips (price fell) = +$100.
        let short = pnl_amount(1.10100, 1.10000, 1.0, 100_000.0, -1.0);
        assert!((short - 100.0).abs() < 1e-6);
        // AAPL: 100 shares, $2.50 move = +$250.
        let stock = pnl_amount(182.50, 185.00, 100.0, 1.0, 1.0);
        assert!((stock - 250.0).abs() < 1e-6);
    }
}
