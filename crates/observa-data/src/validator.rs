//! Dataset validation — checks bars before the engine sees them.

use chrono::{DateTime, Utc};
use observa_core::Bar;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ValidationError {
    #[error("Timestamp not monotonically increasing at bar {index}: \
             previous={previous}, current={current}")]
    NonMonotonicTimestamp {
        index:    usize,
        previous: DateTime<Utc>,
        current:  DateTime<Utc>,
    },
    #[error("Duplicate timestamp at bar {index}: {timestamp}")]
    DuplicateTimestamp {
        index:     usize,
        timestamp: DateTime<Utc>,
    },
    #[error("Dataset is empty — no bars to replay")]
    EmptyDataset,
}

pub struct DatasetValidator;

impl DatasetValidator {
    pub fn validate(bars: &[Bar]) -> Result<(), ValidationError> {
        if bars.is_empty() {
            return Err(ValidationError::EmptyDataset);
        }
        for i in 1..bars.len() {
            let previous = bars[i - 1].timestamp;
            let current  = bars[i].timestamp;
            if current == previous {
                return Err(ValidationError::DuplicateTimestamp { index: i, timestamp: current });
            }
            if current < previous {
                return Err(ValidationError::NonMonotonicTimestamp { index: i, previous, current });
            }
        }
        Ok(())
    }
}
