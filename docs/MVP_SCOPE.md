# Observa — MVP Scope Lock

> This document is frozen. Nothing is added to this list without
> removing something else first. When in doubt, cut.

---

## The MVP in One Sentence

A trader loads a CSV and a Python strategy, presses play, and watches
their logic execute bar by bar on a real chart — with indicators drawing
in real time, entries and exits marked when they happen, and basic
execution costs applied.

---

## What the MVP Does

### Data
- Load a single CSV file (OHLCV format)
- Single asset only
- Bar-level data only (minute, hourly, daily)
- Validate monotonic timestamps on load
- Detect and report data gaps before the run starts

### Strategy
- Accept a single Python strategy file
- Expose a simple `on_bar(bar, context)` hook
- Allow user to define and plot custom indicators
- Provide read-only portfolio state via context
- One strategy per run

### Replay Engine
- Bar-by-bar replay
- Play, pause, and step-forward controls
- Strict monotonic time progression
- Deterministic — same inputs always produce same outputs
- No future data leakage — strategy sees only closed bars

### Execution
- Market orders only
- Fixed spread applied at fill time
- Fixed slippage applied at fill time
- Fixed commission applied at fill time
- Reject orders where stop loss is too close to entry price

### Visualization
- Candlestick chart
- User-defined indicator plots
- Entry and exit markers on the chart
- Basic equity curve
- Trade log (list of all trades with entry, exit, PnL)

### Metrics
- Total return
- Max drawdown
- Win rate
- Basic trade statistics (average win, average loss)

---

## What the MVP Does Not Do

These are explicitly excluded. They do not get designed for, coded
for, or accidentally supported.

| Excluded Feature | Why It Waits |
|---|---|
| Tick data | Adds complexity before core is proven |
| Multi-symbol | Out of scope until single-asset is solid |
| Limit and stop orders | Market orders prove the architecture first |
| Dynamic spread / slippage | Fixed models are sufficient for MVP correctness |
| Order book simulation | High complexity, low MVP value |
| Multi-timeframe strategies | Significant engine complexity |
| Strategy hot reload | Breaks determinism guarantees |
| Optimization / parameter search | Post-MVP research feature |
| Monte Carlo analysis | Derived from a working metrics layer |
| Trade journaling | First feature added after MVP ships |
| Advanced metrics | Basic metrics prove the pipeline first |
| Live or paper trading | Comes only after correctness is proven |

---

## The Two Non-Negotiable Invariants

These are not features. They are guarantees the MVP must never violate.

**1. Deterministic Replay**
The same CSV, the same strategy, and the same configuration must
produce identical results every single time. If this is ever false,
nothing in Observa can be trusted.

**2. No Future Data Leakage**
The strategy can only see bars that have already closed. It must be
structurally impossible — not just conventionally avoided — for strategy
logic to access any future price data.

---

## MVP Success Criteria

The MVP is complete when a trader can:

1. Load a CSV and a Python strategy file
2. Press play and watch the strategy execute bar by bar
3. See their indicators drawing on the chart in real time
4. See entry and exit markers appear at the correct bars
5. See spread, slippage, and commission reflected in PnL
6. Trust that running it twice gives the same result

If all six are true, the MVP is done. Everything else is next.

---

*This scope was locked during the design phase. Additions require
explicit justification and removal of something else.*