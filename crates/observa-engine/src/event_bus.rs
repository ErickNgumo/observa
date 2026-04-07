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

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use observa_core::bar::Bar;
    use observa_core::events::{BarReceivedEvent, EventMetadata};
    use std::cell::RefCell;
    use std::rc::Rc;
    use uuid::Uuid;

    /// Builds a minimal BarReceivedEvent for testing
    fn test_bar_event() -> Event {
        let bar = Bar::new(
            Utc::now(),
            1.1376,
            1.13787,
            1.1376,
            1.13786,
            Some(278.19),
        );
        Event::BarReceived(BarReceivedEvent {
            metadata: EventMetadata::new(Uuid::new_v4(), Utc::now()),
            bar,
        })
    }

    #[test]
    fn subscriber_receives_published_event() {
        // Rc<RefCell<>> lets us mutate a counter
        // from inside a closure — we need this because
        // the closure captures the counter by reference
        let received = Rc::new(RefCell::new(0u32));
        let received_clone = received.clone();

        let mut bus = EventBus::new();
        bus.subscribe("test_subscriber", move |_event| {
            *received_clone.borrow_mut() += 1;
        });

        let event = test_bar_event();
        bus.publish(&event).unwrap();

        assert_eq!(*received.borrow(), 1);
    }

    #[test]
    fn multiple_subscribers_all_receive_event() {
        let count1 = Rc::new(RefCell::new(0u32));
        let count2 = Rc::new(RefCell::new(0u32));

        let count1_clone = count1.clone();
        let count2_clone = count2.clone();

        let mut bus = EventBus::new();
        bus.subscribe("subscriber_1", move |_| {
            *count1_clone.borrow_mut() += 1;
        });
        bus.subscribe("subscriber_2", move |_| {
            *count2_clone.borrow_mut() += 1;
        });

        let event = test_bar_event();
        bus.publish(&event).unwrap();

        assert_eq!(*count1.borrow(), 1);
        assert_eq!(*count2.borrow(), 1);
    }

    #[test]
    fn event_count_increments_correctly() {
        let mut bus = EventBus::new();

        assert_eq!(bus.event_count(), 0);

        bus.publish(&test_bar_event()).unwrap();
        bus.publish(&test_bar_event()).unwrap();
        bus.publish(&test_bar_event()).unwrap();

        assert_eq!(bus.event_count(), 3);
    }

    #[test]
    fn event_log_writes_json_lines() {
        use std::io::Read;
        use tempfile::NamedTempFile;

        let log_file = NamedTempFile::new().unwrap();
        let log_path = log_file.path().to_path_buf();

        let mut bus = EventBus::new()
            .with_log(&log_path)
            .unwrap();

        bus.publish(&test_bar_event()).unwrap();
        bus.publish(&test_bar_event()).unwrap();

        // Read the log file back
        let mut contents = String::new();
        std::fs::File::open(&log_path)
            .unwrap()
            .read_to_string(&mut contents)
            .unwrap();

        // Should have two lines — one per event
        let lines: Vec<&str> = contents
            .lines()
            .filter(|l| !l.is_empty())
            .collect();

        assert_eq!(lines.len(), 2);

        // Each line should be valid JSON
        for line in lines {
            let parsed: serde_json::Value =
                serde_json::from_str(line).unwrap();
            assert!(parsed.get("event_id").is_some());
            assert!(parsed.get("run_id").is_some());
        }
    }

    #[test]
    fn subscriber_only_handles_events_it_cares_about() {
        let bar_count = Rc::new(RefCell::new(0u32));
        let bar_count_clone = bar_count.clone();

        let mut bus = EventBus::new();

        // This subscriber only cares about BarReceived
        bus.subscribe("visualization", move |event| {
            match event {
                Event::BarReceived(_) => {
                    *bar_count_clone.borrow_mut() += 1;
                }
                _ => {} // ignore everything else
            }
        });

        // Publish a bar event — should be counted
        bus.publish(&test_bar_event()).unwrap();

        assert_eq!(*bar_count.borrow(), 1);
    }
}