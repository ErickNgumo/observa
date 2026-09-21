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

### Agent / notebook interface
- Single programmatic replay entry point
  `observa.replay(run_dir_or_result, *, port=None, block=True, open_browser=False)`.
- Automatic free-port binding (`port=None` binds port 0) and strict explicit
  ports (`REPLAY_PORT_IN_USE` with `details["port"]`).
- Non-blocking `ReplayServer` handle (`.url`, `.port`, `.run_dir`,
  `.is_running`, idempotent `.stop()`, context manager, daemon thread) while
  `block=True` remains the default.
- Machine-readable result summaries: `result.summary()` and
  `observa.run_summary(run_dir)`; the latter reads only `run.json`/`metrics.json`
  and duplicates no arrays.
- Machine-readable failure codes on the existing exception classes: `exc.code`,
  `exc.details`, and the `observa.error_code(exc)` helper. Order rejections
  remain canonical `order_rejected` events, not exceptions.

### Run inspection
- `observa.inspect_run(run_dir)` → `PersistedRun`: structured, read-only access
  to a persisted run's canonical history (`meta`, `metrics`, `events`, `event`,
  `bar`, `position`, `order`, `positions`, `trades`, `rejections`).
- Events are parsed once and indexed by `event_seq`, bar chronology bucket,
  `position_id` and `order_seq`; nothing is recomputed and the run directory is
  never written to.
- Canonical order linkage in both directions: `position(pid)["opening_order"]`
  and `["closing_order"]` expose the full order lifecycle, and
  `order(seq)["position_id"]` names the position that order opened or closed.
- A closing order is recorded whenever one exists (`position_closed.order_seq`,
  OBS-SCHEMA-02). It is absent for protective SL/TP exits, which are not orders,
  and for runs produced before that linkage was persisted.
- A present canonical `order_seq` reference that resolves to no order is
  reported as `RUN_ARTIFACTS_INVALID`, never silently degraded to `None`.

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

The installed `observa` console script (from the wheel) provides:

- `observa replay <run-dir> [--port <port>]`
- `observa mcp --runs-dir <path>` (stdio only; MCP ships with the standard install)
- `observa agent-spec [--json] [--out FILE]` (OBS-AI-04)
- `observa validate-strategy FILE [--class NAME] [--json] [--smoke]` (OBS-AI-04)

Not implemented in the shipped CLI: `observa init`, `observa run --strategy …`
and YAML configuration. A `run --strategy` subcommand exists only in the Rust
`observa-cli` binary, which is **not** part of the release assets and uses the
legacy/dev-only bridge in `crates/observa-python` (see `docs/STRATEGY_API.md`).

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
