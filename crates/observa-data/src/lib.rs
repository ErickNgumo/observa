//! observa-data — CSV reading, validation, and dataset management.

pub mod csv_reader;
pub mod validator;

pub use csv_reader::{CsvReader, CsvReaderError};
pub use validator::{DatasetValidator, ValidationError};
