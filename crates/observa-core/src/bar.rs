//! The Bar — the primary unit of market data in Observa.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use crate::types::{Price, Volume};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Bar {
    pub timestamp: DateTime<Utc>,
    pub open:      Price,
    pub high:      Price,
    pub low:       Price,
    pub close:     Price,
    pub volume:    Option<Volume>,
}

impl Bar {
    pub fn new(
        timestamp: DateTime<Utc>,
        open:      Price,
        high:      Price,
        low:       Price,
        close:     Price,
        volume:    Option<Volume>,
    ) -> Result<Self, BarError> {
        if high < low   { return Err(BarError::HighBelowLow { high, low }); }
        if high < open  { return Err(BarError::HighBelowOpen { high, open }); }
        if high < close { return Err(BarError::HighBelowClose { high, close }); }
        if low > open   { return Err(BarError::LowAboveOpen { low, open }); }
        if low > close  { return Err(BarError::LowAboveClose { low, close }); }
        if let Some(v) = volume {
            if v < 0.0  { return Err(BarError::NegativeVolume { volume: v }); }
        }
        Ok(Bar { timestamp, open, high, low, close, volume })
    }

    pub fn midpoint(&self)   -> Price { (self.high + self.low) / 2.0 }
    pub fn is_bullish(&self) -> bool  { self.close > self.open }
    pub fn is_bearish(&self) -> bool  { self.close < self.open }
}

#[derive(Debug, thiserror::Error)]
pub enum BarError {
    #[error("High ({high}) is below Low ({low})")]
    HighBelowLow   { high: Price, low: Price },
    #[error("High ({high}) is below Open ({open})")]
    HighBelowOpen  { high: Price, open: Price },
    #[error("High ({high}) is below Close ({close})")]
    HighBelowClose { high: Price, close: Price },
    #[error("Low ({low}) is above Open ({open})")]
    LowAboveOpen   { low: Price, open: Price },
    #[error("Low ({low}) is above Close ({close})")]
    LowAboveClose  { low: Price, close: Price },
    #[error("Volume ({volume}) is negative")]
    NegativeVolume { volume: Volume },
}
