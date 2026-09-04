# Visualization Domain

## Purpose

Provide the primary visual debugging interface for the backtest.

## Current frontend

- Vanilla JavaScript.
- TradingView Lightweight Charts v5.
- Rust HTTP server exposes an event JSON array.
- Frontend replays event-by-event.

## Documented features

- Candlestick chart
- EMA lines in the documented example
- Entry/exit markers
- Trade connection lines
- Equity curve
- Trade log
- Metrics panel
- Maximum drawdown highlight
- Drawdown banner
- Strategy drawings
- Play / pause / step / reset
- Speed controls
- Tabbed panels

## Known visual issues

- Floating-point formatting noise.
- Region drawing workaround.
- Bar-color state not fully reflected in rendering.
- Drawdown highlight can be off by one bar due to closest-point matching.

## Principle

The visualization layer must not independently recompute financial truth. It renders information derived from events.
