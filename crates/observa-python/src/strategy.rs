use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule};
use std::path::Path;

use observa_core::bar::Bar;
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};

use crate::bar::bar_to_py;
use crate::error::BridgeError;
use crate::portfolio::portfolio_to_py;
use crate::signal::signal_from_py;

// ────────────────────────────────────────────────
// PyStrategy
// ────────────────────────────────────────────────

/// Wraps a Python strategy class instance and
/// implements the Rust Strategy trait.
///
/// The engine calls Rust methods — this struct
/// forwards each call into Python via PyO3.
pub struct PyStrategy {
    /// The Python strategy instance
    /// (result of calling MyStrategy())
    instance: PyObject,

    /// Name of the strategy class — used in errors
    class_name: String,
}

impl PyStrategy {
    /// Loads a Python file, finds the strategy class
    /// inside it, and instantiates it.
    ///
    /// # Arguments
    /// * `file_path` — path to the .py file
    /// * `class_name` — name of the Strategy subclass
    ///                  inside the file (e.g. "EMACrossover")
    pub fn load(
        file_path: &Path,
        class_name: &str,
    ) -> Result<Self, BridgeError> {
        let path_str = file_path.to_string_lossy().to_string();
        let source = std::fs::read_to_string(file_path)
            .map_err(|e| BridgeError::FileLoadError(
                path_str.clone(),
                e.to_string(),
            ))?;

        Python::with_gil(|py| {
            // Load the file as a Python module
            let module = PyModule::from_code_bound(
                py,
                &source,
                &path_str,
                "user_strategy",
            ).map_err(|e| BridgeError::FileLoadError(
                path_str.clone(),
                e.to_string(),
            ))?;

            // Find the strategy class by name
            let class = module
                .getattr(class_name)
                .map_err(|_| BridgeError::ClassNotFound(
                    class_name.to_string()
                ))?;

            // Instantiate the class — calls __init__
            let instance = class
                .call0()
                .map_err(|e| BridgeError::MethodCallError(
                    "__init__".to_string(),
                    e.to_string(),
                ))?
                .into();

            Ok(PyStrategy {
                instance,
                class_name: class_name.to_string(),
            })
        })
    }

    /// Helper — calls a method on the Python instance
    /// with no arguments.
    fn call_method0(&self, method: &str)
        -> Result<(), BridgeError>
    {
        Python::with_gil(|py| {
            self.instance
                .call_method0(py, method)
                .map_err(|e| BridgeError::MethodCallError(
                    method.to_string(),
                    e.to_string(),
                ))?;
            Ok(())
        })
    }
}

// ────────────────────────────────────────────────
// Strategy trait implementation
// ────────────────────────────────────────────────

impl Strategy for PyStrategy {
    /// Calls initialize() on the Python strategy.
    fn initialize(&mut self) {
        if let Err(e) = self.call_method0("initialize") {
            eprintln!(
                "[PyStrategy] initialize() failed on '{}': {}",
                self.class_name, e
            );
        }
    }

    /// Calls on_bar() on the Python strategy,
    /// passing bar and portfolio as Python dicts.
    /// Converts the returned list of signal dicts
    /// into Rust StrategySignals.
    fn on_bar(
        &mut self,
        bar: &Bar,
        portfolio: &PortfolioView,
        history: &[Bar],
    ) -> Vec<StrategySignal> {
        Python::with_gil(|py| {
            // Convert bar and portfolio to Python dicts
            let py_bar = match bar_to_py(py, bar) {
                Ok(d)  => d,
                Err(e) => {
                    eprintln!("[PyStrategy] bar conversion failed: {}", e);
                    return vec![];
                }
            };

            let py_portfolio = match portfolio_to_py(py, portfolio) {
                Ok(d)  => d,
                Err(e) => {
                    eprintln!("[PyStrategy] portfolio conversion failed: {}", e);
                    return vec![];
                }
            };

            // Build history as a Python list of dicts
            let py_history = PyList::empty_bound(py);
            for h_bar in history {
                if let Ok(d) = bar_to_py(py, h_bar) {
                    py_history.append(d).ok();
                }
            }

            // Call on_bar(bar, portfolio, history)
            let result = match self.instance.call_method1(
                py,
                "on_bar",
                (py_bar, py_portfolio, py_history),
            ) {
                Ok(r)  => r,
                Err(e) => {
                    eprintln!(
                        "[PyStrategy] on_bar() failed on '{}': {}",
                        self.class_name, e
                    );
                    return vec![];
                }
            };

            // Convert result to a list of signal dicts
            let signal_list = match result.downcast_bound::<PyList>(py) {
                Ok(l)  => l.to_owned(),
                Err(_) => {
                    // on_bar returned None or non-list — no signals
                    return vec![];
                }
            };

            // Convert each dict to a StrategySignal
            signal_list
                .iter()
                .filter_map(|item| {
                    match signal_from_py(py, &item) {
                        Ok(signal) => Some(signal),
                        Err(e) => {
                            eprintln!(
                                "[PyStrategy] invalid signal: {}",
                                e
                            );
                            None
                        }
                    }
                })
                .collect()
        })
    }

    /// Calls teardown() on the Python strategy.
    fn teardown(&mut self) {
        if let Err(e) = self.call_method0("teardown") {
            eprintln!(
                "[PyStrategy] teardown() failed on '{}': {}",
                self.class_name, e
            );
        }
    }
}

// ────────────────────────────────────────────────
// Loader — finds the strategy class name
// automatically if not specified
// ────────────────────────────────────────────────

/// Scans a Python file and returns the name of the
/// first class that inherits from Strategy.
///
/// This lets users run without specifying --class:
///   observa run --strategy my_file.py
///   (class name detected automatically)
pub fn detect_strategy_class(
    file_path: &Path,
) -> Result<String, BridgeError> {
    let source = std::fs::read_to_string(file_path)
        .map_err(|e| BridgeError::FileLoadError(
            file_path.to_string_lossy().to_string(),
            e.to_string(),
        ))?;

    // Strategy 1
    // Simple heuristic — find "class Foo(Strategy):"
    // explicit inheritance is the cleanest signal
    for line in source.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("class ") && trimmed.contains("Strategy") {
            // Extract class name between "class " and "("
            let after_class = &trimmed["class ".len()..];
            if let Some(paren_pos) = after_class.find('(') {
                let class_name = after_class[..paren_pos].trim();
                if !class_name.is_empty() {
                    return Ok(class_name.to_string());
                }
            }
        }
    }

    // Strategy 2 - look for any class that has all three
    // required methods: initialize, on_bar, teardown
    // This handles plain Python classes with no inheritance
    let mut current_class: Option<String> = None;
    let mut has_initialize = false;
    let mut has_on_bar = false;
    let mut has_teardown = false;

    for line in source.lines() {
        let trimmed = line.trim();

        // Found a class definition
        if trimmed.starts_with("class ") && trimmed.contains(':') {
            // Check of previous class was a valid strategy
            if let Some(ref name) = current_class {
                if has_initialize && has_on_bar && has_teardown {
                    return Ok(name.clone());
                }
            }
            // Start with tracking new class
            let after_class = &trimmed["class ".len()..];
            let end = after_class.find(|c| c == '(' || c == ':')
                .unwrap_or(after_class.len());
            current_class = Some(after_class[..end].trim().to_string());
            has_initialize = false;
            has_on_bar = false;
            has_teardown = false;
        }

        // TRack method definitions inside current class
        if current_class.is_some() {
            if trimmed.starts_with("def initialize") { has_initialize = true; }
            if trimmed.starts_with("def on_bar")      { has_on_bar     = true; }
            if trimmed.starts_with("def teardown")   {has_teardown    = true; }
        }
    }

    // Check the last class in the file
    if let Some(ref name) = current_class {
        if has_initialize && has_on_bar && has_teardown {
            return Ok(name.clone());
        }
    }

    Err(BridgeError::ClassNotFound(
        "no Strategy class found — class must have \
         initialize(), on_bar(), and teardown() methods".to_string()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn write_temp_strategy(content: &str) -> NamedTempFile {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(content.as_bytes()).unwrap();
        // Rename to .py so PyModule loads it correctly
        file
    }

    #[test]
    fn detects_strategy_class_by_methods() {
        let mut file = NamedTempFile::new().unwrap();
        writeln!(file, "class EMACrossover:").unwrap();
        writeln!(file, "    def initialize(self): pass").unwrap();
        writeln!(file, "    def on_bar(self, bar, portfolio, history): return []").unwrap();
        writeln!(file, "    def teardown(self): pass").unwrap();

        let name = detect_strategy_class(file.path()).unwrap();
        assert_eq!(name, "EMACrossover");
    }

    #[test]
    fn detects_strategy_class_by_inheritance() {
        let mut file = NamedTempFile::new().unwrap();
        writeln!(file, "class MyCrossover(Strategy):").unwrap();
        writeln!(file, "    pass").unwrap();

        let name = detect_strategy_class(file.path()).unwrap();
        assert_eq!(name, "MyCrossover");
    }

    #[test]
    fn returns_error_when_no_strategy_class() {
        let mut file = NamedTempFile::new().unwrap();
        writeln!(file, "class Foo:").unwrap();
        writeln!(file, "    def some_method(self): pass").unwrap();

        let result = detect_strategy_class(file.path());
        assert!(result.is_err());
    }

    #[test]
    fn loads_and_calls_minimal_python_strategy() {
        pyo3::prepare_freethreaded_python();

        let strategy_code = r#"
class MinimalStrategy:
    def initialize(self): pass
    def on_bar(self, bar, portfolio, history): return []
    def teardown(self): pass
"#;
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(strategy_code.as_bytes()).unwrap();

        let mut strategy = PyStrategy::load(
            file.path(),
            "MinimalStrategy",
        ).unwrap();

        // Should not panic
        strategy.initialize();

        let bar = observa_core::bar::Bar::new(
            chrono::Utc::now(),
            1.1376, 1.13787, 1.1376, 1.13786,
            Some(278.19),
        );
        let portfolio = observa_engine::strategy::PortfolioView::empty(
            10_000.0
        );
        let signals = strategy.on_bar(&bar, &portfolio, &[]);
        assert!(signals.is_empty());

        strategy.teardown();
    }
}