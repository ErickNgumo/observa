use thiserror::Error;

#[derive(Debug, Error)]
pub enum ExecutionError {
    #[error("No current bar available for fill calculation")]
    NoCurrentBar,

    #[error("Fill price calculation failed: {message}")]
    FillCalculationError {message: String },
}