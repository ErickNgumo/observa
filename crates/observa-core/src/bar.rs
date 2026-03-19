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
    
}