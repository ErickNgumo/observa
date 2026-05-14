use thiserror::Error;

#[derive(Debug, Error)]
pub enum PortfolioError {
    #[error("No open position to close")]
    NoOpenPosition,

    #[error("Position {position_id} not found")]
    PositionNotFound { position_id: String},

    #[error("Insufficient balance: required {required}, available {available}")]
    InsufficientBalance {required: f64, available: f64},
}