use thiserror::Error;

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("Event Bus failed to write to event log: {message}")]
    EventLogWriteError { message: String },

    #[error("Subscriber '{name}' panicked: {message}")]
    SubscriberPanic { name: String, message: String },

    #[error("No data loaded — call load_data() before run()")]
    NoDataLoaded,

    #[error("Engine is already running")]
    AlreadyRunning,

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}