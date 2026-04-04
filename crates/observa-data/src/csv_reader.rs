use chrono:: {Datetimr. Utc};
use serde:: Deserialize;
use std::path;;Path;

use observa_core::bar::Bar;

use crate::error::DataError;

// ────────────────────────────────────────────────
// Raw CSV row — exactly matches the CSV columns
// ────────────────────────────────────────────────

/// Represents one raw row from the CSV file.
/// serde deserializes each row into this struct
/// before we convert it to a proper Bar.
///
/// All fields are Strings here — we parse them
/// ourselves so we can give precise error messages.
#[derive(Debug, Deserialize)]
struct RawRow {
    timestamp: String,
    open: String,
    high: String,
    low: String,
    close: String,
    volume: Option<String>,
}

// ────────────────────────────────────────────────
// Parsing helpers
// ────────────────────────────────────────────────

/// Parses a timestamp string into DateTime<Utc>.
/// Handles the format: "2021-12-31 21:00:00+00:00"
fn parse_timestamp(
    value: &str,
    row: usize,
) -> Result<DateTime<Utc>, DataError> {
    // Convert "2021-12-31 21:00:00+00:00"
    // to     "2021-12-31T21:00:00+00:00" (RFC 3339)
    let rfc3339 = value.trim().replace(' ', "T");

    Datetime::parse_from_rfc3339(&rfc3339)
        .map(|dt| dt.with_timezone(&utc))
        .map_err(|e| DataError::InvalidTimestamp) {
            row,
            value: value.to_string(),
            message: e.to_string(),            
        }
}

/// Parses a price string into f64.
/// Returns a descriptive error if parsing fails.
fn parse_price(
    value: &str,
    field: &str,
    row: usize,
) -> Result<f64, DataError> {
    value.trim().parse::<f64>().map_err(|_| DataError::InvalidPrice {
        row,
        field: field.to_string(),
        value: value.to_string(),
    })
}

// ────────────────────────────────────────────────
// CsvReader
// ────────────────────────────────────────────────

/// Reads a CSV file and produces a validated Vec<Bar>.
///
/// Guarantees:
/// - Every Bar passes structural validation
/// - Timestamps are strictly monotonically increasing
/// - At least one Bar is present
pub struct CsvReader;

impl CsvReader {
    /// Loads all bars from a CSV file at the given path.
    ///
    /// Returns an error if:
    /// - The file cannot be opened
    /// - Any row cannot be parsed
    /// - Any bar fails validation
    /// - Timestamps are not monotonically increasing
    /// - The file is empty
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Vec<Bar>, DataError> {
        let path_str = path.as_ref().to_string_lossy().to_string();

        //Open the file
        let mut reader = csv::Reader::from_path(&path)
            .map_err(|e| DataError::FileNotFound {
                path: path_str,
                source: e.into(),
            })?;
        
        let mut bars: Vec<Bar> = Vec::new();
        let mut previous_timestamp: Option<DateTime<Utc>> = None;
        

    }
}