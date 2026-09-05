use thiserror::Error;

use observa_portfolio::error::PortfolioError;

/// Structured errors raised by the canonical Engine runtime (OBS-0007).
///
/// The Engine coordinates configuration, strategy, execution semantics and
/// portfolio authority. Failures are surfaced as structured variants rather
/// than uncontrolled panics or silent fallbacks.
#[derive(Debug, Error)]
pub enum EngineError {
    /// The resolved configuration is invalid or incomplete.
    #[error("invalid engine configuration: {0}")]
    InvalidConfiguration(String),

    /// No market data was provided to the run.
    #[error("no data loaded: the run requires at least one bar")]
    NoDataLoaded,

    /// A strategy lifecycle callback failed.
    #[error("strategy failure: {message}")]
    StrategyFailure {
        /// Bar index at which the failure occurred, when known.
        #[doc(hidden)]
        bar_index: Option<usize>,
        /// Structured message from the strategy bridge.
        message: String,
    },

    /// The portfolio rejected or failed a financial operation.
    #[error("portfolio error: {0}")]
    Portfolio(#[from] PortfolioError),

    /// An execution-domain error surfaced through the runtime.
    #[error("execution error: {0}")]
    Execution(#[from] observa_execution::semantics::ExecutionDomainError),

    /// An order-sequence overflow (u64 counter exhausted).
    #[error("order sequence overflow: cannot create more orders in this run")]
    OrderSequenceOverflow,

    /// Internal runtime state error.
    #[error("invalid runtime state: {0}")]
    InvalidState(String),
}
