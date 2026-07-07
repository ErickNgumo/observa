use thiserror::Error;

#[derive(Debug, Error)]
pub enum BridgeError {
    #[error("python error: {0}")]
    PythonError(String),

    #[error("Strategy class '{0}' not found in file")]
    ClassNotFound(String),

    #[error("Failed to load strategy file '{0}':{1}")]
    FileLoadError(String, String),

    #[error("Invalid signal from strategy: {0}")]
    InvalidSignal(String),

    #[error("Strategy method '{0} failed: {1}")]
    MethodCallError(String, String),
}

impl From<pyo3::PyErr> for BridgeError {
    fn from(e: pyo3::PyErr) -> Self {
        BridgeError::PythonError((e.to_string()))
    }
}