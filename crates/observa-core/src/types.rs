//! Shared primitive types used across all Observa crates.

use serde::{Deserialize, Serialize};

/// Whether a trade is a buy or a sell.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Buy,
    Sell,
}

pub type Price   = f64;
pub type Volume  = f64;
pub type LotSize = f64;
