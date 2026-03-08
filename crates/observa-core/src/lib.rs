//! observa-core — Domain types and events shared across all Observa crates.
//!
//! This crate has no dependencies on other Observa crates.
//! Everything else depends on this.

pub mod bar;
pub mod events;
pub mod types;

pub use bar::{Bar, BarError};
pub use events::Event;
pub use types::{Direction, LotSize, Price, Volume};
