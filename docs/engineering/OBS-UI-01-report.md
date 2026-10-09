# OBS-UI-01 Replay Workspace Redesign Report

Review outcome: visually approved by the user; merge to master authorized.
The report and screenshots below preserve the original review evidence.
Final focused regressions passed again before integration. No release authorized.

The real EUR/USD demo ran using `examples/eurusd_demo.py` with only its
create-only output path changed to `runs/obs-ui-01-demo`. The review server is
`http://127.0.0.1:8765`. Canonical results: 600 bars, 2,495 events, 11 closed
trades, one open position, balance 10,482.00 and equity 10,654.00.

## Layout

The inspector defaults to 280px. Drag its visible top handle, or focus the
separator and use Up/Down in 24px increments. It has a 130px minimum and a
viewport-dependent maximum that reserves about 220px for the price chart.
Collapse leaves a 40px tab strip; selecting a tab expands it. Double-clicking
the handle restores the default. Height, tab and collapse state survive reloads
within the current browser session. ResizeObserver resizes both chart canvases.

The existing layout implementation was extended, including fixing a stray CSS
brace that prevented the Trade Log's intended scroll-container rule from applying.
The page remains fixed to the viewport; evidence areas own their scrolling.

## Trade Log

The table scrolls independently in both directions where needed, with a sticky
header. Columns: number, BUY/SELL side, entry UTC, exit UTC, entry price, exit
price, canonical net P&L, elapsed duration and exit reason. Duration is wall-clock
elapsed time between the recorded opening/closing bar timestamps; it includes
market closures. Missing timestamps produce an em dash. Stops/targets remain
available in Positions. P&L has a signed value as well as semantic color.

Click or press Enter/Space on a trade to select it, pause playback/follow, focus
the chart on the recorded trade period, and highlight its evidence on price and
equity. Selection does not change replay position or reconstruct trade pairing.
The empty state explicitly says there are no closed trades yet.

## Inspector

- **Account:** six compact recorded snapshot figures: balance, equity, used/free
  margin, unrealised and realised P&L. The selected bar is identified above them.
- **Signals / Decisions:** signal count and the strategy's verbatim reasons at
  this bar. Missing reasons are stated explicitly; none are invented.
- **Positions:** all positions opened by this point, with exact recorded open/
  closed state, protective levels and abbreviated tickets with full hover titles.
- **Orders:** lifecycle state up to the selected bar, including rejection details.
  Created bar uses the same one-based presentation as the replay progress label.
- **Strategy series:** the existing annotation legend remains available.
- **Events:** activity at this bar with readable summaries. Expand an event to
  inspect its complete recorded JSON, including original zero-based bar indices.

Position and order tables have bounded scroll areas, sticky headers and keyboard/
mouse row selection. The Inspector itself scrolls to reach later sections.

## Metrics

A compact six-column overview shows Total Return, Max Drawdown, Sharpe Ratio,
Profit Factor, Win Rate and Trades. Smaller Performance, Risk and Trade Statistics
groups show the remaining available canonical metrics. Rows are approximately
62px high rather than large dashboard tiles.

The panel explicitly identifies these as **complete-run results**, independent
of the selected bar. Missing ratios show N/A. The drawdown inspection action is
available once the recorded period has been replayed; backward seeks remove
outlines belonging to unrevealed history. No financial metric is calculated here.

## Equity Curve

The legend correctly distinguishes solid equity, dashed balance and the red
maximum-drawdown interval. Both financial curves use recorded snapshots. The
curve fits the revealed history and resizes with the inspector. Hover identifies
the equity observation; the existing drawdown investigation remains available.

## Header

Run/strategy identity sits on the left, replay and annotation controls together
in the center, and instrument/account/progress/theme information to the right.
At laptop widths, the status group occupies a separate compact row to prevent
overlap. Disabled buttons and keyboard focus are visible.

Symbol comes from the existing replay `run.symbol`. Interval is now forwarded
unchanged from persisted `config.dataset.interval`; missing intervals are omitted
and missing symbols use “Loaded run.” The optional instrument price precision is
also forwarded from `config.instrument.price_decimals`, fixing the two-decimal
FX price axis. These are additive **display-only adapter fields** in
`crates/observa-engine/src/replay.rs`; persisted schemas and economics are unchanged.

## Chart

Auto-follow preserves bar spacing and scrolls the latest candle to approximately
80% of the time-scale width, with visible-price autoscaling. It never continually
fits all candles. Mouse-wheel zoom and drag pan suspend follow. Resume follow
returns to the latest replay candle at the current spacing; Fit all independently
fits the revealed candles and leaves follow suspended. Reset enables follow again.

## Chart ↔ Inspector

Trade selection focuses/highlights its period. Clicking a revealed candle or a
marker at that time selects that replay bar, pauses playback, and opens Inspector.
Account, positions, orders, decisions and events rebuild through the existing
canonical reducer. Seeking backward from completion also re-enables Play.

## Tooltips

Short help is available for Balance, Equity, Used Margin, Free Margin, Unrealised
P&L, Realised P&L, Order State, Position State, Signal/Decision, Total Return,
Annualised Return, Sharpe Ratio, Calmar Ratio, Profit Factor, Expectancy, Win Rate,
Max Drawdown and Current Drawdown. Resize, follow, fit, annotations and navigation
controls have labels/titles. Essential labels remain visible without hovering.

## Visual design

Dark neutral surfaces, restrained teal accent, semantic green/red, compact
numeric typography, subtle separators and consistent small radii. Removed the
remote font request and decorative brand/progress glow. Trade investigation uses
the accent; drawdown investigation uses red. Negative-zero and object-summary
noise are removed from display only. Theme support remains; Paper was also captured.

## Responsive checks

Real Chromium checks and screenshots cover 1920×1080 and 1366×768. Both have no
page-level horizontal overflow. The laptop toolbar wraps cleanly; the maximum
inspector height leaves the price chart usable. Tables scroll within their own
containers. Desktop research use remains the target.

## Tests

All final checks passed:

| Check | Result |
| --- | --- |
| `node python/tests/replay.test.js` | 17 groups |
| `node python/tests/drawings.test.js` | 12 groups |
| `node python/tests/workspace.test.js` | Metadata fallbacks, follow spacing/position, override state, resize limits, duration, negative-zero display |
| `harness/replay_workspace_review.py` | 39 real-browser checks; no JavaScript errors |
| `cargo test -p observa-engine --offline` | 88 tests, including adapter, persistence, execution, annotations and reasons |
| `python/tests/test_canonical_baseline.py` | 33 checks; existing known answers unchanged |
| `python/tests/test_demo.py` | 29 checks |
| `python/tests/test_ai_interface.py` | 76 API/replay/server/CLI checks |
| Native extension release build | Passed |
| `git diff --check` | Passed |

Environment notes: socket-based tests needed execution outside the filesystem/
network sandbox. The first API test attempt used an environment without its CLI;
rerunning with `.venv-ai/bin/python` and `PYTHONPATH=python/python` passed all 76.
Existing Rust unused-import/variable/dead-code warnings remain; none were hidden
or modified. Playwright was installed only in the development environment, with
no new runtime dependency. The native extension was built locally for verification.

Browser reproduction (with the review server running):

```bash
OBSERVA_CHROMIUM=/path/to/chromium .venv-dev/bin/python harness/replay_workspace_review.py
```

The script drives the actual served interface, uses the recorded demo payload,
and saves unmodified browser screenshots. `checks.json` records the checks.

## Screenshots

All files are in `docs/engineering/obs-ui-01-screenshots/`:

1. [Main / default inspector, 1920×1080](obs-ui-01-screenshots/01-main-default-1920.png)
2. [Collapsed inspector, 1920×1080](obs-ui-01-screenshots/02-main-collapsed-1920.png)
3. [Trade Log and selected trade, 1920×1080](obs-ui-01-screenshots/03-trade-log-1920.png)
4. [Expanded Inspector, 1920×1080](obs-ui-01-screenshots/04-inspector-expanded-1920.png)
5. [Orders / event details, 1920×1080](obs-ui-01-screenshots/05-inspector-events-1920.png)
6. [Metrics, 1920×1080](obs-ui-01-screenshots/06-metrics-1920.png)
7. [Expanded Equity Curve, 1920×1080](obs-ui-01-screenshots/07-equity-expanded-1920.png)
8. [Inspector, 1366×768](obs-ui-01-screenshots/08-inspector-1366.png)
9. [Trade Log, 1366×768](obs-ui-01-screenshots/09-trade-log-1366.png)
10. [Expanded Metrics, 1366×768](obs-ui-01-screenshots/10-metrics-expanded-1366.png)
11. [Equity Curve, 1366×768](obs-ui-01-screenshots/11-equity-1366.png)
12. [Paper theme, 1366×768](obs-ui-01-screenshots/12-light-theme-1366.png)
13. [Recorded strategy decision, 1920×1080](obs-ui-01-screenshots/13-strategy-decision-1920.png)

## Deferred ideas

- Exact event-marker → individual event-row targeting beyond selecting its bar.
- Search, filtering and virtualization for exceptionally large evidence tables.
- Preferences across browser sessions; current session storage is deliberate.

Existing GIF media is unchanged; demo data, annotations and replay controls remain
compatible. No replacement GIF was generated. Human visual acceptance was subsequently granted and merge to master authorized.

- Trade Log scrollable: YES
- Inspector panel resizable: YES
- Inspector understandable without internal knowledge: YES
- Metrics redesigned: YES
- Symbol/timeframe dynamic: YES
- Replay auto-follow implemented: YES
- Manual zoom/pan respected: YES
- GIF/demo compatibility preserved: YES
- Execution/economics unchanged: YES
- Ready for visual review: YES
