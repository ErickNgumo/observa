use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

// ────────────────────────────────────────────────
// Error type
// ────────────────────────────────────────────────

/// Describes exactly why a Bar failed validation.
/// Each variant is a specific rule violation.

#[derive(Debug, Clone, PartialEq)]
pub enum BarValidationError {
    /// high must be >= open, close, and low
    HighBelowOtherPrices { high: f64, offender: f64 },

    /// low must be <= open, close, and high
    LowAboveOtherPrices { low: f64, offender: f64 },

    /// No price field can be zero or negative
    NonPositivePrice { field: String, value: f64 },

    /// Volume cannot be negative if present
    NegativeVolume { volume: f64 },
}

// This lets us print the error as a human readable message
impl std::fmt::Display for BarValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BarValidationError::HighBelowOtherPrices { high, offender } => {
                write!(f, "High ({high}) is below another price ({offender})")
            }
            BarValidationError::LowAboveOtherPrices { low, offender } => {
                write!(f, "Low ({low}) is above another price ({offender})")
            }
            BarValidationError::NonPositivePrice { field, value } => {
                write!(f, "Price field '{field}' must be positive, got {value}")
            }
            BarValidationError::NegativeVolume { volume } => {
                write!(f, "Volume cannot be negative, got {volume}")
            }
        }
    }
}


/// A single OHLCV candle representing price activity
/// over a fixed time period.
///
/// Bar is the primary unit of market data in Observa.
/// It is read-only — nothing in the system modifies a Bar
/// after it is created.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bar {
    /// The exact time this bar closed, in UTC
    pub timestamp: DateTime<Utc>,

    /// Opening price of this bar
    pub open: f64,

    /// Highest price reached during this bar
    pub high: f64,

    /// Lowest price reached during this bar
    pub low: f64,

    /// Closing price of this bar
    pub close: f64,

    /// Trading volume — optional because not all
    /// datasets include volume (especially forex)
    pub volume: Option<f64>,
}

// ────────────────────────────────────────────────
// Bar methods
// ────────────────────────────────────────────────

impl Bar {
    /// Creates a new Bar.
    /// This is the only way to construct a Bar.
    pub fn new(
        timestamp: DateTime<Utc>,
        open: f64,
        high: f64,
        low: f64,
        close: f64,
        volume: Option<f64>,
    ) -> Self {
        Self {
            timestamp,
            open,
            high,
            low,
            close,
            volume,
        }
    }
    /// Validates that this Bar obeys all invariants
    /// defined in the event schemas.
    ///
    /// Returns Ok(()) if valid, or a Vec of every
    /// violation found — not just the first one.
    pub fn validate(&self) -> Result<(), Vec<BarValidationError>> {
        let mut errors = Vec::new();

        // Rule 1 — all prices must be positive
        for (field, value) in [
            ("open",  self.open),
            ("high",  self.high),
            ("low",   self.low),
            ("close", self.close),
        ] {
            if value <= 0.0 {
                errors.push(BarValidationError::NonPositivePrice {
                    field: field.to_string(),
                    value,
                });
            }
        }

        // Rule 2 — high must be >= open, low, close
        for offender in [self.open, self.low, self.close] {
            if self.high < offender {
                errors.push(BarValidationError::HighBelowOtherPrices {
                    high: self.high,
                    offender,
                });
            }
        }

        // Rule 3 — low must be <= open, high, close
        for offender in [self.open, self.high, self.close] {
            if self.low > offender {
                errors.push(BarValidationError::LowAboveOtherPrices {
                    low: self.low,
                    offender,
                });
            }
        }

        // Rule 4 — volume cannot be negative if present
        if let Some(vol) = self.volume {
            if vol < 0.0 {
                errors.push(BarValidationError::NegativeVolume { volume: vol });
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }

    /// Returns the candle's price range (high - low)
    pub fn range(&self) -> f64 {
        self.high - self.low
    }

    /// Returns true if this is a bullish candle
    /// (close above open)
    pub fn is_bullish(&self) -> bool {
        self.close > self.open
    }

    /// Returns true if this is a bearish candle
    /// (close below open)
    pub fn is_bearish(&self) -> bool {
        self.close < self.open
    }

}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    /// Helper — builds a known-good EURUSD bar
    /// matching the first row of our sample CSV
    fn sample_bar() -> Bar {
        Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1376,   // open
            1.13787,  // high
            1.1376,   // low
            1.13786,  // close
            Some(278.19), // volume
        )
    }

    #[test]
    fn valid_bar_passes_validation() {
        let bar = sample_bar();
        assert!(bar.validate().is_ok());
    }

    #[test]
    fn high_below_close_fails_validation() {
        let bar = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1376,   // open
            1.1370,   // high — WRONG: below close
            1.1360,   // low
            1.1375,   // close
            None,
        );
        let result = bar.validate();
        assert!(result.is_err());
        let errors = result.unwrap_err();
        assert!(errors.iter().any(|e| matches!(
            e,
            BarValidationError::HighBelowOtherPrices { .. }
        )));
    }

    #[test]
    fn negative_price_fails_validation() {
        let bar = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            -1.1376,  // open — WRONG: negative
            1.13787,
            1.1376,
            1.13786,
            None,
        );
        let result = bar.validate();
        assert!(result.is_err());
        let errors = result.unwrap_err();
        assert!(errors.iter().any(|e| matches!(
            e,
            BarValidationError::NonPositivePrice { .. }
        )));
    }

    #[test]
    fn negative_volume_fails_validation() {
        let bar = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1376,
            1.13787,
            1.1376,
            1.13786,
            Some(-10.0), // WRONG: negative volume
        );
        let result = bar.validate();
        assert!(result.is_err());
        let errors = result.unwrap_err();
        assert!(errors.iter().any(|e| matches!(
            e,
            BarValidationError::NegativeVolume { .. }
        )));
    }

    #[test]
    fn missing_volume_is_valid() {
        let bar = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1376,
            1.13787,
            1.1376,
            1.13786,
            None, // volume absent — should still be valid
        );
        assert!(bar.validate().is_ok());
    }

    #[test]
    fn bullish_and_bearish_detection() {
        let bullish = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1370,  // open
            1.1380,
            1.1365,
            1.1378,  // close > open — bullish
            None,
        );
        assert!(bullish.is_bullish());
        assert!(!bullish.is_bearish());

        let bearish = Bar::new(
            Utc.with_ymd_and_hms(2021, 12, 31, 21, 0, 0).unwrap(),
            1.1378,  // open
            1.1380,
            1.1365,
            1.1370,  // close < open — bearish
            None,
        );
        assert!(bearish.is_bearish());
        assert!(!bearish.is_bullish());
    }
}