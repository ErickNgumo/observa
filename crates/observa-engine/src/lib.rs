//! observa-engine — the single canonical backtest runtime (OBS-0007).
//!
//! * [`engine`] — the canonical Engine: one replay loop coordinating strategy,
//!   execution semantics and the portfolio financial authority.
//! * [`strategy`] — the strategy contract (read-only views, signals/drawings,
//!   lifecycle incl. parameterized initialization and structured errors).
//! * [`error`] — structured Engine errors.

pub mod engine;
pub mod error;
pub mod strategy;
