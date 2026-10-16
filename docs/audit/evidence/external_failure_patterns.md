# External failure patterns from other backtesters (leads for Observa audit)

Collected 2026-10-16. Sources: GitHub issues read with `gh issue view` (body plus comments),
upstream source read with `gh api .../contents` (not executed), and docs fetched with WebFetch.

**Limitations**
- backtrader has GitHub issues **disabled** (`hasIssuesEnabled: false`), and community.backtrader.com
  returned HTTP 522. backtrader items therefore come from the official docs and the upstream source
  (`mementum/backtrader` master), not from user reports.
- `backtrader.readthedocs.io` turned out to be a third-party fork's docs. I used the upstream source instead.
- "Mapping" lines are hypotheses about Observa. None of them shows that Observa has the defect.
- Items tagged **[source-read]** are my reading of upstream code, with no issue confirming them.

---

## 1. Silent no-trade / ignored orders

1. **Absolute-size orders cancelled for insufficient margin with no warning (0 trades, `buy()` looks successful).**
   (b) https://github.com/kernc/backtesting.py/issues/1334 and https://github.com/kernc/backtesting.py/issues/1360
   (c) Fixed: warning added in commit 054d4539. Current source warns on both the absolute and relative paths ("Broker canceled the order due to insufficient margin").
   (d) Observa reports rejections as `order_rejected` events. Check that every engine-side drop path (margin, zero size, invalid SL/TP side, unknown ticket) emits one, and that run summaries show rejection counts prominently.
2. **Size semantics overloaded: `0 < size < 1` means "fraction of equity", so `size=0.1` meant as 0.1 BTC (or lots) rounds to 0 units and the order is silently removed.**
   (b) https://github.com/kernc/backtesting.py/issues/1198 , https://github.com/kernc/backtesting.py/issues/1329 , https://github.com/kernc/backtesting.py/issues/1186
   (c) Wontfix/design. The maintainer points to `FractionalBacktest`, which trades in 1e-8 units by default, so users must also scale size (#1329: "you should have called `self.buy(size=int(1e8))`").
   (d) Observa's `size` is a quantity (e.g. 0.1 lots). Check for any lot-step or min-size quantisation that could round a small size to 0. If one exists, it must produce a rejection event, not a no-op.
3. **Pending stop/limit orders deleted at trigger time when sizing exceeds equity; the user "spent like one hour" finding out why.**
   (b) https://github.com/kernc/backtesting.py/issues/1216
   (c) Closed after explanation. Later covered by the warnings in item 1.
   (d) Pending-order expiry or cancellation at trigger time needs the same event visibility as rejection at submit time.
4. **Order "softly rejected" on the first bar because valuation needs a previous close that does not exist.**
   (b) https://github.com/polakowo/vectorbt/issues/65 (related: https://github.com/polakowo/vectorbt/issues/667, first order "Ignored")
   (c) Explained as by design. Status only shows in order logs (`log=True`). The docs list a `raise_reject` flag (https://vectorbt.dev/api/portfolio/base/).
   (d) Bar 0 has empty `history`. Check that bar-0 / first-fill edge cases with `next_bar_open` produce either a fill or an explicit event.
5. **backtrader `checksubmit=True` (default) checks margin/cash at submit; orders move to `Margin` status and never execute. You only see this if you implement `notify_order`.**
   (b) https://github.com/mementum/backtrader/blob/master/backtrader/brokers/bbroker.py (docstring for `checksubmit`, `order.margin()` calls) **[source-read]**. Docs: https://www.backtrader.com/docu/broker/
   (c) Documented behaviour.
   (d) Observa's signal dicts silently ignore unknown keys (a typo in `sl` drops the stop). This is the same "silent no-op" family. `validate-strategy` should flag unknown keys if it does not already.

## 2. Timestamp / timezone handling

1. **TZ-offset index (`+08:00`, a TradingView export) makes the daily equity resample land on Saturday instead of Friday, which shifts daily returns and the annualised stats.**
   (b) https://github.com/kernc/backtesting.py/issues/1002
   (c) Open. The maintainer says the results are "not invalid" (it was already Saturday in UTC), suggests `tz_convert(None)`, and is open to a warning.
   (d) RFC 3339 inputs with mixed offsets: check whether Observa normalises to UTC, and which calendar day per-day metric bucketing (if any) uses.
2. **tz-aware index crashes optimisation (`Cannot interpret 'datetime64[ns, Asia/Kolkata]'`) or comparisons (`tz-naive vs tz-aware`).**
   (b) https://github.com/kernc/backtesting.py/issues/1252 , https://github.com/polakowo/vectorbt/issues/637
   (c) Workarounds only (`tz_localize(None)`). In vectorbt the bug was attributed to quantstats.
   (d) Check that mixing `Z` and `+hh:mm` timestamps in one dataset either canonicalises them or is rejected deterministically.
3. **Numeric epoch index auto-converted with `pd.to_datetime(...)` and no unit, using the heuristic "most values > 1975 epoch-seconds". Seconds vs milliseconds is not detected.**
   (b) Source: https://github.com/kernc/backtesting.py/blob/master/backtesting/backtesting.py (`Backtest.__init__`, "Numeric index with most large numbers") **[source-read]**. Listed as item 10 in https://github.com/kernc/backtesting.py/issues/1318 ("improve timestamp inference (detect seconds vs. milliseconds)").
   (c) Open (enhancement list).
   (d) If Observa accepts or derives epoch timestamps anywhere (CSV loaders, adapters), the unit must be explicit. A silent ns/ms/s mix-up yields 1970 dates or a wrong bars_per_year.
4. **Daily bars anchored to UTC midnight plus a fixed offset drift by an hour across DST, so sessions split or merge (wrong OHLC, wrong daily returns).**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/4398 . The backtrader docs warn about DST drift with hard-coded local times: https://www.backtrader.com/docu/timemgmt/
   (c) Nautilus: fixed (`time_bars_time_zone`, commit 0a8a19df). backtrader: documented (`tzinput`/`tz`).
   (d) Lower relevance unless Observa resamples. Relevant if any metric groups by "day" or "session".
5. **Duplicate or equal timestamps: duplicate `ts_event` bars accumulate in the cache; rows sharing `ts_init` reorder by CPU count; NETTING cycles with equal open/close timestamps collapse into one PnL record.**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/5083 , https://github.com/nautechsystems/nautilus_trader/issues/5253 , https://github.com/nautechsystems/nautilus_trader/issues/5288
   (c) 5083 fixed (replace on equal, skip older). 5253 closed (book-event part fixed in 2395df0e3). 5288 open.
   (d) Observa should reject or define behaviour for duplicate or non-increasing bar timestamps. backtesting.py silently *sorts* unsorted data with only a warning (source, `Backtest.__init__`), which is a pattern to avoid. Also check that any keys built from (ticket, timestamp) cannot collide.

## 3. NaN / bad OHLC data

1. **backtesting.py raises on NaN OHLC ("Some OHLC values are missing (NaN)…"), but there is no High>=max(O,C) / Low<=min(O,C) sanity check.**
   (b) Source `Backtest.__init__` **[source-read]**. The missing OHLC check is item 9 of https://github.com/kernc/backtesting.py/issues/1318
   (c) The NaN check is a fix by design. The OHLC-consistency check is an open suggestion.
   (d) Check that Observa rejects NaN/inf/negative prices and inconsistent OHLC before the loop. An inverted high/low would distort SL/TP intrabar evaluation.
2. **NaN gaps (suspended stock or misaligned calendars) poison TA-Lib indicators for the rest of the series.**
   (b) https://github.com/polakowo/vectorbt/issues/180
   (c) Answered: use NaN-aware built-ins or forward-fill. "No easy way" otherwise.
   (d) Strategy-side, so lower relevance. Still worth warning in agent docs that indicator libraries may propagate NaN into `sl`/`tp`/`size`. Check that the engine rejects NaN signal fields rather than passing them through.
3. **Per-trade stats NaN when account currency differs from instrument currency; Sortino returns a degenerate value from 1 observation while Sharpe returns NaN.**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/4205 , https://github.com/nautechsystems/nautilus_trader/issues/4915
   (c) Both closed (4915: return NaN for n<2 to match Sharpe).
   (d) Check Observa's metrics with 0 trades, 1 trade, and 1 return observation, and that every ratio uses a consistent "undefined" policy (null, never 0 and never NaN in JSON).
4. **Sharpe/Sortino/Calmar floored at 0, so negative ratios showed as 0.**
   (b) https://github.com/kernc/backtesting.py/issues/1082
   (c) Fixed (flooring removed in d47185f9).
   (d) Check that Observa never clamps metrics.

## 4. Lookahead bias

1. **Helper used `.bfill()` on a rolling ATR, which leaks future values into the warm-up period.**
   (b) https://github.com/kernc/backtesting.py/issues/963
   (c) Acknowledged by the maintainer ("introduces a brief look-ahead bias"). Still open; PR #1230 proposed.
   (d) Observa ships no indicators in the engine, but any helper or example code that backfills is the same trap. Audit examples and the gold example.
2. **Bar stamped at interval *open* but carrying completed OHLCV, so it becomes visible before it formed.**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/4577 (IB), https://github.com/nautechsystems/nautilus_trader/issues/4711 (Hyperliquid). Docs: https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/ ("ts_init must represent the close… Using the current bar's open in on_bar introduces look-ahead bias")
   (c) Both fixed. The policy is documented. Wider timestamp policy still open: https://github.com/nautechsystems/nautilus_trader/issues/4681
   (d) Observa should document whether a bar's RFC 3339 timestamp is the open or the close. With `fill_mode=bar_close`, a signal computed from bar *t* filling at close *t* is the classic "cheat-on-close".
3. **Fill at the signal bar's close is explicitly labelled cheating (`coc`).**
   (b) https://www.backtrader.com/docu/broker/ ("This is actually *cheating*, because the bar is *closed*…"). The vectorbt docs say "If you generated signals using close price, don't forget to shift your signals by one tick forward" (https://vectorbt.dev/api/portfolio/base/)
   (c) Documented, off by default in backtrader.
   (d) Directly relevant to `fill_mode=bar_close`. The run artifacts and reports should state clearly which mode was used, and the docs should say what a `bar_close` result does and does not mean.
4. **`trade_on_close=True` regression: exits filled at the next open while entries filled at the close (asymmetric).**
   (b) https://github.com/kernc/backtesting.py/issues/1218
   (c) Fixed in v0.6.2.
   (d) Add a regression test that entry, explicit close, and SL/TP exits all follow the same `fill_mode` convention.
5. **Higher-timeframe indicator on lower-timeframe bars leaks the unfinished daily bar.**
   (b) https://github.com/polakowo/vectorbt/issues/101 . Related warm-up interplay: https://github.com/kernc/backtesting.py/issues/1339
   (c) Answered with workarounds.
   (d) `history` = strictly prior bars structurally prevents this for raw data. Agent docs could warn against resampling `history` that includes partial periods.

## 5. Annualisation / Sharpe for intraday data

1. **Annualisation factor `year_freq / freq` with `year_freq='252 days'` on 15-minute *stock* data gives 24,192 bars/year, against roughly 6,552 actual session bars.**
   (b) https://github.com/polakowo/vectorbt/issues/294
   (c) Answered: the user must set `year_freq` to the true session time (e.g. '1638 hours') and drop out-of-session data.
   (d) Observa's `bars_per_year` must match the instrument's session (24x5 FX vs 24x7 crypto vs RTH equities). Check how it is defaulted or derived, and that it is persisted in run.json.
2. **Default 365-day year overstates annualised return for equities (GOOG 115% vs 59%).**
   (b) https://github.com/polakowo/vectorbt/issues/798
   (c) Answered: pass `year_freq="252d"`. Multi-asset averaging was also called out as "only for quick view".
   (d) Same as above. A silent default is the danger.
3. **Weekly/monthly data annualised as if daily.**
   (b) https://github.com/kernc/backtesting.py/issues/537
   (c) Fixed. Current `_stats.py` maps the period to 52/12/1, else 365 or 252 by weekend presence **[source-read]**.
   (d) If Observa infers `bars_per_year` from timestamps, test it on weekly and monthly data and on data with weekend gaps.
4. **backtrader Sharpe: the factor table only covers Days/Weeks/Months/Years. For Minutes the factor is `None`, so `annualize=True` silently does nothing, and the default `timeframe=Years` gives `None` on short runs.**
   (b) https://github.com/mementum/backtrader/blob/master/backtrader/analyzers/sharpe.py (`RATEFACTORS`, `factor is not None and convertrate and annualize`) **[source-read]**. Docs: https://www.backtrader.com/docu/analyzers-reference/ ("Sub-day conversions are not supported")
   (c) Documented limitation.
   (d) Observa should never fall back silently to "not annualised" without saying so in metrics.json.
5. **Daily-return resample plus timezone shifts returns across days** (see 2.1, #1002). This feeds directly into annualised volatility and Sharpe.

## 6. SL/TP intrabar ambiguity and gaps

1. **SL/TP placed with an entry did not trigger on the entry bar; when ambiguous, they are deferred to the next bar with a warning.**
   (b) https://github.com/kernc/backtesting.py/issues/119 . Current source warning: "A contingent SL/TP order would execute in the same bar its parent stop/limit order was turned into a trade… making the result… somewhat dubious" **[source-read]**
   (c) Partially fixed (market-order entries reprocess same-bar SL/TP). Ambiguous cases still deferred.
   (d) Observa must define, and test, whether a SL/TP can trigger on the fill bar under `next_bar_open` (fill at open, then H/L of the same bar is causally after it) and under `bar_close` (it should not use the same bar's H/L).
2. **When both stop and limit (or SL and TP) fall in one bar, a fixed pessimistic rule is applied.**
   (b) https://github.com/kernc/backtesting.py/issues/1224 (users argue SL-first is "pessimistic"). Source comment: "we pessimistically assume limit was hit before the stop" **[source-read]**
   (c) Closed. The rule lives in code comments.
   (d) Observa should document its SL-vs-TP same-bar rule in llms-full.txt and record which rule fired in the exit event's reason or metadata.
3. **Nautilus uses a fixed O→H→L→C path by default, or adaptive (nearer extreme first). The docs call it "a deterministic heuristic, not a reconstruction."**
   (b) https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/
   (c) Documented, configurable (`bar_adaptive_high_low_ordering`).
   (d) This is a reference design for documenting Observa's rule.
4. **Stop filled at an unreachable price after a gap (stop=160 filled at 160 although the next bar opened far above).**
   (b) https://github.com/kernc/backtesting.py/issues/1370
   (c) Fixed in PR #1369 (gap fills at the open).
   (d) Test gap-through SL/TP: a long SL gapped through should fill at the open (worse), and a TP gapped through at the open (better, or capped by policy). The behaviour must be explicit.
5. **Stop exit price: vectorbt defaults to the stop price but uses the *open* when the stop is already hit at the open; users saw "random" next-open exits. Slippage is not applied to stop orders.**
   (b) https://github.com/polakowo/vectorbt/issues/780 , https://github.com/polakowo/vectorbt/issues/539 , https://github.com/polakowo/vectorbt/issues/695
   (c) 780 explained (`stop_exit_price`). 695 open; the maintainer says "increase the stop percentage".
   (d) Check that Observa applies spread and slippage consistently to SL/TP exits, not only to market or explicit closes.

## 7. Performance cliffs

1. **Run slows from about 2,000 bars/s to about 30 bars/s on 204k bars because pending orders accumulate (per-bar loops over all orders).**
   (b) https://github.com/kernc/backtesting.py/issues/1275
   (c) User-side fix (cancel stale orders). No engine cap.
   (d) Observa passes `history` (all prior bars) to Python every bar. If that is materialised as a fresh list or dict per bar, cost is O(N²). Benchmark 100k–1M bars and check per-bar cost stays flat. Also check open-position and pending-order growth.
2. **Unbounded dedup set (funding settlements) grows for the whole run, so lookups slow down.**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/5242
   (c) Open.
   (d) Look for engine-side collections that only grow (event buffers, ticket maps) and are queried per bar.
3. **Memory: `pf.stats()` holds over 1 GB of cache; `pf.value()` on 7M×10 runs out of memory. The maintainer says vectorbt "trades memory for performance."**
   (b) https://github.com/polakowo/vectorbt/issues/704 , https://github.com/polakowo/vectorbt/issues/797
   (c) Open / answered (use `from_order_func` with a custom accumulator).
   (d) events.jsonl and per-bar equity snapshots scale with N. Check peak RSS and file size for long intraday runs.
4. **backtrader keeps every line value in memory by default. `exactbars=1` bounds memory but disables preload, runonce and plotting.**
   (b) https://www.backtrader.com/docu/memory-savings/memory-savings/ , https://www.backtrader.com/docu/cerebro/
   (c) Documented trade-off.
   (d) Same trade-off for Observa's `history`: full history is convenient for agents but costly. Consider a documented cap or a lazy view.
5. **Optimisation is slow with per-bar Python.** A user waited 15 minutes for 7.7k candles × 50 tries. The reply was "Try using Vector BT."
   (b) https://github.com/kernc/backtesting.py/issues/1011
   (c) No fix.
   (d) Per-bar Python call overhead is the floor. Measure the Rust↔Python boundary cost per bar.

## 8. Cost model surprises

1. **A per-order commission was added to the per-unit price, which is wrong for fixed or partly fixed commissions.**
   (b) https://github.com/kernc/backtesting.py/issues/1273
   (c) Fixed. Current source divides by `abs(order.size)` **[source-read]**. The maintainer notes commission is charged per side, twice per round trip.
   (d) Observa should state whether `commission` is per unit, per lot, per side, or percent of notional, and test each with sizes ≠ 1.
2. **Full spread applied on entry and none on exit: the round-trip total is right but placement is wrong, so %-based SL/TP and `pl_pct` drift with spread.**
   (b) https://github.com/kernc/backtesting.py/issues/1335
   (c) Open.
   (d) Check where Observa applies spread (half per side, or bid/ask by side), and whether SL/TP triggers are compared against bid or ask consistently for long and short.
3. **Commission baked into the fill price, so the trade appears filled above the bar's high.**
   (b) https://github.com/kernc/backtesting.py/issues/153
   (c) Explained as by design.
   (d) Keep raw fill price, spread/slippage-adjusted price and commission as separate fields in fill events. A fill outside [L, H] should only ever be explainable by a documented cost.
4. **backtrader commission interpretation flips on `margin`. With `commtype=None`, no margin means percent and stock-like; with margin it is fixed per contract. `percabs` defaults differ (`False` in CommInfoBase = "XX%", `True` in CommissionInfo), so 0.1 can mean 10% or 0.1%.**
   (b) https://github.com/mementum/backtrader/blob/master/backtrader/comminfo.py (docstring) **[source-read]**. https://www.backtrader.com/docu/commission-schemes/commission-schemes/
   (c) Documented.
   (d) Observa config should use one unambiguous unit per cost field, preferably with units named in the key or schema.
5. **Constant spread only; real (MT5) data has per-bar spread.** Separately, backtrader's `slip_match=True` silently caps slipped prices at the bar high/low.
   (b) https://github.com/kernc/backtesting.py/issues/1300 . backtrader bbroker docstring (`slip_match`, `slip_out`) **[source-read]**
   (c) 1300 open (PR #1393). backtrader documented.
   (d) If Observa caps or clamps slipped prices to the bar range, it should say so, and it should not happen silently.

## 9. Agent/LLM-related

1. **An LLM-generated enhancement list (title "CGPT5 proposed enhancements") was filed as an issue. The maintainer replied "Best to just let your agent decide."** Several items match the classes above: silent cancellations, same-bar SL/TP, OHLC sanity, epoch-unit inference.
   (b) https://github.com/kernc/backtesting.py/issues/1318
   (c) Open.
   (d) Shows the same failure classes are what agents flag. A useful checklist seed.
2. **Request for official "Agent Skills" because general-purpose agents "mix incompatible APIs, rely on stale examples." A commenter notes "a skill is a cache," so version-skew invalidation is the hard problem.**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/4600
   (c) Accepted for after v2.0.
   (d) Observa already ships `agent_spec()` and an AGENTS template. Check that the spec is generated from code, not hand-maintained, so it cannot drift.
3. **Maintainer declined an AI-assisted contributor's PR, citing AI_POLICY ("fully review, verify, and understand everything they submit").**
   (b) https://github.com/nautechsystems/nautilus_trader/issues/5054 (comment by cjdsellers)
   (c) Policy enforcement.
   (d) Process lead only, not a runtime defect.

## Bonus: determinism (directly relevant to Observa invariants)

- **Same seed and data gave different trades and PnL (about 6% spread) because the matching engine iterated `AHashMap` keys.**
  (b) https://github.com/nautechsystems/nautilus_trader/issues/3914
  (c) Fixed: switched to `IndexMap`, plus a pre-commit hook.
  (d) Observa forbids hash ordering of economics. Grep the Rust engine for `HashMap`/`HashSet` iteration on any path that affects fills, SL/TP order, or event order.
- **An empty strategy produced -98.7% PnL with zero orders.**
  (b) https://github.com/nautechsystems/nautilus_trader/issues/4055
  (c) Closed; the maintainer could not reproduce and asked for logs. **Root cause unverified.**
  (d) A cheap invariant test: zero signals must give equity equal to initial cash on every bar.
- **CASH account fill exceeding cash: order FILLED, but the balance silently debited only the affordable part.**
  (b) https://github.com/nautechsystems/nautilus_trader/issues/5047
  (c) Fixed direction agreed: surface the error and stop the backtest.
  (d) Invariant: starting balance − Σ fill costs − Σ fees = final balance. Observa's Finance/QA should assert this on every run.
