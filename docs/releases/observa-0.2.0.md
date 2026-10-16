# Observa 0.2.0

This release makes Observa's results harder to misread. Strategy and data
mistakes that used to be silently ignored now fail with a clear error, long
intraday runs are fast, and strategy metrics state exactly what they assume —
including when a figure cannot honestly be computed.

Execution and backtest economics are unchanged for valid inputs: canonical
events, fills and P&L are byte-identical to 0.1.6 (independently checked).

## Strategy metrics you can trust

- **No silent annualisation.** 0.1.x annualised every run as if its bars were
  daily, so a 15-minute run reported a meaningless "annualised return" and
  Sharpe ratio (the bundled demo turned an 8-day +6.5 % into "2.7 %
  annualised"). Annualised metrics now need the number of bars per year:
  pass `observa.run(..., bars_per_year=...)` or `Config(bars_per_year=...)`.
  Daily bars default to 252 and weekly bars to 52 when the bar spacing agrees
  with the declared interval; intraday bars are never guessed.
- **Short samples are not annualised.** Returns over less than one year are
  shown as total returns only (GIPS convention).
- **Unavailable means unavailable.** A metric that cannot be computed (no
  losing trades for a profit factor, too few returns for a Sharpe ratio,
  equity below zero …) is `null` with a plain-language reason, never `0`.
- **Assumptions and sample sizes are recorded** in `metrics.json`: bars per
  year and where it came from, risk-free rate, currency, number of bars,
  returns and closed trades, calendar span.
- **New metrics:** net profit, annualised volatility, Sortino ratio, drawdown
  amount, recovery date and longest drawdown, payoff ratio, break-even trades,
  longest losing streak, average holding time, time in market, maximum gross
  leverage, and an execution-cost breakdown (commission, spread, slippage).
  Definitions and edge cases: `docs/metrics.md`.
- **Fixed:** total return and drawdowns are measured from the starting
  balance; a zero-P&L trade is break-even, not a win.

## A clearer metrics view in replay

- Metrics grouped into Overview, Returns, Risk, Exposure and costs, and Trades.
- Every figure says whether it is a whole-run total or annualised; the sample
  size and annualisation assumption are shown above the figures.
- Unavailable figures are marked as such with the reason.
- A closed-trade outcome chart and a cost breakdown.
- Honest empty states for runs without trades; runs recorded by 0.1.x still
  open and are labelled as legacy.
- Works at laptop and phone widths, in every theme.

## Mistakes now fail loudly

- A signal key Observa does not know — for example `stop_loss` instead of
  `sl` — used to be ignored, so the position opened **without a stop**. The
  run now stops with `SIGNAL_FIELD_UNKNOWN` and suggests the right key.
- Returning `None`, a bare signal dict, or a dict without a `signals` list from
  `on_bar` used to give a "successful" zero-trade run. It now fails with
  `STRATEGY_RETURN_INVALID` at that bar.
- A misspelled config key (`{"spred": 0}`) fails with `CONFIG_INVALID`.
- `Config` accepts `tick_size` and `pip_size` (#5).

## Market data is checked the same way everywhere

- NaN and infinite prices are rejected; Python lists and DataFrames get the
  same OHLC checks as CSV files. A NaN volume is treated as missing.
- Timestamps must carry a timezone; epoch values must be seconds (a
  millisecond value is rejected instead of becoming the year 56971).
  Timezone-aware `datetime` and `pandas.Timestamp` values are accepted.
- `bar["timestamp"]` is documented as `YYYY-MM-DDTHH:MM:SS[.f…]+00:00`, and
  the new `bar["timestamp_ms"]` (epoch milliseconds) is the safe key for
  joining external data (#8).

## Fast long runs

- `history` is now a read-only, list-like view costing O(1) per bar (#6).
  100,000 one-minute bars take about 2 seconds instead of about 3 hours.

## Upgrading from 0.1.x

| If your code … | Change |
| --- | --- |
| reads annualised metrics from intraday runs | pass `bars_per_year` (e.g. `252 * 96` for 15-minute bars of a 24h market) |
| expects `annualised_return_pct`, `avg_win`, … to always be numbers | handle `null` and read `metrics["unavailable"][key]` |
| counted zero-P&L trades as wins | use `breakeven_trades` |
| uses `stop_loss` / `take_profit` / `quantity` / `qty` in a signal | use `sl` / `tp` / `size` |
| returns `None` or a bare signal dict from `on_bar` | return `[]` / `[signal]` |
| returns `{"drawings": [...]}` only | `{"signals": [], "drawings": [...]}` |
| mutates `history` or checks `isinstance(history, list)` | use `list(history)` |
| passes timezone-less timestamps or epoch milliseconds | add `Z`/an offset; divide by 1000 |
| passes extra keys in a config dict | remove or fix them |
| feeds every numeric bar field into a model | exclude the new `timestamp_ms` |

`metrics.json` is now schema 2; runs saved by 0.1.x keep schema 1 and still
open in replay, `inspect_run`, `run_summary` and the MCP server.

## Verification

- 290 Rust tests and 15 Python suites, including property-based trust checks,
  no-lookahead perturbation, byte-identical determinism, independent
  Finance/QA golden ledgers, and metric fixtures recomputed independently from
  the canonical artifacts plus a hand-computed run.
- Independent code and Finance/QA reviews: `docs/audit/`, `harness/finance/`.
- Full audit: `docs/audit/2026-10-trust-audit.md`.

## Package

- Wheel: `observa-0.2.0-cp310-abi3-manylinux_2_34_x86_64.whl`
- SHA-256: `71dbeba77469041ec5fe4c371b9418525ef0a8b73f31a5a55c8ee6466dc8fac7`
- Linux x86_64, manylinux_2_34, CPython abi3 for Python 3.10+

Install from the wheel attached to this release. Do not install the unrelated
PyPI project named `observa`.
