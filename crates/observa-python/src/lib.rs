//! observa-python — **legacy / dev-only** Python bindings via PyO3.
//!
//! **This crate is NOT the strategy contract of the released Python wheel.**
//!
//! The shipped wheel is built by the separate maturin project at `python/`
//! (module `observa._observa`), which does not depend on this crate. This bridge
//! is reachable only through the Rust `observa-cli` binary
//! (`observa run --strategy <file.py>`), which is not part of the release
//! assets, and its portfolio/position dict shapes diverge from the shipped
//! binding. See `crates/observa-python/README.md` and `docs/STRATEGY_API.md`.
//!
//! OBS-AI-04 deliberately left it in place but made the divergence explicit:
//! `python/tests/test_agent_contract.py` guards the recorded key-set
//! difference, so a future change fails loudly instead of drifting silently.
pub mod bar;
pub mod drawings;
pub mod error;
pub mod portfolio;
pub mod signal;
pub mod strategy;
