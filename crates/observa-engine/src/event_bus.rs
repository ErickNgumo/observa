use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;

use observa_core::events::Event;

use crate::error::EngineError;

// ────────────────────────────────────────────────
// Subscriber type
// ────────────────────────────────────────────────

/// A subscriber is a named function that receives events.
/// The name is used for error reporting — if a subscriber
/// panics, we know which one caused it.
pub struct Subscriber {
    pub name: String,
    pub handler: Box<dyn Fn(&Event)>,
}

// ────────────────────────────────────────────────
// EventBus
// ────────────────────────────────────────────────

/// The central message router of Observa.
///
/// Responsibilities:
/// 1. Always write every event to the event log first
/// 2. Then deliver the event to all subscribers
///
/// The event log write always happens before subscribers
/// are notified. If a subscriber panics, the event is
/// already safely recorded.
pub struct EventBus {
    /// All registered subscribers
    subscribers: Vec<Subscriber>,

    /// The event log file — every event written here
    log_file: Option<File>,

    /// Count of events published this run
    event_count: u64,
}

impl EventBus {
    /// Creates a new EventBus with no log file.
    /// Call with_log() to enable event logging.
    pub fn new() -> Self {
        Self {
            subscribers: Vec::new(),
            log_file: None,
            event_count: 0,
        }
    }

    /// Attaches an event log file to this bus.
    /// Every event will be written here as a JSON line.
    pub fn with_log<P: AsRef<Path>>(
        mut self,
        path: P,
    ) -> Result<Self, EngineError> {
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;

        self.log_file = Some(file);
        Ok(self)
    }

    /// Registers a named subscriber.
    /// The name appears in error messages if the
    /// subscriber panics.
    pub fn subscribe(
        &mut self,
        name: impl Into<String>,
        handler: impl Fn(&Event) + 'static,
    ) {
        self.subscribers.push(Subscriber {
            name: name.into(),
            handler: Box::new(handler),
        });
    }

    /// Publishes an event to the bus.
    ///
    /// Order of operations:
    /// 1. Write to event log (always first)
    /// 2. Notify all subscribers in registration order
    pub fn publish(&mut self, event: &Event) -> Result<(), EngineError> {
        // Step 1 — write to event log first, always
        self.write_to_log(event)?;

        // Step 2 — notify all subscribers
        for subscriber in &self.subscribers {
            (subscriber.handler)(event);
        }

        self.event_count += 1;
        Ok(())
    }

    /// Returns how many events have been published
    pub fn event_count(&self) -> u64 {
        self.event_count
    }

    /// Writes an event to the log file as a JSON line.
    /// One event per line — easy to parse and stream.
    fn write_to_log(&mut self, event: &Event) -> Result<(), EngineError> {
        if let Some(file) = &mut self.log_file {
            let json = serde_json::to_string(event).map_err(|e| {
                EngineError::EventLogWriteError {
                    message: e.to_string(),
                }
            })?;

            writeln!(file, "{}", json).map_err(|e| {
                EngineError::EventLogWriteError {
                    message: e.to_string(),
                }
            })?;
        }
        Ok(())
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}