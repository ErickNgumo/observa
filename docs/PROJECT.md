# Observa Project

## 1. What Observa is

Observa is an event-driven visual backtesting engine for algorithmic traders. Traders write Python strategies that execute against historical OHLCV data, then watch strategy decisions, orders, positions, and portfolio changes replay bar by bar in a browser-based chart.

## 2. Problem

Traditional backtesting tools primarily return numerical results. This creates two important failure modes:

1. Silent strategy or implementation errors can still produce plausible-looking results.
2. Unrealistic execution assumptions can make a backtest look better than live trading.

Observa addresses these by making execution observable and by simulating execution details such as spread, slippage, commission, and stop validation.

## 3. Users

Primary: algorithmic traders who write Python strategies and want to verify strategy behavior visually before trading live.

Secondary: developers building trading tools who need a visual debugging layer.

Tertiary: CS students and researchers studying strategy behavior.

## 4. North star

> **The goal is not a better backtest. The goal is the end of blind trust.**

## 5. Product insight

A number tells the user the result. Replay should help the user understand why the result happened.

The chart is therefore a debugging and verification interface, not decoration.

## 6. Core philosophy

### Seeing is understanding
Every meaningful event during a backtest should be observable.

### Events are truth
The event log is the source of truth. Visualization and metrics derive from events.

### Realism by default
Spread, slippage, commission, and execution validation are part of the simulation model rather than optional cosmetic settings.

### Determinism
The same inputs must produce the same outputs.

### No future leakage
The strategy receives only historical information available at the current point in replay.

## 7. Long-term direction from the source knowledge base

The historical plan describes a platform where:

- Python is the primary strategy language.
- End users do not need Rust knowledge.
- Distribution is intended to become pip-installable.
- Rich indicators and drawing capabilities may grow over time.
- Live data, community sharing, and data products are long-term possibilities.

These are long-term direction, not automatic MVP commitments.
