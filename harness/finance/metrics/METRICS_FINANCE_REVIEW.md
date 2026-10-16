# Metrics schema 2 — independent Finance/QA review

Reviewer: Finance/QA (independent of the implementer) · 2026-10-16 · branch `trust-audit-2026-10`
Scope: `docs/metrics.md` (schema 2, release 0.2.0), `crates/observa-metrics/src/evaluation.rs`,
`crates/observa-engine/src/persistence.rs::derive_metrics_json`.
Wheels: fixed = `scratchpad/venv-dev` (reports 0.1.6, schema 2); released = `scratchpad/venv-rel313` (0.1.6, schema 1).

## Verdict: **APPROVE WITH CHANGES**

The implementation matches the specification exactly in every scenario I pre-registered.
There were **0 discrepancies** across 564 checks. The change is **metrics-only**: canonical
`events.jsonl` and `run.json` are byte-identical to 0.1.6 for 55 valid runs, and the execution
golden ledgers still pass 616/616. The definitions are defensible and mostly conventional for
this accounting model. None of the requested changes is an arithmetic defect. They concern one
misleading edge case (leverage once equity is ≤ 0), annualisation sanity checks that are too weak,
and missing disclosures (financing costs, provenance of `bars_per_year`). Items C1–C3 below should
be addressed or explicitly accepted before 0.2.0 ships.

## Method and provenance

1. I wrote `metrics_expectations_prerun.md` (sha256 `e973a6da…6b6d`) by hand from the spec and the
   previously verified execution model, **before** running anything or reading the implementation.
   `metrics_reference.py` (sha256 `000ef655…73f4`) is an independent implementation of the spec's
   Returns/Risk formulas. It was used for the ≥30-return scenarios, with the equity derived from my
   own price model, not from the engine.
2. Tolerances were fixed before running: money abs 1e-6 (or rel 1e-9); ratios/percentages rel 1e-9
   (abs 1e-12); counts exact; `null` must be `null` *and* carry an `unavailable` reason.
3. `metrics_golden.py` runs every scenario through `observa.run(..., output=…)`. It compares
   `RunResult.metrics` against the pre-registered values. It also checks that the persisted
   `metrics.json` equals the in-memory result, that every `null` has a reason, that no defined
   metric has a stray reason, and that there are no NaN/inf values. Finally it recomputes the
   risk metrics from the engine's own `portfolio_snapshot` equities with the reference code.
4. Discrimination check: I injected 5 wrong expectations (money, null-vs-0, 0-vs-null, a
   timestamp, and a 2e-9 relative error). All 5 failed and the script exited 1.
5. Only after the first full run did I read the implementation. I then wrote `metrics_probes.py`
   (post-run, informational, not pre-registered) for paths the scenarios did not exercise.

The only pre-run → run change was a harness bug in my comparator (`math.isfinite` on a list). It
was fixed before any value was compared. No expected value was changed after running.

## Results summary

| Check | Result |
|---|---|
| `metrics_golden.py` (fixed wheel) | **564 PASS, 0 FAIL**, 39 INFO, exit 0 |
| Mutation test of the harness | 5/5 injected errors detected, exit 1 |
| `metrics_cross_wheel.py` (14 metrics scenarios, 0.1.6 vs fixed) | events.jsonl byte-identical 14/14; run.json identical 14/14 (no keys changed, added or removed); exit 0 |
| `cross_build_compare.py` (41 battery cases, 0.1.6 vs fixed) | 219 PASS / 41 FAIL. **All 41 failures are "metrics.json identical"**, which is the expected schema change. events.jsonl 41/41, run.json 41/41, strategy observations 4/4, signals 4/4, input-format equivalence 14/14 |
| `harness/finance/golden_ledgers.py` (fixed wheel) | **616 passed, 0 failed** |
| `metrics_probes.py` (post-run) | informational; findings F2–F6 below |

### Scenario coverage (all PASS; full tables in Appendix A)

| ID | What it covers | Key expected = actual |
|---|---|---|
| S1 | profitable, 3 trades (long/short/long), PER_SIDE commission 2 | net 98; MDD 1.8956 % (194); PF 2.53125; costs 12/60/60; leverage 1.00218 |
| S1b | same, ROUND_TRIP 2 | commission_cost **6**, not 12, so the G3b double-reported `commission_amount` on fills is correctly *not* summed; PF 166/62 |
| S2 | losing, never recovers, open position at end | net −340; unrealised −120; PF **0** (defined); avg_win/largest_win null; DD start = first bar (peak = S) |
| S3 | equity to 0 and −2000 | MDD **120 %** (12 000); return ratios null ("equity fell to or below zero…"); leverage → see C1 |
| S4 | only winners | PF **null** ("unbounded"); payoff null; max_consecutive_losses 0; MDD 1/10397 from exit commission |
| S5 | no trades, 40 flat bars | all trade stats null with reasons; vol **0**; Sharpe null (std 0); Sortino null; leverage null; DD timestamps null |
| S6 | hedged long + short | gross leverage 2.0482 (both legs); holding 2.5; costs 40/40 |
| S7 | SL exit + TP exit with costs | spread/slippage on the SL exit counted, 0 on the TP exit: 30/30; net −64 |
| S8 / S8x | 504 business-daily bars, default 252 / explicit 260 | CAGR 6.1239 % / 6.3244 %; Sharpe 2.8086 / 2.8529; Sortino 4.6439; Calmar 1.2457; recovery date |
| S9a–e,i | intraday no bpy; 1h + 8760; hourly labelled "1d"; weekly "1w"; weekly-spaced labelled "1d"; 40 calendar-daily | B resolution and reasons as specified; <1 year → no CAGR; ratios defined at ≥30 returns |
| S9f–h | bpy 0/−1/NaN/inf (run and Config), conflicting values, same value twice | 8/8 raise `ValueError`; conflict raises; same value accepted (source explicit) |

## Discrepancies and their classification

No asserted value disagreed. The pre-registered ambiguities resolved as follows:

| # | Item | Observed | Classification |
|---|---|---|---|
| A1 | `max_gross_leverage` when E_t ≤ 0 (S3) | **46.0**, no reason/note. Bars with E ≤ 0 are silently skipped (`filter(|b| b.equity > 0.0 …)`) | **Spec defect** (behaviour undocumented) → C1 |
| A2 | `sample.return_periods` once equity ≤ 0 | 6 (= n) although the returns are undefined; the ratio reasons explain it | Ambiguity, cosmetic |
| A3 | weekly spelling | "1w", "1W", "W" → 52; "1wk", "weekly" → `ValueError: unknown interval` | Spec/doc gap (accepted spellings not listed) |
| A4 | "within a factor of two" boundary | inclusive. Bars exactly 2 days apart with "1d" → B = 252 | Ambiguity; also a weakness → C2 |
| A5 | DD start when the peak is S | first bar, as expected | Matches spec |
| A6 | 7-day/week daily data (crypto, some FX feeds) | B = 252 (median spacing 1 d); the note says "pass bars_per_year=365 for a 24/7 market" | Spec-compliant; finance weakness → C2 |
| — | my errors | none in values; one comparator bug fixed before comparison | — |

## Post-run probe findings (`metrics_probes.py`)

* **F1** Break-even classification uses exact float comparisons (`> 0.0`, `< 0.0`). Executed prices
  are rounded to `price_decimals`, so an economically flat EURUSD round trip nets exactly `0.0` and
  is counted as break-even (P1). I did not demonstrate float-noise misclassification with
  `commission_rate_per_unit`. Low risk; a tolerance (e.g. |pnl| < 0.5 × 10^-currency_decimals)
  would make it robust.
* **F2** An explicit `bars_per_year` is recorded in `metrics.json → assumptions` but **not in
  `run.json`**, and `inspect_run` does not surface it (P2). `run.json` is documented as "what
  produced the run", so re-deriving metrics from `run.json` + `events.jsonl` loses it. → C4
* **F3** A break-even trade **resets** `max_consecutive_losses` (loss, BE, loss → 1) (P3). This is
  defensible but the spec only says "longest run of losing trades". Document it.
* **F4** On an equity plateau at the peak, `max_drawdown_start` is the **last** bar at the peak
  level, not the first (P4), because the code uses `e >= peak`. That is a reasonable "drawdown
  begins when equity leaves the peak" convention, but it should be documented.
* **F5** Partial closes are rejected by the engine ("close quantity mismatch"), so "trade =
  closed position" is unambiguous today. If partial closes are added, trade statistics will need
  a rule.
* **F6** A legacy 0.1.6 (schema-1) run directory still opens with `inspect_run` on the new wheel.
  `result.summary()` returns raw doubles (e.g. `max_gross_leverage 1.0000000000000002`,
  `max_drawdown_amount 508.72999999999956`).

## Finance assessment

### (a) Are the definitions defensible for this accounting model?

| Choice | Assessment |
|---|---|
| Mark-to-market at bar close, mid, no exit costs | Defensible and disclosed (`return_basis`, known-limitations). It is optimistic relative to liquidation value by about half the spread + slippage (+ the ROUND_TRIP commission still owed) on open positions. MetaTrader marks longs at Bid, so its equity already includes the spread. Close-only marking also **understates intrabar drawdown**. Acceptable with the existing disclosure; consider adding "close-to-close" to the drawdown help text. |
| Returns from the starting balance (E_−1 = S) | Correct. This fixes a real schema-1 defect where first-bar costs and P&L were excluded. |
| Trade = closed position, net of commission | Conventional (MT4/MT5 "deal" statistics are per closed position net of commission). Open positions are correctly excluded and reported via `unrealised_pnl_end`. Note that a buy-and-hold run shows 0 trades with a +12.6 % return (S8). That is labelled, but readers should be pointed at `unrealised_pnl_end`. |
| Sample std (n−1), arithmetic mean, rf = 0, √B scaling | Conventional for backtest reports. rf = 0 is stated in `assumptions`. |
| Sortino: downside deviation over all n periods, target 0 | Conventional (Sortino–Price style, n in the denominator rather than only the count of negatives). Correct choice. |
| Calmar = CAGR / max DD over the full sample | Defensible, but strictly this is the **MAR ratio**. The original Calmar uses a trailing 36 months. Suggest a one-line note in the help text. Negative Calmar for negative CAGR (S9d −0.193) is fine. |
| No annualisation under 1 year (GIPS) | Correct and important. It removes schema 1's "annualised" figures from short runs. |
| 252/52 defaults only when spacing agrees; no intraday default | Right principle. The check is too permissive (C2). |
| `max_gross_leverage = used_margin × leverage / E` at the close | Equal to Σ\|units\| × close / equity, i.e. gross notional / equity. Correct **given** the documented restriction account currency = quote currency (verified in known-limitations). The hedged case correctly reports gross, not net. The E ≤ 0 handling is misleading (C1). |
| `spread_cost = Σ spread_applied × units` | Correct accounting of what the engine charged: half the spread per market-style side, including SL exits, and 0 on TP and limit fills (S7). Note that under the engine's model a TP fill pays no spread at all. `spread_cost` faithfully reports that, but readers should not take it as the broker-realistic spread bill. (This is an execution-model property and out of scope here.) |

### (b) Misleading, redundant or missing items, and precision

* **Misleading:** `max_gross_leverage` after equity hits zero (C1). Weak annualisation sanity
  (C2): with the 2× band, daily-labelled data with half the days missing (or 2-day bars) gets
  B = 252. Then `years = n/B` is half the true elapsed time, CAGR is grossly overstated, and
  volatility is misscaled by √2. 7-day calendar-daily data likewise gets 252 instead of 365. The
  spec's own S8 run shows the gap: `years = 2.0` against `calendar_days = 705` (1.93 yr).
* **Precision:** `metrics.json` at full double precision is right for re-derivation. Replay shows
  2 decimals plus sample-size chips, which is good. However, `result.summary()`/`run_summary`
  return raw doubles that agents tend to quote verbatim (F6). More importantly, the 30-return
  minimum lets a 40-bar hourly run show **Sharpe 19.99 / Sortino 32.53** (S9b). That is
  arithmetically correct but economically meaningless. Recommend showing a standard error
  (Lo 2002: SE(SR) ≈ √((1 + ½·SR_p²)/n) · √B) or flagging ratios computed from under one year
  of data.
* **Redundant:** `total_costs_pct_of_starting_balance` adds little. Costs as % of gross profit,
  or cost per trade, is more decision-relevant for FX/CFD.
* **Missing for FX/CFD evaluation:**
  1. **Financing/swap costs** are neither modelled nor listed in `known-limitations.md`, yet
     `total_costs` reads as complete. For multi-day FX/CFD holds this is often the largest cost.
     → C3
  2. **Minimum margin level** (equity / used_margin) and a "**would have been stopped out**"
     flag (e.g. margin level < 50 %, a common broker stop-out). Without margin calls, S3 shows
     a −120 % drawdown that a real account could not reach; this flag would make that explicit.
  3. Long/short breakdown, average/time-weighted gross leverage (the max alone is spiky),
     trades per year, MAE/MFE, and recovery factor (net profit / max DD amount), as in
     MT4/MT5 reports.

### (c) Execution/accounting invariance

Verified, not assumed: 55 valid runs (14 metrics scenarios + 41 battery cases covering
BAR_CLOSE/NEXT_BAR_OPEN × PER_SIDE/ROUND_TRIP, SL/TP, hedging, open-at-end, negative equity, and
several input formats) produce **byte-identical `events.jsonl` and identical `run.json`** on 0.1.6
and the fixed wheel. Strategy observations and signals are identical. `golden_ledgers.py` passes
616/616 on the fixed wheel. `derive_metrics_json` only reads `result.events/bars/trades/fills`
and `final_state`; nothing it computes is fed back.

## Recommendations

| ID | Priority | Recommendation | Class |
|---|---|---|---|
| C1 | Should fix before 0.2.0 | `max_gross_leverage`: when any bar with open positions has E ≤ 0, report `null` with reason "equity fell to or below zero at <ts>; leverage unbounded", or keep the positive-equity max and add the reason/flag. Never silently drop bars. Document it in the spec. | spec defect |
| C2 | Should fix | Tighten the interval-default check (e.g. daily accepted if median spacing is within 0.75–1.5 d) **and** reconcile `n/B` with `calendar_days/365.25`. If they differ by more than ~15 %, either refuse the default or add a prominent note (this catches 2-day bars, sparse data and 7-day-week data). | spec weakness |
| C3 | Should fix (docs) | State in `known-limitations.md`, `docs/metrics.md` (Costs) and the `total_costs` help that overnight financing/swap is not modelled and excluded from costs and P&L. | missing disclosure |
| C4 | Nice to have | Record an explicit `bars_per_year` in `run.json` (as run provenance) and surface it in `inspect_run`/MCP. | provenance gap |
| C5 | Nice to have | Document: accepted interval spellings; the inclusive 2× boundary; break-even resets the loss streak; DD start = last bar at the peak; Calmar here is full-sample (MAR). | doc |
| C6 | Nice to have | Round in `summary()`/`run_summary` text, or label values as unrounded; add a Sharpe standard error or a "< 1 year of data" flag next to ratios. | presentation |
| C7 | Backlog | Add min margin level / stop-out flag, long/short split, average gross leverage, cost as % of gross profit. | missing metrics |
| C8 | Low | Consider an epsilon for break-even classification (F1). | robustness |

## What was NOT verified

* The replay metrics panel rendering (`static/js/metrics.js`) beyond reading its formatting code.
  No browser was run. Nor was the legacy-run display in replay.
* The MCP server's presentation of schema-2 metrics. `inspect_run` was checked only for not
  crashing on a legacy run and for not showing an explicit bpy.
* The repo's own `python/tests/test_metrics_fixtures.py` and `metrics_panel.test.js` (pytest is
  not installed in venv-dev; not run). Rust unit tests in `evaluation.rs` were not run.
* LIMIT/STOP entries, gap-through SL, BAR_CLOSE fill mode and `commission_rate_per_unit` were
  **not** in my metrics scenarios. They are covered for execution by `golden_ledgers.py` and for
  invariance by the cross-build battery, but their metric values were not hand-checked.
* Float-noise break-even misclassification (F1) was reasoned about from the code, not
  demonstrated.
* Non-UTC/DST timestamp effects on median spacing; datasets with < 3 bars (spacing check
  disabled, so the default is accepted); very large runs (performance).
* Multi-currency accounts (unsupported by the engine).

## Files

* `harness/finance/metrics/metrics_expectations_prerun.md` — pre-registered expectations (hand arithmetic)
* `harness/finance/metrics/metrics_reference.py` — spec-only reference implementation + bar generators
* `harness/finance/metrics/metrics_golden.py` — runnable comparison (exit 1 on failure)
* `harness/finance/metrics/metrics_cross_wheel.py` — 0.1.6 vs fixed invariance for the metrics scenarios
* `harness/finance/metrics/metrics_probes.py` — post-run edge probes (informational)

Reproduce:
```
PY=<scratchpad>/venv-dev/bin/python; REL=<scratchpad>/venv-rel313/bin/python
$PY  harness/finance/metrics/metrics_golden.py
$REL harness/finance/metrics/metrics_cross_wheel.py run OUT_REL
$PY  harness/finance/metrics/metrics_cross_wheel.py run OUT_FIX
python3 harness/finance/metrics/metrics_cross_wheel.py compare OUT_REL OUT_FIX
$PY  harness/finance/golden_ledgers.py
```

## Appendix A — expected vs actual (generated from the run's `results.json`)

Values printed to 10 significant figures. Comparisons used the full-precision values and the
tolerances above. Rows not listed here (generic checks, snapshot cross-checks, `sample.*`) also
passed; see the per-scenario counts.

**S1_profit_per_side** — 50 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 98 | 98 | PASS |
| total_return_pct | 0.98 | 0.98 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | null | null | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 1.895641978 | 1.895641978 | PASS |
| max_drawdown_amount | 194 | 194 | PASS |
| max_drawdown_start | 2024-01-05 | 2024-01-05 | PASS |
| max_drawdown_end | 2024-01-08 | 2024-01-08 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 1.328903654 | 1.328903654 | PASS |
| total_trades | 3 | 3 | PASS |
| winning_trades | 2 | 2 | PASS |
| losing_trades | 1 | 1 | PASS |
| win_rate_pct | 66.66666667 | 66.66666667 | PASS |
| avg_win | 81 | 81 | PASS |
| avg_loss | 64 | 64 | PASS |
| payoff_ratio | 1.265625 | 1.265625 | PASS |
| profit_factor | 2.53125 | 2.53125 | PASS |
| expectancy | 32.66666667 | 32.66666667 | PASS |
| largest_win | 156 | 156 | PASS |
| largest_loss | 64 | 64 | PASS |
| max_consecutive_losses | 1 | 1 | PASS |
| avg_holding_bars | 1.666666667 | 1.666666667 | PASS |
| time_in_market_pct | 50 | 50 | PASS |
| max_gross_leverage | 1.002182973 | 1.002182973 | PASS |
| commission_cost | 12 | 12 | PASS |
| spread_cost | 60 | 60 | PASS |
| slippage_cost | 60 | 60 | PASS |
| total_costs | 132 | 132 | PASS |
| unrealised_pnl_end | 0 | 0 | PASS |
| assumptions.bars_per_year | 252 | 252 | PASS |
| assumptions.bars_per_year_source | interval_default | interval_default | PASS |

**S1b_profit_round_trip** — 30 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 104 | 104 | PASS |
| total_return_pct | 1.04 | 1.04 | PASS |
| max_drawdown_pct | 1.875366282 | 1.875366282 | PASS |
| max_drawdown_amount | 192 | 192 | PASS |
| max_drawdown_start | 2024-01-05 | 2024-01-05 | PASS |
| max_drawdown_end | 2024-01-08 | 2024-01-08 | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 1.308849385 | 1.308849385 | PASS |
| avg_win | 83 | 83 | PASS |
| avg_loss | 62 | 62 | PASS |
| payoff_ratio | 1.338709677 | 1.338709677 | PASS |
| profit_factor | 2.677419355 | 2.677419355 | PASS |
| expectancy | 34.66666667 | 34.66666667 | PASS |
| largest_win | 158 | 158 | PASS |
| largest_loss | 62 | 62 | PASS |
| max_gross_leverage | 1.001984127 | 1.001984127 | PASS |
| commission_cost | 6 | 6 | PASS |
| spread_cost | 60 | 60 | PASS |
| slippage_cost | 60 | 60 | PASS |
| total_costs | 126 | 126 | PASS |

**S2_losing_open_at_end** — 44 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | -340 | -340 | PASS |
| total_return_pct | -3.4 | -3.4 | PASS |
| max_drawdown_pct | 4.4 | 4.4 | PASS |
| max_drawdown_amount | 440 | 440 | PASS |
| max_drawdown_start | 2024-01-01 | 2024-01-01 | PASS |
| max_drawdown_end | 2024-01-05 | 2024-01-05 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 3.4 | 3.4 | PASS |
| total_trades | 1 | 1 | PASS |
| winning_trades | 0 | 0 | PASS |
| losing_trades | 1 | 1 | PASS |
| win_rate_pct | 0 | 0 | PASS |
| avg_win | null | null | PASS |
| avg_loss | 220 | 220 | PASS |
| payoff_ratio | null | null | PASS |
| profit_factor | 0 | -0 | PASS |
| expectancy | -220 | -220 | PASS |
| largest_win | null | null | PASS |
| largest_loss | 220 | 220 | PASS |
| max_consecutive_losses | 1 | 1 | PASS |
| avg_holding_bars | 2 | 2 | PASS |
| time_in_market_pct | 66.66666667 | 66.66666667 | PASS |
| max_gross_leverage | 2.008368201 | 2.008368201 | PASS |
| commission_cost | 0 | 0 | PASS |
| spread_cost | 40 | 40 | PASS |
| slippage_cost | 0 | 0 | PASS |
| total_costs | 40 | 40 | PASS |
| unrealised_pnl_end | -120 | -120 | PASS |

**S3_equity_below_zero** — 25 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | -8000 | -8000 | PASS |
| total_return_pct | -80 | -80 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | null | null | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 120 | 120 | PASS |
| max_drawdown_amount | 12000 | 12000 | PASS |
| max_drawdown_start | 2024-01-01 | 2024-01-01 | PASS |
| max_drawdown_end | 2024-01-04 | 2024-01-04 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 80 | 80 | PASS |
| total_trades | 1 | 1 | PASS |
| losing_trades | 1 | 1 | PASS |
| avg_loss | 8000 | 8000 | PASS |
| profit_factor | 0 | -0 | PASS |
| avg_holding_bars | 4 | 4 | PASS |
| time_in_market_pct | 66.66666667 | 66.66666667 | PASS |

**S4_only_winners** — 38 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 396 | 396 | PASS |
| total_return_pct | 3.96 | 3.96 | PASS |
| max_drawdown_pct | 0.009618159084 | 0.009618159084 | PASS |
| max_drawdown_amount | 1 | 1 | PASS |
| max_drawdown_start | 2024-01-04 | 2024-01-04 | PASS |
| max_drawdown_end | 2024-01-05 | 2024-01-05 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 1 | 1 | PASS |
| total_trades | 2 | 2 | PASS |
| winning_trades | 2 | 2 | PASS |
| losing_trades | 0 | 0 | PASS |
| win_rate_pct | 100 | 100 | PASS |
| avg_win | 198 | 198 | PASS |
| avg_loss | null | null | PASS |
| payoff_ratio | null | null | PASS |
| profit_factor | null | null | PASS |
| expectancy | 198 | 198 | PASS |
| largest_win | 198 | 198 | PASS |
| largest_loss | null | null | PASS |
| max_consecutive_losses | 0 | 0 | PASS |
| avg_holding_bars | 1 | 1 | PASS |
| time_in_market_pct | 40 | 40 | PASS |
| max_gross_leverage | 1.00009902 | 1.00009902 | PASS |
| commission_cost | 4 | 4 | PASS |
| spread_cost | 0 | 0 | PASS |
| slippage_cost | 0 | 0 | PASS |
| total_costs | 4 | 4 | PASS |

**S5_no_trades** — 46 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 0 | 0 | PASS |
| total_return_pct | 0 | 0 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | 0 | 0 | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 0 | 0 | PASS |
| max_drawdown_amount | 0 | 0 | PASS |
| max_drawdown_start | null | null | PASS |
| max_drawdown_end | null | null | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 0 | 0 | PASS |
| current_drawdown_pct | 0 | 0 | PASS |
| total_trades | 0 | 0 | PASS |
| winning_trades | 0 | 0 | PASS |
| losing_trades | 0 | 0 | PASS |
| win_rate_pct | null | null | PASS |
| avg_win | null | null | PASS |
| avg_loss | null | null | PASS |
| payoff_ratio | null | null | PASS |
| profit_factor | null | null | PASS |
| expectancy | null | null | PASS |
| largest_win | null | null | PASS |
| largest_loss | null | null | PASS |
| max_consecutive_losses | 0 | 0 | PASS |
| avg_holding_bars | null | null | PASS |
| time_in_market_pct | 0 | 0 | PASS |
| max_gross_leverage | null | null | PASS |
| commission_cost | 0 | 0 | PASS |
| spread_cost | 0 | -0 | PASS |
| slippage_cost | 0 | -0 | PASS |
| total_costs | 0 | 0 | PASS |

**S6_hedged** — 37 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | -80 | -80 | PASS |
| total_return_pct | -0.8 | -0.8 | PASS |
| max_drawdown_pct | 1.1 | 1.1 | PASS |
| max_drawdown_amount | 110 | 110 | PASS |
| max_drawdown_start | 2024-01-01 | 2024-01-01 | PASS |
| max_drawdown_end | 2024-01-04 | 2024-01-04 | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 0.8 | 0.8 | PASS |
| total_trades | 2 | 2 | PASS |
| winning_trades | 1 | 1 | PASS |
| losing_trades | 1 | 1 | PASS |
| win_rate_pct | 50 | 50 | PASS |
| avg_win | 160 | 160 | PASS |
| avg_loss | 240 | 240 | PASS |
| payoff_ratio | 0.6666666667 | 0.6666666667 | PASS |
| profit_factor | 0.6666666667 | 0.6666666667 | PASS |
| expectancy | -40 | -40 | PASS |
| largest_win | 160 | 160 | PASS |
| largest_loss | 240 | 240 | PASS |
| max_consecutive_losses | 1 | 1 | PASS |
| avg_holding_bars | 2.5 | 2.5 | PASS |
| time_in_market_pct | 50 | 50 | PASS |
| max_gross_leverage | 2.048192771 | 2.048192771 | PASS |
| commission_cost | 0 | 0 | PASS |
| spread_cost | 40 | 40 | PASS |
| slippage_cost | 40 | 40 | PASS |
| total_costs | 80 | 80 | PASS |

**S7_sl_tp_costs** — 37 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | -64 | -64 | PASS |
| total_return_pct | -0.64 | -0.64 | PASS |
| max_drawdown_pct | 2.42 | 2.42 | PASS |
| max_drawdown_amount | 242 | 242 | PASS |
| max_drawdown_start | 2024-01-01 | 2024-01-01 | PASS |
| max_drawdown_end | 2024-01-03 | 2024-01-03 | PASS |
| longest_drawdown_bars | 5 | 5 | PASS |
| current_drawdown_pct | 0.64 | 0.64 | PASS |
| total_trades | 2 | 2 | PASS |
| winning_trades | 1 | 1 | PASS |
| losing_trades | 1 | 1 | PASS |
| win_rate_pct | 50 | 50 | PASS |
| avg_win | 178 | 178 | PASS |
| avg_loss | 242 | 242 | PASS |
| payoff_ratio | 0.7355371901 | 0.7355371901 | PASS |
| profit_factor | 0.7355371901 | 0.7355371901 | PASS |
| expectancy | -32 | -32 | PASS |
| largest_win | 178 | 178 | PASS |
| largest_loss | 242 | 242 | PASS |
| max_consecutive_losses | 1 | 1 | PASS |
| avg_holding_bars | 1 | 1 | PASS |
| time_in_market_pct | 33.33333333 | 33.33333333 | PASS |
| max_gross_leverage | 1.006404392 | 1.006404392 | PASS |
| commission_cost | 4 | 4 | PASS |
| spread_cost | 30 | 30 | PASS |
| slippage_cost | 30 | 30 | PASS |
| total_costs | 64 | 64 | PASS |

**S8_daily_2y** — 30 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 1262.29 | 1262.29 | PASS |
| total_return_pct | 12.6229 | 12.6229 | PASS |
| annualised_return_pct | 6.123936979 | 6.123936979 | PASS |
| annualised_volatility_pct | 2.124497986 | 2.124497986 | PASS |
| sharpe_ratio | 2.808646401 | 2.808646401 | PASS |
| sortino_ratio | 4.643899793 | 4.643899793 | PASS |
| calmar_ratio | 1.245735394 | 1.245735394 | PASS |
| max_drawdown_pct | 4.915921157 | 4.915921157 | PASS |
| max_drawdown_amount | 508.73 | 508.73 | PASS |
| max_drawdown_start | 2020-02-05 | 2020-02-05 | PASS |
| max_drawdown_end | 2020-04-07 | 2020-04-07 | PASS |
| max_drawdown_recovered_at | 2020-05-22 | 2020-05-22 | PASS |
| longest_drawdown_bars | 77 | 77 | PASS |
| current_drawdown_pct | 0.2546266774 | 0.2546266774 | PASS |
| total_trades | 0 | 0 | PASS |
| unrealised_pnl_end | 1262.29 | 1262.29 | PASS |
| assumptions.bars_per_year | 252 | 252 | PASS |
| assumptions.bars_per_year_source | interval_default | interval_default | PASS |
| sample.years | 2 | 2 | PASS |

**S8x_daily_2y_explicit260** — 28 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 1262.29 | 1262.29 | PASS |
| total_return_pct | 12.6229 | 12.6229 | PASS |
| annualised_return_pct | 6.324371587 | 6.324371587 | PASS |
| annualised_volatility_pct | 2.157956706 | 2.157956706 | PASS |
| sharpe_ratio | 2.852879774 | 2.852879774 | PASS |
| sortino_ratio | 4.717036573 | 4.717036573 | PASS |
| calmar_ratio | 1.286507937 | 1.286507937 | PASS |
| max_drawdown_pct | 4.915921157 | 4.915921157 | PASS |
| max_drawdown_amount | 508.73 | 508.73 | PASS |
| max_drawdown_start | 2020-02-05 | 2020-02-05 | PASS |
| max_drawdown_end | 2020-04-07 | 2020-04-07 | PASS |
| max_drawdown_recovered_at | 2020-05-22 | 2020-05-22 | PASS |
| longest_drawdown_bars | 77 | 77 | PASS |
| current_drawdown_pct | 0.2546266774 | 0.2546266774 | PASS |
| assumptions.bars_per_year | 260 | 260 | PASS |
| assumptions.bars_per_year_source | explicit | explicit | PASS |
| sample.years | 1.938461538 | 1.938461538 | PASS |

**S9a_hourly_no_bpy** — 26 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 238.71 | 238.71 | PASS |
| total_return_pct | 2.3871 | 2.3871 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | null | null | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 3.758359939 | 3.758359939 | PASS |
| max_drawdown_amount | 383.65 | 383.65 | PASS |
| max_drawdown_start | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_end | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_recovered_at | 2020-01-02 | 2020-01-02 | PASS |
| longest_drawdown_bars | 28 | 28 | PASS |
| current_drawdown_pct | 0 | 0 | PASS |
| assumptions.bars_per_year | null | null | PASS |

**S9b_hourly_bpy8760** — 28 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 238.71 | 238.71 | PASS |
| total_return_pct | 2.3871 | 2.3871 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | 26.02001614 | 26.02001614 | PASS |
| sharpe_ratio | 19.98790586 | 19.98790586 | PASS |
| sortino_ratio | 32.53245386 | 32.53245386 | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 3.758359939 | 3.758359939 | PASS |
| max_drawdown_amount | 383.65 | 383.65 | PASS |
| max_drawdown_start | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_end | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_recovered_at | 2020-01-02 | 2020-01-02 | PASS |
| longest_drawdown_bars | 28 | 28 | PASS |
| current_drawdown_pct | 0 | 0 | PASS |
| assumptions.bars_per_year | 8760 | 8760 | PASS |
| assumptions.bars_per_year_source | explicit | explicit | PASS |
| sample.years | 0.004566210046 | 0.004566210046 | PASS |

**S9c_hourly_interval_1d** — 26 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 238.71 | 238.71 | PASS |
| total_return_pct | 2.3871 | 2.3871 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | null | null | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 3.758359939 | 3.758359939 | PASS |
| max_drawdown_amount | 383.65 | 383.65 | PASS |
| max_drawdown_start | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_end | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_recovered_at | 2020-01-02 | 2020-01-02 | PASS |
| longest_drawdown_bars | 28 | 28 | PASS |
| current_drawdown_pct | 0 | 0 | PASS |
| assumptions.bars_per_year | null | null | PASS |

**S9c2_hourly_interval_1d_bpy** — 27 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 238.71 | 238.71 | PASS |
| total_return_pct | 2.3871 | 2.3871 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | 26.02001614 | 26.02001614 | PASS |
| sharpe_ratio | 19.98790586 | 19.98790586 | PASS |
| sortino_ratio | 32.53245386 | 32.53245386 | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 3.758359939 | 3.758359939 | PASS |
| max_drawdown_amount | 383.65 | 383.65 | PASS |
| max_drawdown_start | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_end | 2020-01-01 | 2020-01-01 | PASS |
| max_drawdown_recovered_at | 2020-01-02 | 2020-01-02 | PASS |
| longest_drawdown_bars | 28 | 28 | PASS |
| current_drawdown_pct | 0 | 0 | PASS |
| assumptions.bars_per_year_source | explicit | explicit | PASS |
| sample.years | 0.004566210046 | 0.004566210046 | PASS |

**S9d_weekly_1w** — 28 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | -95.47 | -95.47 | PASS |
| total_return_pct | -0.9547 | -0.9547 | PASS |
| annualised_return_pct | -0.8279351925 | -0.8279351925 | PASS |
| annualised_volatility_pct | 1.037423446 | 1.037423446 | PASS |
| sharpe_ratio | -0.7962270654 | -0.7962270654 | PASS |
| sortino_ratio | -1.099082414 | -1.099082414 | PASS |
| calmar_ratio | -0.1929335651 | -0.1929335651 | PASS |
| max_drawdown_pct | 4.291296811 | 4.291296811 | PASS |
| max_drawdown_amount | 444.09 | 444.09 | PASS |
| max_drawdown_start | 2020-06-24 | 2020-06-24 | PASS |
| max_drawdown_end | 2021-02-17 | 2021-02-17 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 34 | 34 | PASS |
| current_drawdown_pct | 4.291296811 | 4.291296811 | PASS |
| assumptions.bars_per_year | 52 | 52 | PASS |
| assumptions.bars_per_year_source | interval_default | interval_default | PASS |
| sample.years | 1.153846154 | 1.153846154 | PASS |

**S9e_weekly_spaced_interval_1d** — 26 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 232.65 | 232.65 | PASS |
| total_return_pct | 2.3265 | 2.3265 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | null | null | PASS |
| sharpe_ratio | null | null | PASS |
| sortino_ratio | null | null | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 1.120632509 | 1.120632509 | PASS |
| max_drawdown_amount | 115.97 | 115.97 | PASS |
| max_drawdown_start | 2020-06-24 | 2020-06-24 | PASS |
| max_drawdown_end | 2020-09-30 | 2020-09-30 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 14 | 14 | PASS |
| current_drawdown_pct | 1.120632509 | 1.120632509 | PASS |
| assumptions.bars_per_year | null | null | PASS |

**S9i_calendar_daily_40** — 28 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| net_profit | 232.65 | 232.65 | PASS |
| total_return_pct | 2.3265 | 2.3265 | PASS |
| annualised_return_pct | null | null | PASS |
| annualised_volatility_pct | 1.917507161 | 1.917507161 | PASS |
| sharpe_ratio | 7.567708326 | 7.567708326 | PASS |
| sortino_ratio | 16.89180305 | 16.89180305 | PASS |
| calmar_ratio | null | null | PASS |
| max_drawdown_pct | 1.120632509 | 1.120632509 | PASS |
| max_drawdown_amount | 115.97 | 115.97 | PASS |
| max_drawdown_start | 2020-01-26 | 2020-01-26 | PASS |
| max_drawdown_end | 2020-02-09 | 2020-02-09 | PASS |
| max_drawdown_recovered_at | null | null | PASS |
| longest_drawdown_bars | 14 | 14 | PASS |
| current_drawdown_pct | 1.120632509 | 1.120632509 | PASS |
| assumptions.bars_per_year | 252 | 252 | PASS |
| assumptions.bars_per_year_source | interval_default | interval_default | PASS |
| sample.years | 0.1587301587 | 0.1587301587 | PASS |

**S9h_same_bpy_twice** — 1 checks passed, 0 failed (all checks incl. generic + snapshot cross-checks)

| metric | expected | actual | |
|---|---|---|---|
| assumptions.bars_per_year_source | explicit | explicit | PASS |


---

# Re-review of fixes (2026-10-16, rebuilt fixed wheel in `scratchpad/venv-dev`)

## Updated verdict: **APPROVE** (residual items are low priority and non-blocking)

C1, C2, C3, C5, C6 and C8 are implemented as described and verified by running them. I accept
C4 as declined: the rationale holds and I verified that the factor is exposed. C7 remains
backlog. Execution and accounting are still unchanged against 0.1.6. Four low-priority residual
items are listed below; none blocks 0.2.0.

## Results on the rebuilt wheel

| Check | Result |
|---|---|
| Original `metrics_golden.py`, before my harness update | 559 PASS / **5 FAIL**, all in `S9i_calendar_daily_40` (B 365 instead of 252, plus the 4 values that depend on it) |
| `metrics_golden.py` after the update (pre-registered scenarios + new `FIX-*` checks) | **624 PASS / 0 FAIL**, 40 INFO, exit 0 |
| `metrics_cross_wheel.py` (14 scenarios, 0.1.6 vs rebuilt) | events.jsonl byte-identical 14/14; run.json identical 14/14; compare failures 0 |
| `cross_build_compare.py` (41 battery cases) | 219 PASS / 41 FAIL — **all 41 failures are "metrics.json identical"** (the intended schema change); events.jsonl, run.json, strategy observations and signals: 164/164 PASS; input-format equivalence 14/14 |
| `harness/finance/golden_ledgers.py` | **616 passed, 0 failed** |

### Harness change (S9i) and why

The pre-run expectation for S9i (40 consecutive calendar days, interval "1d") was B = 252. That
was correct under the original spec, and I had flagged it as weakness A6. The revised
`docs/metrics.md` derives the daily default from observed calendar density over spans of at
least 28 days. 40 calendar days (a 39-day span) is about 365 bars per calendar year, so B = 365.
I changed the expectation to 365 and recomputed the values with the **unchanged** spec-only
`metrics_reference.py`. They are: vol 2.3077202249491338, Sharpe 9.107738380282917, Sortino
20.329288119014404, years 0.1095890410958904. The engine matched all of them. This is a spec
change, not an implementation defect or my error. The change is commented in
`metrics_golden.py`. No other pre-registered expectation was altered.

The new `FIX-*` checks were written after reading the coordinator's change list and the revised
spec, so they are not pre-registered in the original sense. Their expected values come from the
spec text and hand arithmetic (S3b, C8), or from the reference implementation (calendar400).

## Per-finding status

| ID | Finding | Status | Evidence |
|---|---|---|---|
| A1/C1 | `max_gross_leverage` silently skipped E ≤ 0 bars | **Fixed, verified** | S3 → `null`, reason "equity fell to or below zero while positions were open, so leverage was unbounded (margin calls are not modelled)", plus the warning "Equity fell to or below zero; no margin call is modelled…". New S3b (equity goes negative only *after* a gap-through close, while flat) → leverage **46** = 92 000/2 000 (correctly still defined), Sharpe null, warning present. |
| A4/A6/C2 | Annualisation sanity too loose | **Fixed, verified** | 40 calendar days → 365; S5 → 365; 10 bars and 20 calendar days (span < 28 d) → 252; Mon–Fri 60 → 252; **Mon–Sat 60 (~313/yr) → unavailable**; 2-day spacing → unavailable (was 252); weekly 10-day spacing → unavailable; 5-day spacing with "1w" → 52; 400 calendar days → B 365, years 1.0959, CAGR/vol/Sharpe/Sortino/Calmar equal to the reference, no warnings. Explicit bounds: 1 and 31 622 400 accepted; 0.999 and 31 622 401 rejected; 0/−1/NaN/inf/conflict rejected. |
| C3 | Financing/swap not disclosed | **Fixed, verified** | `assumptions.cost_scope` = "commission, spread and slippage as charged by the configured cost model; financing / swap / funding is not modelled"; `known-limitations.md` and the `docs/metrics.md` Costs section updated. |
| C4 | `bars_per_year` not in run.json | **Declined; rationale accepted** | Verified that `inspect_run(dir).metrics.assumptions` and `run_summary(dir)` expose `bars_per_year = 8760, source explicit`. run.json records what produced the economics, and B does not affect them; byte-identical run.json against 0.1.6 is a benefit. Residual: the factor survives only as long as `metrics.json` is kept with the run. |
| A3/C5 | Undocumented conventions | **Fixed (docs), verified where testable** | Spellings `1d/d/day/1D`, `1w/w/week` accepted, as documented; "1wk"/"weekly" rejected, which is consistent with the documented list. Break-even ends a loss run, DD start = last bar at the peak, and Calmar = full-sample MAR are all now in the spec; behaviour matches (probes P3/P4). |
| C6 | Presentation / short-sample ratios | **Partly fixed** | `warnings` verified on 9 ratio scenarios: none for S8/S8x/S9d (≥ 1 year); "Not annualised: …" for S9a/S9c/S9e; "…highly uncertain" for S9b/S9c2/S9i; none on the 7 short hand scenarios except S3. Replay renders `warningsNotice` (code read, **not browser-verified**). Not addressed: no Sharpe standard error, and `summary()`/`run_summary` still return unrounded doubles. Acceptable, because replay rounds and `metrics.json` must stay full-precision. |
| C7 | Missing FX/CFD metrics | Backlog (agreed) | — |
| F1/C8 | Break-even exact-float comparison | **Fixed, verified with a real noise case** | 1 unit, 100.1 → 100.3, flat commission 0.1/side: the engine's `net_realized_pnl` = **2.858824288409778e-15**, which is non-zero, so the tolerance really was exercised. Result: breakeven 1, winning 0, avg_win null. |
| A2 | `return_periods` counted after E ≤ 0 | Unchanged (cosmetic) | Reasons and warnings explain it. |

## Residual observations (new, low priority)

* **R1 — An explicit `bars_per_year` is not reconciled with the data.** Passing 8760 on daily
  bars is accepted silently. It produced Sharpe 44.6 and the warning "…from **0.00 years** of
  data", although the data spans 39 calendar days (0.11 years). `years = n/B` inherits the user's
  error. Suggest a warning when an explicit B differs from the observed calendar density by more
  than about 2× (the density estimate already exists for C2). Classification: enhancement.
* **R2 — Doc mismatch:** `docs/metrics.md` §Annualisation still says an explicit factor "must be
  finite and > 0". The code (both layers, per the error text) and the Python docstring enforce
  1..31 622 400. Classification: spec/doc defect, trivial.
* **R3 — "0.00 years of data"** for intraday samples (40 hourly bars) under-communicates the
  sample. Suggest showing days or hours when years < 0.1. Presentation only.
* **R4 — `llms-full.txt`** (the agent guide) does not mention that financing/swap is not
  modelled. Agents writing FX/CFD strategies read that file rather than `known-limitations.md`.
  A one-line addition is recommended.

## Not verified in the re-review

* The replay warnings banner in a browser; MCP output.
* That the *Rust* layer rejects out-of-range `bars_per_year` independently of Python. I only saw
  the shared error text through the Python API. The dev-only Rust CLI was not exercised.
* The exact density formula (n vs n−1 over the span) at the 200/290/330/380 boundaries. I tested
  only points well inside each band.
* Repo tests (`test_metrics_fixtures.py`, `metrics_panel.test.js`, Rust unit tests) were not run;
  pytest is unavailable in venv-dev.
