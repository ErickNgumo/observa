use thiserror::Error;

/// Structured errors produced by the financial/position accounting model
/// (OBS-0005 §27).
///
/// Financial operations that cannot be completed return these errors rather
/// than silently returning false/zero/empty values. The engine layer
/// (OBS-0007) will translate them into structured events; they must never be
/// used as the *only* error channel (no stderr-only handling).
#[derive(Debug, Error, PartialEq)]
pub enum PortfolioError {
    /// A close request did not identify any position ticket.
    #[error(
        "close requires an explicit position ticket; no implicit position selection is allowed"
    )]
    CloseRequiresTicket,

    /// No position exists for the given ticket.
    #[error("position {position_id} not found")]
    PositionNotFound { position_id: String },

    /// The ticket references a position that is already closed.
    #[error("position {position_id} is already closed")]
    PositionAlreadyClosed { position_id: String },

    /// The requested close quantity does not equal the full open quantity
    /// (partial closes are out of the MVP scope).
    #[error("close quantity mismatch for position {position_id}: open {open_quantity}, requested {requested_quantity}")]
    CloseQuantityMismatch {
        position_id: String,
        open_quantity: f64,
        requested_quantity: f64,
    },

    /// Opening the position would require more margin than is available.
    #[error("insufficient margin: required {required}, free margin {available}")]
    InsufficientMargin { required: f64, available: f64 },

    /// The requested quantity is invalid (non-finite or not positive).
    #[error("invalid quantity {quantity}: {reason}")]
    InvalidQuantity { quantity: f64, reason: String },

    /// A supplied price is invalid (non-finite or not positive).
    #[error("invalid price {price}: {reason}")]
    InvalidPrice { price: f64, reason: String },

    /// The direction is invalid for the requested operation (e.g. opening a
    /// position with `Direction::Close`).
    #[error("invalid direction for this operation: {direction}")]
    InvalidDirection { direction: String },

    /// A commission amount supplied for booking is invalid.
    #[error("invalid commission amount {amount}: {reason}")]
    InvalidCommission { amount: f64, reason: String },

    /// The portfolio is in an internally inconsistent financial state.
    #[error("invalid portfolio state: {reason}")]
    InvalidState { reason: String },

    /// The portfolio was constructed with invalid settings.
    #[error("invalid portfolio settings: {reason}")]
    InvalidSettings { reason: String },
}
