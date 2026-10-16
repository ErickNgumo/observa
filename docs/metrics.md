# Strategy metrics (schema 2)

Observa derives metrics from the canonical run after it completes. Metrics are
**never** a financial authority: they read the canonical end-of-bar
snapshots, closed positions and fills, and nothing feeds back into execution.
The Rust implementation is `crates/observa-metrics/src/evaluation.rs`; the
same object is returned by `RunResult.metrics`, written to `metrics.json`,
shown in replay and summarised by `observa.run_summary()`.

## Conventions

* `S` — starting balance (`Config.starting_balance`).
* `E_t` — end-of-bar equity for bars `t = 0 … n−1`: balance plus unrealised
  P&L of open positions, marked at the bar **close** (no exit costs). `E_−1 = S`.
* `r_t = E_t / E_{t−1} − 1` — per-bar return (`n` returns; the first is
  measured from the starting balance). Returns are defined only while equity
  stays strictly positive.
* `B` — bars per year (the annualisation factor), see below.
* A trade is a **closed position**; its P&L is realised P&L **net of
  commission**. Positions still open at the end are not trades (their
  unrealised P&L is reported separately and is included in final equity).
* Money values are in the account currency (`assumptions.currency`).
* A metric that is undefined is `null` in the report and its reason is given
  in `unavailable[metric]`. Nothing undefined is reported as `0`.

## Annualisation

Annualised metrics (`annualised_return_pct`, `annualised_volatility_pct`,
`sharpe_ratio`, `sortino_ratio`, `calmar_ratio`) need `B`:

1. If you pass `bars_per_year` (`observa.run(..., bars_per_year=…)` or
   `Config(bars_per_year=…)`), it is used. It must be a number between 1 (one
   bar a year) and 31,622,400 (one bar a second); giving two different values
   is an error. If the data contain more than twice or less than half that
   many bars per calendar year (over a span of at least four weeks), a warning
   says so.
2. Otherwise **daily** bars get a default only when the median bar spacing is
   0.75–1.5 days, and then from the calendar actually observed (over a span of
   at least four weeks): about 200–290 bars per calendar year → **252**
   (trading days); about 330–380 → **365** (every calendar day, e.g. crypto);
   anything else → unavailable. Spans shorter than four weeks use 252.
   **Weekly** bars get **52** when the median spacing is 5–9 days. Hourly bars
   left with the default `interval="1d"` are never annualised as if daily.
   Accepted interval spellings: `Nm`, `Nh`, `1d`/`d`/`day`, `1w`/`w`/`week`
   (case-insensitive).
3. Intraday intervals have **no default**: bars per year depends on the
   market's trading hours. Annualised metrics are then unavailable, with the
   reason.

Examples: 15-minute FX bars traded 24h on 252 days → `252 × 96 = 24192`;
hourly crypto bars 24/7 → `365 × 24 = 8760`; daily crypto bars → `365`.

The factor, its source (`explicit` / `interval_default`) and an explanation
are recorded in `assumptions`.

## Definitions

### Returns

| Key | Definition | Unavailable when |
|---|---|---|
| `net_profit` | `E_{n−1} − S` | — |
| `total_return_pct` | `(E_{n−1}/S − 1) × 100` (not annualised) | — |
| `annualised_return_pct` | CAGR: `((E_{n−1}/S)^(1/years) − 1) × 100`, `years = n/B` | no `B`; `years < 1` (periods shorter than a year are not annualised — GIPS convention); `E_{n−1} ≤ 0` |
| `unrealised_pnl_end` | `final_equity − final_balance` | — |

### Risk

| Key | Definition | Unavailable when |
|---|---|---|
| `annualised_volatility_pct` | sample std. dev. of `r_t` (n−1 denominator) `× √B × 100` | no `B`; fewer than 30 returns; any `E_t ≤ 0` |
| `sharpe_ratio` | `mean(r) / std(r) × √B`, risk-free rate 0 | as above; `std(r) = 0` |
| `sortino_ratio` | `mean(r) / DD × √B`, `DD = √(Σ min(r_t,0)² / n)` (target 0) | as above; no negative return |
| `max_drawdown_pct` | `max_t (P_t − E_t)/P_t × 100`, running peak `P_t = max(S, E_0…E_t)` | — (0 when equity never fell below a peak) |
| `max_drawdown_amount` | `P − E` at that drawdown, in currency | — |
| `max_drawdown_start` / `_end` | timestamps of the peak (the last bar at that peak level; the first bar when the peak is the starting balance) and of the trough | `null` when there is no drawdown |
| `max_drawdown_recovered_at` | first bar after the trough with `E_t ≥` that peak | `null` = not recovered |
| `longest_drawdown_bars` | longest run of consecutive bars with `E_t < P_t` | — |
| `current_drawdown_pct` | `(P_{n−1} − E_{n−1})/P_{n−1} × 100` | — |
| `calmar_ratio` | `annualised_return_pct / max_drawdown_pct` over the whole sample (strictly the MAR ratio; classic Calmar uses the last 36 months) | annualised return unavailable; no drawdown |

Drawdowns can exceed 100 % when equity goes negative: Observa does not model
margin calls or liquidation (see `known-limitations.md`).

### Trades (closed positions)

| Key | Definition | Unavailable when |
|---|---|---|
| `total_trades`, `winning_trades`, `losing_trades`, `breakeven_trades` | counts with net P&L `> ε`, `< −ε`, otherwise break-even (`ε = 1e-9`, float noise) | — |
| `win_rate_pct` | `winning / total × 100` | no trades |
| `avg_win` / `avg_loss` | mean net P&L of winners / mean absolute net P&L of losers | no winners / no losers |
| `payoff_ratio` | `avg_win / avg_loss` | either side missing |
| `profit_factor` | gross profit / gross loss | no trades; no losing trade (unbounded) |
| `expectancy` | mean net P&L per trade | no trades |
| `largest_win` / `largest_loss` | best / worst single trade (loss as a positive amount) | none |
| `max_consecutive_losses` | longest run of losing trades in closing order (a break-even trade ends a run) | — |
| `avg_holding_bars` | mean of `exit bar − entry bar` | no trades |

### Exposure

| Key | Definition | Unavailable when |
|---|---|---|
| `time_in_market_pct` | share of bars ending with ≥ 1 open position | — |
| `max_gross_leverage` | `max_t used_margin_t × leverage / E_t` = gross position value / equity at the bar close | no position open at any bar close; equity ≤ 0 while positions were open (leverage unbounded) |

### Costs (account currency)

| Key | Definition |
|---|---|
| `commission_cost` | commissions booked by the configured model (end of run) |
| `spread_cost` | `Σ spread_applied × units` over all fills, including SL/TP exits (half the configured spread per side for market-style fills) |
| `slippage_cost` | `Σ slippage_applied × units` over all fills |
| `total_costs` | sum of the three |
| `total_costs_pct_of_starting_balance` | `total_costs / S × 100` |

Costs cover what the configured cost model charges. **Financing / swap /
funding is not modelled**, so positions held overnight have no carry cost
(`assumptions.cost_scope` says so).

### Warnings

`warnings` is a list of plain-language caveats shown next to the numbers:
annualised ratios extrapolated from less than one year of data (stated in
calendar days or hours), an explicit `bars_per_year` that disagrees with the
data by more than 2x, equity having
fallen to or below zero (no margin call modelled), or annualisation being
unavailable and why.

### Sample and assumptions

`sample` records `bars`, `return_periods`, `closed_trades`, the first/last
timestamp, `calendar_days` and `years` (when `B` is known). `assumptions`
records the starting balance, currency, interval, `bars_per_year` and its
source, the annualisation note, the risk-free rate (0), the return basis and
the minimum sample rules (30 returns; one year for annualised returns).

## Where the factor is recorded

`bars_per_year`, its source and the explanation live in `metrics.json`
(`assumptions`), which `inspect_run(dir).metrics`, `run_summary(dir)` and the
MCP server expose. It is deliberately **not** part of `run.json`: `run.json`
records what produced the canonical economics, and the annualisation factor
does not affect them. The development-only Rust CLI (`observa-cli`, not
shipped) has no `bars_per_year` option yet, so its intraday runs report
annualised metrics as unavailable.

## Precision

`metrics.json` keeps full double precision so values can be re-derived and
compared exactly; replay displays two decimals (percentages, ratios, money)
and states sample sizes next to the figures. Ratios from short samples are
noisy — read them with the `sample` block.

## Changes from schema 1 (Observa ≤ 0.1.6)

* Annualised figures used `bars_per_year = 252` whatever the interval, and a
  run shorter than 0.05 "years" reported its total return as "annualised".
  Schema 2 never guesses an intraday factor and does not annualise returns
  over less than one year.
* Total return and drawdowns are measured from the starting balance (schema 1
  used the first end-of-bar snapshot).
* A zero-P&L trade is break-even (schema 1 counted it as a win).
* Undefined values are `null` with a reason (schema 1 reported e.g. `avg_win`
  as `0.0` when there were no wins).
* New: `net_profit`, `annualised_volatility_pct`, `sortino_ratio`, `warnings`,
  `max_drawdown_amount`, `max_drawdown_recovered_at`, `longest_drawdown_bars`,
  `breakeven_trades`, `payoff_ratio`, `max_consecutive_losses`,
  `avg_holding_bars`, `time_in_market_pct`, `max_gross_leverage`, the cost
  breakdown, `unrealised_pnl_end`, `sample`, `assumptions`, `unavailable`.

Older runs keep their schema-1 `metrics.json`; they still open in replay,
`inspect_run` and the MCP server, and replay labels their annualised figures
as legacy.
