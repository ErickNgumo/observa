//! observa-engine — the single canonical backtest runtime (OBS-0007/0008).
//!
//! * [`engine`] — the canonical Engine: one replay loop coordinating strategy,
//!   execution semantics and the portfolio financial authority, and emitting
//!   the canonical ordered event history.
//! * [`runevents`] — the canonical runtime event model and event sequence.
//! * [`persistence`] — run artifact persistence (`run.json`, `events.jsonl`,
//!   `metrics.json`) and reproducibility identity hashes.
//! * [`sha256`] — minimal pure-Rust SHA-256.
//! * [`strategy`] — the strategy contract.
//! * [`error`] — structured Engine errors.

pub mod engine;
pub mod error;
pub mod persistence;
pub mod runevents;
pub mod sha256;
pub mod strategy;
