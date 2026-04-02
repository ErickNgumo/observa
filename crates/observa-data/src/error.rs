use thiserror::Error;

/// All the ways data loading can fail in Observa.
/// Each variant describes a specific, actionable problem.
#[derive(Debug, Error)]
pub enum DataError {
    #[error("Failed to open file '{path}': {source}")]
    FileNotFound {
        path: String,
        source: std::io::Error,
    },

    #[error("Failed to parse CSV at row {row}: {message}")]
    CsvParseError {
        row: usize,
        message: String,
    },

    #[error("Failed to parse timestamp '{value}' at row {row}: {message}")]
    InvalidTimestamp {
        row: usize,
        value: String,
        message: String,
    },

    #[error("Failed to parse price field '{field}' at row {row}: '{value}'")]
    InvalidPrice {
        row: usize,
        field: String,
        value: String,
    },

    #[error("Bar validation failed at row {row}: {details}")]
    InvalidBar {
        row: usize,
        details: String,
    },

    #[error("Dataset is empty — no bars were loaded")]
    EmptyDataset,

    #[error("Timestamps are not monotonically increasing at row {row}: \
             {current} is not after {previous}")]
    NonMonotonicTimestamp {
        row: usize,
        previous: String,
        current: String,
    },
}