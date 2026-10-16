# Metrics schema 2 — pre-run expectations (Finance/QA)

Written 2026-10-16 from `docs/metrics.md` and the documented/verified execution
model (`harness/finance/golden_ledgers.py`, llms-full.txt §I), **before** running
any scenario and **before** reading `crates/observa-metrics/src/evaluation.rs`
or `persistence.rs::derive_metrics_json`.

Tolerances fixed now: money and prices abs 1e-6 **or** relative 1e-9
(whichever is looser); ratios/percentages relative 1e-9 (abs 1e-12 near 0);
counts exact; `null` must be `null` and must have a reason in `unavailable`.

## Execution model used (documented / previously verified)

* Instrument for S1–S7: `contract_size=100`, `starting_balance=10000`,
  `leverage=100`, daily bars, `fill_mode=NEXT_BAR_OPEN`. 1 lot = 100 units.
* Market buy = next open + spread/2 + slippage; sell = open − spread/2 − slippage.
  `spread_applied` = spread/2, `slippage_applied` = slippage on such fills.
* SL exit (no gap) is market-style: SL − spread/2 − slippage for a long.
  TP exit is exactly the TP level (spread_applied = slippage_applied = 0).
* PER_SIDE: `commission` charged on each fill, from balance at the fill.
  ROUND_TRIP: `commission` charged once, on the closing fill.
* Equity marked at bar close (mid). `used_margin = units × close / leverage`,
  so `used_margin × leverage / E = units × close / E`.
* `E_-1 = S`; drawdown peak includes S. Bars indexed from 0.

---------------------------------------------------------------------------

## S1 — profitable multi-trade, PER_SIDE commission 2, spread 0.2, slip 0.1

| bar | O | H | L | C | action |
|---|---|---|---|---|---|
| 0 | 100 | 101 | 99 | 100 | signal buy 1 |
| 1 | 100 | 102 | 99.5 | 101 | buy fill 100+0.1+0.1 = 100.2, comm 2 |
| 2 | 101 | 103 | 100.5 | 102 | signal close |
| 3 | 102 | 102.5 | 101 | 101.5 | sell fill 102−0.2 = 101.8; signal sell 1 |
| 4 | 101.5 | 102 | 100 | 100.5 | short fill 101.5−0.2 = 101.3 |
| 5 | 100.5 | 101 | 99 | 101 | signal close |
| 6 | 101 | 101.5 | 100.5 | 101.2 | buy-to-close 101+0.2 = 101.2; signal buy 1 |
| 7 | 101.2 | 101.4 | 100 | 100.2 | buy fill 101.4; signal close |
| 8 | 101 | 101.2 | 100.5 | 100.9 | sell fill 101−0.2 = 100.8 |
| 9 | 100.9 | 101 | 100.8 | 100.9 | flat |

Ledger (balance B, equity E):
* b0 E=10000. b1 B=9998, E=9998+(101−100.2)·100 = **10078**. b2 E=9998+180 = **10178**.
* b3 T1 gross (101.8−100.2)·100 = 160, B=9998+160−2 = **10156** = E.
* b4 B=10154, E=10154+(101.3−100.5)·100 = **10234**. b5 E=10154+30 = **10184**.
* b6 T2 gross (101.3−101.2)·100 = 10, B=10154+10−2 = **10162** = E.
* b7 B=10160, E=10160+(100.2−101.4)·100 = **10040**.
* b8 T3 gross (100.8−101.4)·100 = −60, B=10160−60−2 = **10098** = E; b9 10098.

Trades net: T1 160−4 = **156** (hold 3−1=2), T2 10−4 = **6** (6−4=2), T3 −60−4 = **−64** (8−7=1).

| metric | expected |
|---|---|
| net_profit | 98 |
| total_return_pct | 0.98 |
| annualised_return_pct | null (years = 10/252 < 1) |
| annualised_volatility_pct, sharpe, sortino | null (< 30 returns) |
| max_drawdown_pct | peak 10234 (b4), trough 10040 (b7): 194/10234·100 = 1.8956419777213211 |
| max_drawdown_amount | 194 |
| max_drawdown_start / end | ts(b4) / ts(b7) |
| max_drawdown_recovered_at | null |
| longest_drawdown_bars | b3 (1), b5..b9 (5) → 5 |
| current_drawdown_pct | 136/10234·100 = 1.3289036544850499 |
| calmar_ratio | null |
| total/win/loss/breakeven | 3 / 2 / 1 / 0 |
| win_rate_pct | 66.666666666666667 |
| avg_win / avg_loss | (156+6)/2 = 81 / 64 |
| payoff_ratio | 81/64 = 1.265625 |
| profit_factor | 162/64 = 2.53125 |
| expectancy | 98/3 = 32.666666666666667 |
| largest_win / largest_loss | 156 / 64 |
| max_consecutive_losses | 1 |
| avg_holding_bars | 5/3 = 1.6666666666666667 |
| time_in_market_pct | open at close of b1,b2,b4,b5,b7 → 5/10 = 50 |
| max_gross_leverage | b1: 100·101/10078 = 1.002182972812066 (b2 1.00216, b4 0.98202, b5 0.99175, b7 0.99801) |
| commission_cost | 6 fills × 2 = 12 |
| spread_cost | 6 × 0.1 × 100 = 60 |
| slippage_cost | 6 × 0.1 × 100 = 60 |
| total_costs / pct | 132 / 1.32 |
| unrealised_pnl_end | 0 |
| sample.bars / return_periods / closed_trades | 10 / 10 / 3 |
| assumptions.bars_per_year / source | 252 / interval_default (calendar-daily spacing = 1 d) |

## S1b — same as S1, ROUND_TRIP commission 2 (booked once, on close)

E: 10000, 10080, 10180, 10158, 10238, 10188, 10166, 10046, 10104, 10104.
Trades net 158, 8, −62.

| metric | expected |
|---|---|
| net_profit / total_return_pct | 104 / 1.04 |
| max_drawdown_pct / amount | (10238−10046)/10238·100 = 1.8753662824770465 / 192 |
| current_drawdown_pct | 134/10238·100 = 1.3088493846454385 |
| longest_drawdown_bars | 5 |
| avg_win / avg_loss / payoff | 83 / 62 / 1.3387096774193548 |
| profit_factor | 166/62 = 2.6774193548387097 |
| expectancy | 104/3 = 34.666666666666667 |
| largest_win / largest_loss | 158 / 62 |
| max_gross_leverage | 10100/10080 = 1.001984126984127 |
| commission_cost | **6** (3 round trips × 2). Note: golden_ledgers G3b found `order_filled.commission_amount` reports the round-trip amount on BOTH fills; summing fills would give 12 — that would be a defect. |
| spread / slippage / total / pct | 60 / 60 / 126 / 1.26 |

## S2 — losing run that never recovers, open position at end; spread 0.2, no slip, no comm

| bar | O | H | L | C | action |
|---|---|---|---|---|---|
| 0 | 100 | 100 | 99 | 99.5 | signal buy 1 |
| 1 | 99.5 | 99.8 | 98 | 98.5 | fill 99.6 |
| 2 | 98.5 | 99 | 97 | 97.5 | signal close |
| 3 | 97.5 | 98 | 96 | 97 | close 97.4 (gross −220); signal buy 2 |
| 4 | 97 | 97.5 | 95 | 96 | fill 97.1 (200 units) |
| 5 | 96 | 97 | 95.5 | 96.5 | end, still open |

E: 10000, 9890, 9790, 9780, 9780+(96−97.1)·200 = 9560, 9780−120 = 9660. Final balance 9780.

| metric | expected |
|---|---|
| net_profit / total_return_pct | −340 / −3.4 |
| unrealised_pnl_end | 9660 − 9780 = −120 |
| max_drawdown_pct / amount | 440/10000 = 4.4 / 440 |
| max_drawdown_start / end | ts(b0) (peak = S, first bar) / ts(b4) |
| recovered_at | null |
| longest_drawdown_bars | 5 |
| current_drawdown_pct | 3.4 |
| trades total/win/loss/be | 1/0/1/0 |
| win_rate_pct | 0 |
| avg_win, payoff, largest_win | null (no winners) |
| avg_loss / largest_loss | 220 / 220 |
| profit_factor | 0/220 = **0** (defined: there are trades and a loser) |
| expectancy | −220 |
| max_consecutive_losses | 1 |
| avg_holding_bars | 2 |
| time_in_market_pct | b1,b2,b4,b5 → 4/6 = 66.666666666666667 |
| max_gross_leverage | b4: 200·96/9560 = 2.00836820083682 |
| spread_cost | 0.1·100 + 0.1·100 + 0.1·200 = 40; slippage 0; commission 0; total 40; pct 0.4 |
| sample.closed_trades | 1 (the open position is not a trade) |

## S3 — equity to zero and below; 10 lots (1000 units), zero costs

| bar | O | H | L | C | E |
|---|---|---|---|---|---|
| 0 | 100 | 100 | 100 | 100 | 10000 (signal buy 10) |
| 1 | 100 | 100 | 95 | 95 | fill 100; 10000−5000 = 5000 |
| 2 | 95 | 95 | 90 | 90 | **0** |
| 3 | 90 | 90 | 88 | 88 | **−2000** |
| 4 | 88 | 92 | 88 | 92 | 2000 (signal close) |
| 5 | 92 | 92 | 92 | 92 | close fill 92: gross −8000; E=B=2000 |

| metric | expected |
|---|---|
| net_profit / total_return_pct | −8000 / −80 |
| annualised_* / sharpe / sortino / calmar | null (years < 1; equity ≤ 0) |
| max_drawdown_pct / amount | 12000/10000 = **120** / 12000 (spec: can exceed 100 %) |
| max_drawdown_start / end | ts(b0) / ts(b3) |
| longest_drawdown_bars | 5; current_drawdown_pct 80 |
| trades | 1 loser −8000, PF 0, avg_holding_bars 4 |
| time_in_market_pct | 4/6 = 66.666666666666667 |
| max_gross_leverage | **AMBIGUITY**: spec formula divides by E_t, which is 0 at b2 and negative at b3. Acceptable: `null` with reason, or the max over E_t > 0 bars = b4 92·1000/2000 = **46** (b1 19). **Not acceptable**: inf, NaN, a negative number, or silently ignoring bars without saying so. |

## S4 — only winners; PER_SIDE commission 1, no spread/slip

| bar | O | H | L | C | action |
|---|---|---|---|---|---|
| 0 | 100 | 100 | 100 | 100 | signal buy 1 |
| 1 | 100 | 101 | 100 | 101 | fill 100; B 9999; E 10099; signal close |
| 2 | 102 | 102 | 101 | 101 | close 102: gross 200; B=E=10198; signal buy 1 |
| 3 | 101 | 103 | 101 | 103 | fill 101; B 10197; E 10397; signal close |
| 4 | 103 | 104 | 103 | 104 | close 103: gross 200; B=E=10396 |

| metric | expected |
|---|---|
| net_profit | 396; total_return_pct 3.96 |
| trades | 2 / 2 / 0 / 0; win_rate 100 |
| avg_win 198; avg_loss null; payoff null | |
| profit_factor | **null** (no losing trade, unbounded) with reason |
| expectancy 198; largest_win 198; largest_loss null; max_consecutive_losses 0 | |
| avg_holding_bars | 1 |
| max_drawdown_pct / amount | 1/10397·100 = 0.009618159084351255 / 1 (exit commission at b4) |
| max_drawdown_start/end | ts(b3) / ts(b4); recovered null; longest 1 |
| time_in_market_pct | 2/5 = 40 |
| max_gross_leverage | 10100/10099 = 1.0000990197049213 |
| commission 4; spread 0; slippage 0; total 4; pct 0.04 | |

## S5 — no trades: 40 flat daily bars (price 100), strategy returns []

| metric | expected |
|---|---|
| net_profit, total_return_pct | 0, 0 |
| annualised_return_pct | null (years 40/252 < 1) |
| annualised_volatility_pct | **0** (B = 252 default, 40 ≥ 30 returns, all r = 0; spec lists no other condition) |
| sharpe_ratio | null (std = 0) |
| sortino_ratio | null (no negative return) |
| max_drawdown_pct 0, amount 0; start/end/recovered null; longest 0; current 0; calmar null | |
| total_trades 0; win/loss/be 0; max_consecutive_losses 0 | |
| win_rate, avg_win, avg_loss, payoff, profit_factor, expectancy, largest_win, largest_loss, avg_holding_bars | all null with reasons |
| time_in_market_pct | 0 |
| max_gross_leverage | null (no position at any close) |
| costs | all 0 |

## S6 — hedged long + short simultaneously; spread 0.2, slip 0.1, no comm

| bar | O | H | L | C | action |
|---|---|---|---|---|---|
| 0 | 100 | 100 | 100 | 100 | signal buy 1 and sell 1 |
| 1 | 100 | 101 | 99 | 100.5 | long 100.2, short 99.8 |
| 2 | 101 | 102 | 100.5 | 102 | signal close long (by ticket) |
| 3 | 102 | 103 | 101 | 102.5 | long closed 101.8 (+160); signal close short |
| 4 | 102 | 102 | 101 | 101 | short closed 102.2 (−240) |
| 5 | 101 | 101 | 101 | 101 | flat |

E: 10000; b1 10000+30−70 = 9960; b2 10000+180−220 = 9960; b3 10160−270 = 9890; b4 9920; b5 9920.

| metric | expected |
|---|---|
| net_profit −80; total_return_pct −0.8 | |
| max_drawdown_pct / amount | 1.1 / 110 ; start ts(b0), end ts(b3); longest 5; current 0.8 |
| trades | 2/1/1/0; win_rate 50; avg_win 160; avg_loss 240; payoff 0.6666666666666666; PF 0.6666666666666666; expectancy −40; largest 160/240; max_consec_losses 1 |
| avg_holding_bars | (2 + 3)/2 = 2.5 |
| time_in_market_pct | 3/6 = 50 |
| max_gross_leverage | b2: both legs gross 2·100·102/9960 = 2.0481927710843375 (gross, not net — a hedged book has zero net exposure) |
| spread 40; slippage 40; commission 0; total 80; pct 0.8 | |

## S7 — SL and TP exits with costs; PER_SIDE commission 1, spread 0.2, slip 0.1

| bar | O | H | L | C | action |
|---|---|---|---|---|---|
| 0 | 100 | 100.5 | 99.5 | 100 | signal buy 1, sl 98, tp 105 |
| 1 | 100 | 100.5 | 99 | 99.5 | fill 100.2; B 9999; E 9929 |
| 2 | 99.5 | 99.6 | 97.5 | 98 | SL exit 98−0.1−0.1 = 97.8: gross −240; B=E=9758; signal buy 1 sl 95 tp 100 |
| 3 | 98 | 99 | 97.8 | 99 | fill 98.2; B 9757; E 9837 |
| 4 | 99 | 101 | 98.9 | 100.5 | TP exit at 100.0 exactly: gross 180; B=E=9936 |
| 5 | 100.5 | 100.6 | 100.4 | 100.5 | flat |

| metric | expected |
|---|---|
| net_profit −64; total_return_pct −0.64 | |
| trades | −242 (SL), +178 (TP): 2/1/1/0; win_rate 50; avg_win 178; avg_loss 242; payoff = PF = 0.7355371900826446; expectancy −32; largest 178/242; max_consec_losses 1; avg_holding_bars 1 |
| max_drawdown_pct / amount | 2.42 / 242; start ts(b0), end ts(b2); longest 5; current 0.64 |
| time_in_market_pct | 2/6 = 33.333333333333333 |
| max_gross_leverage | b3: 9900/9837 = 1.0064043915827996 |
| commission_cost | 4 |
| spread_cost | entry 10 + SL exit 10 + entry 10 + TP 0 = **30** |
| slippage_cost | 10 + 10 + 10 + 0 = **30** |
| total 64; pct 0.64 | |

---------------------------------------------------------------------------

## Ratio scenarios (computed with `metrics_reference.py`, written from the spec)

All: contract_size 100, 1 lot, zero spread/slippage/commission, signal buy at
b0, filled at b1 open = C_0, held to the end (never closed → 0 trades,
`unrealised_pnl_end = net_profit`). Bars generated by `metrics_reference.py`
(`open_t = close_{t−1}`, high/low = max/min ± 0.5).

### S8 — business-daily, 504 bars, interval "1d", no bars_per_year → B = 252 (interval_default), years = 2.0

| metric | expected |
|---|---|
| net_profit | 1262.29 |
| total_return_pct | 12.6229 |
| annualised_return_pct | 6.123936979363909 |
| annualised_volatility_pct | 2.1244979861303266 |
| sharpe_ratio | 2.808646400836062 |
| sortino_ratio | 4.643899793253352 |
| max_drawdown_pct / amount | 4.915921156637306 / 508.73 |
| dd start / end / recovered | ts(b25) / ts(b69) / ts(b102) |
| longest_drawdown_bars | 77 |
| current_drawdown_pct | 0.25462667743625195 |
| calmar_ratio | 1.2457353940869418 |
| sample.return_periods / years | 504 / 2.0 |

### S8x — same bars, `bars_per_year=260` explicit → source explicit, years 1.9384615384615385

annualised_return 6.324371586545907; vol 2.157956705693031; sharpe 2.852879774032872;
sortino 4.717036572800403; calmar 1.28650793717612. Non-annualised values as S8.

### S9 — annualisation resolution

| id | bars | interval | bars_per_year | expected B / source | expected annualised metrics |
|---|---|---|---|---|---|
| S9a | 40 hourly | "1h" | none | null (no intraday default) | return/vol/sharpe/sortino/calmar null with reason |
| S9b | 40 hourly | "1h" | 8760 | 8760 / explicit | vol 26.02001613999323, sharpe 19.98790586485932, sortino 32.53245386481848; annualised return null (years 0.004566 < 1); calmar null; mdd 3.758359938518263 |
| S9c | 40 hourly | "1d" (default) | none | null (spacing 1 h disagrees with 1 d) | all annualised null |
| S9c2 | 40 hourly | "1d" | 8760 | 8760 / explicit | as S9b |
| S9d | 60 weekly | "1w" (string assumed; spec does not list accepted spellings) | none | 52 / interval_default; years 1.1538461538461537 | annualised return −0.8279351924782796, vol 1.0374234461506189, sharpe −0.7962270654387915, sortino −1.0990824139264952, mdd 4.291296810589239, calmar −0.19293356507880322 |
| S9e | 40 weekly-spaced | "1d" | none | null (spacing 7 d vs 1 d, factor > 2) | all annualised null |
| S9f | — | — | 0, −1, NaN, +inf | run raises an error | — |
| S9g | 40 daily | "1d" | Config 252 + run 260 | error (two different values) | — |
| S9h | 40 daily | "1d" | Config 252 + run 252 | accepted, explicit | — |
| S9i | 40 calendar-daily | "1d" | none | 252 / interval_default; vol/sharpe defined; annualised return null (<1y) | values from reference on the engine's own equity |

Also checked for every scenario: `metrics.json` (persisted) equals `RunResult.metrics`;
every `null` metric has an `unavailable` entry; no `NaN`/`inf` anywhere.

### Cross-check on engine snapshots (secondary)

In addition to the hand model, the golden script recomputes the Returns/Risk
metrics with `metrics_reference.risk_metrics` from the persisted
`portfolio_snapshot` equities in `events.jsonl`. This isolates metric
arithmetic from execution if a hand ledger disagrees.

## Known ambiguities recorded before running

1. **A1** `max_gross_leverage` when `E_t ≤ 0` (S3) — formula undefined.
2. **A2** return periods / ratios once equity hits 0 (S3): r after a zero equity is undefined; spec only says ratios are unavailable.
3. **A3** accepted spellings for weekly interval ("1w"?) are not documented.
4. **A4** "within a factor of two" — inclusive or exclusive at exactly 2× not stated (not asserted).
5. **A5** drawdown start when the peak is the starting balance: spec says "the first bar" — used ts(b0).
6. **A6** calendar-daily data (7 days/week, e.g. crypto) has median spacing 1 d, so the spec applies 252 although the true factor is ~365 (spec-compliant, but a finance concern).
