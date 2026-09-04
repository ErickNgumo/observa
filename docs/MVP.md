# Observa MVP

## 1. Purpose

The MVP should prove one complete product loop:

> A trader can install Observa, provide a supported dataset and Python strategy, run a deterministic backtest with realistic execution assumptions, visually replay what happened, and inspect trustworthy core statistics.

## 2. MVP scope inherited from the source knowledge base

The source KB explicitly excludes the following from MVP:

- Tick data support
- Multi-symbol strategies
- Limit and stop orders
- Dynamic spread/slippage
- Order book simulation
- Multi-timeframe strategies
- Strategy hot reload
- Optimization / parameter search
- Monte Carlo analysis
- Trade journaling UI
- Live or paper trading
- Click trade-log row to jump to chart

These exclusions are retained here unless explicitly changed by engineering leadership.

## 3. Capabilities required for MVP

### Data

- Load historical OHLCV CSV data.
- Validate price relationships, positivity, timestamp ordering, and gaps.
- Provide a small sample dataset for quick-start testing.

### Strategy

- Python class-based strategy contract.
- Strategy receives bar, portfolio, and past history.
- Strategy emits signals and optional drawings.
- Strategy cannot directly execute orders.

### Execution

- Market-order execution for MVP.
- Spread and slippage.
- Commission.
- Minimum lot / maximum lot validation.
- Stop/target distance validation after actual fill price is known.
- Margin validation.

### Portfolio

- Multiple simultaneous positions.
- Ticket-based position identification.
- Realised and unrealised PnL.
- SL/TP checking on every bar.
- Mark-to-market equity snapshot on every bar.

### Visualization

- Candlesticks.
- Trade entries and exits.
- Equity curve.
- Trade log.
- Core metrics.
- Replay controls.
- Strategy drawings.

### Statistics

The source implementation currently reports:

- Total return
- Annualised return
- Maximum drawdown
- Sharpe ratio
- Calmar ratio
- Win rate
- Profit factor
- Expectancy
- Average win
- Average loss
- Largest win
- Largest loss

These definitions must be audited before release rather than assumed correct merely because they exist in code.

## 4. Packaging — proposed MVP change

The historical roadmap placed pip packaging in v1.0. Engineering leadership has since identified distribution friction as an MVP problem.

**Proposed change:** make `pip install observa` an MVP requirement so a user does not need a Rust toolchain to use the released product.

This is a proposal pending implementation and packaging verification. It should not be treated as completed merely because this document states the desired requirement.

## 5. MVP acceptance criteria

### Installation

On a clean supported environment, a user can install Observa without installing Rust manually.

### First successful run

A new user can use the repository's example/sample project to perform a complete backtest without discovering undocumented commands.

### Correctness

A deterministic known-answer test produces the expected trades, PnL, equity, and core metrics.

### Observability

Every user-visible trade and portfolio change shown in the UI can be traced to the event log.

### Realistic execution

Spread, slippage, commission, SL/TP behavior, and validation rules behave according to the approved execution specification.

### Reproducibility

The same strategy, dataset, and configuration produce the same result.

## 6. Explicit non-goals

MVP is not a live trading platform, optimizer, data marketplace, multi-asset research platform, tick-level simulator, or strategy generator.
