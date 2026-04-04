use chrono::{DateTime, Utc};
use serde::Deserialize;
use std::path::Path;

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
    open:      String,
    high:      String,
    low:       String,
    close:     String,
    volume:    Option<String>,
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

    DateTime::parse_from_rfc3339(&rfc3339)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|e| DataError::InvalidTimestamp {
            row,
            value: value.to_string(),
            message: e.to_string(),
        })
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

        // Open the file
        let mut reader = csv::Reader::from_path(&path)
            .map_err(|e| DataError::FileNotFound {
                path: path_str,
                source: e.into(),
            })?;

        let mut bars: Vec<Bar> = Vec::new();
        let mut previous_timestamp: Option<DateTime<Utc>> = None;

        // row_number starts at 2 because row 1 is the header
        for (index, result) in reader.deserialize::<RawRow>().enumerate() {
            let row_number = index + 2;

            // Parse the raw CSV row
            let raw = result.map_err(|e| DataError::CsvParseError {
                row: row_number,
                message: e.to_string(),
            })?;

            // Parse each field
            let timestamp = parse_timestamp(&raw.timestamp, row_number)?;
            let open      = parse_price(&raw.open,  "open",  row_number)?;
            let high      = parse_price(&raw.high,  "high",  row_number)?;
            let low       = parse_price(&raw.low,   "low",   row_number)?;
            let close     = parse_price(&raw.close, "close", row_number)?;

            // Parse optional volume
            let volume = match &raw.volume {
                Some(v) if !v.trim().is_empty() => {
                    Some(parse_price(v, "volume", row_number)?)
                }
                _ => None,
            };

            // Build the Bar
            let bar = Bar::new(timestamp, open, high, low, close, volume);

            // Validate the Bar's internal consistency
            bar.validate().map_err(|errors| {
                let details = errors
                    .iter()
                    .map(|e| e.to_string())
                    .collect::<Vec<_>>()
                    .join("; ");
                DataError::InvalidBar { row: row_number, details }
            })?;

            // Check monotonic timestamps
            if let Some(prev_ts) = previous_timestamp {
                if timestamp <= prev_ts {
                    return Err(DataError::NonMonotonicTimestamp {
                        row: row_number,
                        previous: prev_ts.to_rfc3339(),
                        current: timestamp.to_rfc3339(),
                    });
                }
            }

            previous_timestamp = Some(timestamp);
            bars.push(bar);
        }

        // Ensure we loaded at least one bar
        if bars.is_empty() {
            return Err(DataError::EmptyDataset);
        }

        Ok(bars)
    }
}