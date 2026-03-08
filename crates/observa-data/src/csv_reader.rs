//! CSV reader — turns a CSV file into a validated stream of Bars.
//!
//! Expected format:
//!   timestamp,open,high,low,close,volume
//!   2021-12-31 21:00:00+00:00,1.1376,1.13787,1.1376,1.13786,278.19

use chrono::{DateTime, Utc};
use observa_core::{Bar, BarError};
use serde::Deserialize;
use thiserror::Error;
use crate::validator::{DatasetValidator, ValidationError};

#[derive(Debug, Deserialize)]
struct CsvRow {
    timestamp: String,
    open:      f64,
    high:      f64,
    low:       f64,
    close:     f64,
    volume:    Option<f64>,
}

#[derive(Debug, Error)]
pub enum CsvReaderError {
    #[error("Could not open file '{path}': {source}")]
    FileNotFound { path: String, source: std::io::Error },
    #[error("CSV parse error at row {row}: {source}")]
    ParseError { row: usize, source: csv::Error },
    #[error("Invalid timestamp '{value}' at row {row}: {source}")]
    InvalidTimestamp { row: usize, value: String, source: chrono::ParseError },
    #[error("Invalid bar data at row {row}: {source}")]
    InvalidBar { row: usize, source: BarError },
    #[error("Dataset validation failed: {source}")]
    ValidationFailed { source: ValidationError },
}

pub struct CsvReader;

impl CsvReader {
    pub fn load(path: &str) -> Result<Vec<Bar>, CsvReaderError> {
        let file = std::fs::File::open(path).map_err(|e| {
            CsvReaderError::FileNotFound { path: path.to_string(), source: e }
        })?;

        let mut reader = csv::ReaderBuilder::new()
            .has_headers(true)
            .from_reader(file);

        let mut bars = Vec::new();

        for (index, result) in reader.deserialize::<CsvRow>().enumerate() {
            let row_number = index + 2;
            let row = result.map_err(|e| CsvReaderError::ParseError {
                row: row_number, source: e,
            })?;

            let timestamp = parse_timestamp(&row.timestamp)
                .map_err(|e| CsvReaderError::InvalidTimestamp {
                    row: row_number, value: row.timestamp.clone(), source: e,
                })?;

            let bar = Bar::new(timestamp, row.open, row.high, row.low, row.close, row.volume)
                .map_err(|e| CsvReaderError::InvalidBar { row: row_number, source: e })?;

            bars.push(bar);
        }

        DatasetValidator::validate(&bars)
            .map_err(|e| CsvReaderError::ValidationFailed { source: e })?;

        Ok(bars)
    }
}

fn parse_timestamp(s: &str) -> Result<DateTime<Utc>, chrono::ParseError> {
    if let Ok(dt) = DateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S%z") {
        return Ok(dt.with_timezone(&Utc));
    }
    let naive = chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S")?;
    Ok(DateTime::from_naive_utc_and_offset(naive, Utc))
}
