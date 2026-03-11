use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

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