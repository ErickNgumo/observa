# Observa Current State

This document is a migration of the **current-state claims in the source knowledge base**. It should be updated whenever repository reality changes.

## Implemented

### Data
- CSV OHLCV loader.
- Timestamp parsing.
- Bar validation.
- Monotonic timestamp validation.
- Gap detection before run start.

### Replay / Engine
- Bar-by-bar replay.
- Strategy invocation through the Python bridge.
- Historical-only strategy history.
- Signal to order-intent flow.

### Python bridge
- PyO3 embedding.
- Python strategy loading.
- Class auto-detection.
- Bar / portfolio conversion.
- Drawing conversion.

### Execution
- Market-order fills.
- Fixed spread.
- Slippage.
- Commission configuration.
- Post-fill SL/TP validation.
- Margin validation.

### Portfolio
- Multiple positions.
- Ticket-based position closing.
- SL/TP checks.
- Realised and unrealised PnL.
- Per-bar mark-to-market snapshots.

### Metrics
- Equity curve.
- Drawdown.
- Core performance and trade statistics.

### Visualization
- Candlestick chart.
- EMA lines in the documented example.
- Entry/exit markers.
- Trade connecting lines.
- Equity curve.
- Trade log.
- Metrics panel.
- Drawdown highlighting.
- Strategy drawings.
- Replay controls.

### CLI
- `observa init`
- `observa run --strategy ... --data ...`
- YAML configuration.

## Partially implemented / known issues

### InstrumentSpec
The source KB says `InstrumentSpec` exists and is loaded from configuration, but its use is not fully wired into all PositionOpenedEvent / PositionClosedEvent construction. Deprecated `pct_equity` and `pct_balance` fields remain in events.

### Metrics / Sharpe
The source KB says the Sharpe implementation was improved, including per-bar equity sampling, sample variance, and compound risk-free conversion, but still regards the result as potentially inflated on small samples.

### Python strategy bridge
`on_fill()` is not wired. Python-side indicator registration is not implemented. Python strategy execution is single-threaded because of the GIL.

### Visualization
Known issues include floating-point display noise, region rendering workaround, bar-color rendering, and drawdown highlight matching.

## Known legacy/prototype components

- `observa-runner` is described as an earlier prototype and largely superseded.
- `observa-server` is described as an earlier prototype; `observa-cli` is the documented entry point.

## Missing / planned work explicitly identified by the source KB

- Finish InstrumentSpec wiring and remove deprecated exposure fields.
- Add sample EURUSD M15 CSV.
- Clearly mark aspirational strategy documentation as not implemented.
- UI polish.
- Full test verification after recent changes.
- CI/CD.
- Testing guide, contribution guide, instrument guide, debugging guide, changelog.
- Pip packaging through maturin and wheel builds — historically v1.0, but now proposed for MVP.

## Important maintenance note

This file is not proof that the code currently matches every statement above. Before implementation work, agents should verify relevant claims against the repository source and tests.
