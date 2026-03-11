//! The Bar — the primary unit of market data in Observa.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use crate::types::{Price, Volume};

// ────────────────────────────────────────────────
// Bar struct
// ────────────────────────────────────────────────

/// A single OHLCV candle representing price activity
/// over a fixed time period.
///
/// Bar is the primary unit of market data in Observa.
/// It is read-only — nothing in the system ever
/// modifies a Bar after it is created.


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Bar {
    pub timestamp: DateTime<Utc>,
    pub open:      Price,
    pub high:      Price,
    pub low:       Price,
    pub close:     Price,
    pub volume:    Option<Volume>,
}

