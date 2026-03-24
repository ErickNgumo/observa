use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::bar::Bar;
use crate::types::{
    AnnotationSource, CancellationReason, Direction,
    ErrorType, ExitReason, RejectionReason, UpdateType,
};

// ────────────────────────────────────────────────
// EventMetadata — shared baseline for all events
// ────────────────────────────────────────────────

/// Fields present on every event in Observa.
/// Embedded in every event struct via #[serde(flatten)].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventMetadata {
    /// Unique identifier for this specific event
    pub event_id: Uuid,

    /// The run this event belongs to
    pub run_id: Uuid,

    /// Exact time this event occurred
    pub timestamp: DateTime<Utc>,
}

impl EventMetadata {
    /// Creates new metadata with a fresh random event_id
    pub fn new(run_id: Uuid, timestamp: DateTime<Utc>) -> Self {
        Self {
            event_id: Uuid::new_v4(),
            run_id,
            timestamp,
        }
    }
}