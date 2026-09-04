# Data Domain

## Current MVP input

Historical single-symbol OHLCV CSV.

Required columns:

- timestamp
- open
- high
- low
- close

Volume is optional.

## Validation

The documented loader:

- parses timestamps
- checks positive prices
- checks high/low relationships
- requires monotonic timestamps
- detects gaps before a run starts
- produces contextual errors including row/field information

## Not MVP

- tick data
- multi-symbol data
- built-in download connectors
- multi-timeframe loading

## Open questions

The source KB leaves data-gap handling unresolved: gaps can be reported, but it is undecided whether future versions should fill, skip, or visually flag them.
