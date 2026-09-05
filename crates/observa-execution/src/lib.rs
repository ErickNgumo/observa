//! observa-execution — Execution model and fill simulation.
//!
//! * [`execution`] — legacy execution model consumed by the pre-OBS-0007 CLI
//!   (annotated as a compatibility adapter).
//! * [`semantics`] — canonical deterministic order/execution semantics
//!   (OBS-0006): MARKET/LIMIT/STOP and protective SL/TP evaluation against an
//!   OHLC bar, spread/slippage, gap handling, and deterministic ordering.

pub mod error;
pub mod execution;
pub mod semantics;
