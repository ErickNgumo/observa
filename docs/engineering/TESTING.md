# Observa Testing

## Philosophy

Tests should prove invariants and known behavior, not just execute code.

## Rules

- Every new feature has tests.
- Every bug fix has a regression test.
- Validation should report all relevant errors rather than only the first.
- PyO3 tests must initialize the Python runtime as required by the project implementation.
- Use the Python mock harness for rapid strategy-side iteration where appropriate.

## Test levels

### Unit tests

Test individual calculations and invariants inside each crate/module.

### Integration tests

Verify interactions between crates and event sequences.

### Known-answer tests

Use deterministic fixtures where exact expected PnL, fills, positions, and metrics are known.

### End-to-end tests

Verify the user workflow from loading data and strategy through completed replay and rendered output/API payload.

## High-value regression areas

- SL/TP validation after spread/slippage.
- SL slippage versus TP no-slippage behavior.
- Portfolio snapshots every bar.
- Timestamp correctness using market-data timestamps.
- InstrumentSpec exposure calculations.
- Position ticket closing.
- PyO3 conversion contracts.
- Event chain integrity.
- Documentation/API synchronization.

## CI expectations from the source KB

The historical proposal calls for GitHub Actions to run tests on pushes and to add checks that strategy-facing documentation stays synchronized with the Rust conversion code.
