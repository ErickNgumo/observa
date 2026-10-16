# Observa Finance/QA Review: Golden Ledgers and Differential Check

Date: 2026-10-16. Verifier: independent Finance/QA agent. No engine code, docs or tests were modified. All artifacts are in `harness/finance/`.

## 0. What was tested

| Item | Value |
|---|---|
| Engine under test | Observa 0.1.6 wheel installed at `.../scratchpad/venv-head3.13` (CPython 3.13). `_observa.abi3.so` built 2026-10-16 09:18 UTC, sha256 prefix `66990a4403ddcf86` |
| Repo HEAD | `c01206f7`. `crates/observa-execution`, `observa-portfolio` and `observa-engine` have no uncommitted changes, so the code consulted equals HEAD |
| Concurrent edits | While this review ran, another process modified `crates/observa-core/src/bar.rs`, `python/src/lib.rs`, `python/python/observa/{__init__,validation,_agent/contract}.py` (timestamps from 09:59 UTC, after the wheel was built). These results apply to the wheel above. They say nothing about those later edits. |
| Golden harness | `python harness/finance/golden_ledgers.py` (exit 0 = all pass). `--keep` keeps the run directories. `GOLDEN_RUN_ROOT` chooses where they are written. |
| Differential harness | `python harness/finance/differential_backtesting_py.py --bt-python <venv-diff>/bin/python` |
| Evidence | `golden_expectations_prerun.py.txt` (sheet written before any engine run, sha256 `89abb45c…`), `golden_run1_prerun_assumptions.txt` (first-run output, 62 FAIL) |

Tolerances were fixed before any run: prices abs 1e-9, money abs 1e-6, counts and bar indices exact.

## 1. Method and provenance

1. I read the documented rules in `docs/execution-model.md`, `docs/domain/EXECUTION.md`, `docs/domain/PORTFOLIO.md`, `docs/domain/METRICS.md`, `docs/known-limitations.md`, `docs/ARCHITECTURE.md` §8, `docs/DECISIONS.md` ADR-006/007/008 and `llms-full.txt` §H/§I.
2. I wrote every scenario and expected number into `golden_ledgers.py`, tagging gap assumptions `[GAP-n]`, and hashed and copied it **before** running the engine.
3. A schema-discovery run of G1 exposed a **verifier arithmetic slip**: pip P&L was scaled by 1e4 instead of 1e5 (0.0036 × 100000 written as 36, not 360). It affected every pip-based P&L, equity and balance literal except G4 and G10. I corrected it by re-deriving each value from its formula and cross-checking with `decimal.Decimal`. I did not change any gap assumption in that correction.
4. First full run: **498 checks, 436 PASS, 62 FAIL**, kept verbatim in `golden_run1_prerun_assumptions.txt`. Every failure traces either to a `[GAP-n]` assumption or to a second verifier slip (G10 entry written as 1.2503 when 1.2500 + 0.0001 + 0.0001 = 1.2502). **No check derived purely from a documented rule failed.**
5. Only after recording the gaps did I read `crates/observa-execution/src/semantics.rs`, `crates/observa-portfolio/src/portfolio.rs` and `crates/observa-engine/src/engine.rs`. I then set the gap-dependent literals to the code's semantics and tagged each one `CODE [GAP-n]` with its pre-run value. I also added five regression scenarios (G5s, G6s, G6g, G9d, G11). Their literals are hand-derived, but they are **not independent of the code reading**.
6. Final run: **616 checks, 616 PASS, 0 FAIL**, exit 0. It was run twice, with identical totals.

## 2. Scenarios: expected vs actual (final run)

Config for all scenarios unless stated: starting_balance 10000, leverage 100, contract_size 100000, EURUSD, USD account, interval 1d. Where not listed, the costs are spread 0.0002 (half = 0.0001), slippage 0.0001, commission 0 PER_SIDE, NEXT_BAR_OPEN, 1 lot.

| Scenario | Rule exercised | Expected (hand) | Actual (engine) | Basis |
|---|---|---|---|---|
| G1 long, NEXT_BAR_OPEN | market buy/sell = ref ± half spread ± slip | buy 1.1012 @b1, sell 1.1048 @b3, gross = net 360.00, final 10360/10360 | identical | doc |
| G1 snapshots | equity = balance + unrealised; free = equity − used | b1 eq 10080, b2 eq 10280; margin 1102 / 1104 | identical | doc + GAP-6/7 |
| G2 BAR_CLOSE | fill at decision-bar close | buy 1.1007 @b0, sell 1.1038 @b2, gross 310.00; b0 eq 9980 | identical | doc |
| G3a short, comm 7 PER_SIDE | 7 per fill | sell 1.1998, buy 1.1952, gross 460, comm 14, net 446; b1 balance 9993 | identical | doc + GAP-8 timing |
| G3b short, comm 7 ROUND_TRIP | charged once | comm 7, net 453; b1 balance 10000; final 10453 | identical. **But both `order_filled` events report `commission_amount=7.0`** (see D1) | doc + GAP-8 |
| G4a rate 0.00005/unit, 0.5 lot | 0.00005 × 50000 = 2.50 per side | 2.50 + 2.50, gross 200, net 195 | identical | doc |
| G4b flat 1 + rate | 1 + 2.50 = 3.50 per side | net 193 | identical | doc |
| G5 long SL intrabar | SL exit price | pre-run 1.0949 (SL − slip); final 1.0948 (SL − half spread − slip), gross −540 | 1.0948, StopLoss, −540 | **GAP-2** |
| G5b SL on the bar the position opened at open | same-bar eligibility for opens at bar open | SL exit on b1 | b1, 1.0948 | doc |
| G5s short SL intrabar (post-review) | symmetry | sell 1.0998, exit 1.1052, −540 | identical | code-derived |
| G6 long TP intrabar | TP not slipped | exit 1.1050 exactly, +480 | identical | doc (ADR-007) + GAP-3 |
| G6s short TP (post-review) | symmetry | exit 1.0950, +480 | identical | code-derived |
| G6g TP gap (post-review) | favourable gap | exit at open 1.1080, +780 | identical | code-derived |
| G7 SL gap (open 1.0900 < SL 1.0950) | gap rule | 1.0900 − 0.0001 − 0.0001 = 1.0898, −1040 | identical | doc + GAP-4 |
| G8 SL and TP both inside one bar | SL-first | StopLoss, 1.0948, −540 | identical | doc + GAP-2 |
| G9a BUY LIMIT 1.0950 | no retro fill on creation bar; rests; fills at limit; not SL-evaluated on intrabar fill bar | no fill b0/b1, fill 1.0950 @b2, no SL on b2 although low < SL, close 1.0978 @b4, +280 | identical | doc + GAP-5 |
| G9b BUY STOP 1.1050 | trigger, no retro fill, fill-bar protective exemption | pre-run fill 1.1050; final 1.1052 (stop + half spread + slip), +260 | 1.1052, +260 | **GAP-5 / D2** |
| G9c BUY STOP gap (open 1.1100) | gap through stop | 1.1102; final equity 10130 | identical | GAP-4/5 |
| G9d BUY LIMIT gap (post-review) | open below limit | fill at open 1.0900, no costs | identical | code-derived |
| G10 open at end, 2 lots | no force close; balance ≠ equity; margin | entry 1.2502, final 10000 / 10560, margin b2 2506 (= 200000 × 1.2530 / 100) | identical | doc + GAP-7 |
| G11 insufficient margin (balance 1000) | financial rejection | 1 `order_rejected` (category financial), no fill, final 1000/1000 | identical: "insufficient margin: required 1101.2, free margin 1000" | doc |

Generic checks run on every scenario: one snapshot per bar; `equity == balance + unrealised_pnl` and `free_margin == equity − used_margin` on every snapshot; `net == gross − total_commission` on every close; `run_completed` final values equal `RunResult.final_balance` / `final_equity`. All passed.

### First-run failure breakdown (pre-run assumptions, before reading code)

| Cause | Failed checks | Scenarios |
|---|---|---|
| GAP-7: margin price (assumed entry price; engine marks at bar close) | 20, plus the margin-related part of G10 | G1, G2, G3a, G3b, G4a, G5, G9a |
| GAP-2: non-gap SL exit (assumed SL − slip; engine SL − half spread − slip) | 24 | G5, G5b, G8 |
| GAP-5: triggered STOP entry (assumed exact; engine adds half spread + slip) | 8 | G9b |
| GAP-8: ROUND_TRIP per-fill `commission_amount` (assumed 0 on entry; engine reports 7) | 1 | G3b |
| Verifier slip #2 (G10 entry 1.2503 vs correct 1.2502), plus G10 margin | 9 | G10 |
| **Total** | **62** | |

Assumptions that held on the first run: half spread per side (GAP-1, as described in execution-model.md); TP exact (GAP-3); gap SL = open ± half spread ± slip (GAP-4); LIMIT fill exact; gap STOP = open ± half spread ± slip; unrealised P&L marked at the bar close (GAP-6); ROUND_TRIP booked at close and PER_SIDE booked at each fill (GAP-8, balance side); snapshot taken after BAR_CLOSE fills (GAP-9).

## 3. Documentation gaps

| ID | Gap | My assumption | Code behaviour (source) | Code vs docs |
|---|---|---|---|---|
| GAP-1 | Spread per side. `docs/domain/EXECUTION.md`: `fill = open + spread + slippage` (full spread). `execution-model.md`: half on each side. | half | half (`semantics.rs` `market_adjust`, `half_spread()`) | Agrees with execution-model.md. **Contradicts EXECUTION.md.** |
| GAP-2 | Non-gap protective SL exit. ADR-007 and ARCHITECTURE §8 say "SL exits receive slippage". Spread on SL is not mentioned. | SL ∓ slip | SL ∓ half spread ∓ slip (`protective_long/short` → `market_adjust`) | Consistent with the docs but **incomplete**: the extra half spread (1 pip here) is undocumented |
| GAP-3 | Protective TP spread treatment | TP exact | exact. A gap through TP fills at the open (price improvement) | Agrees. Gap-TP-at-open is undocumented. |
| GAP-4 | Gap-through SL "with applicable adjustments" | open ∓ half spread ∓ slip | same | Agrees. The wording should name the adjustments. |
| GAP-5 | Triggered STOP / LIMIT fill price. execution-model.md: "LIMIT/STOP triggered fills … are not adversarially slipped beyond their trigger semantics" | both exact | LIMIT exact (gap: open). STOP: stop ± half spread ± slip, gap: open ± half spread ± slip (`stop_outcome`, documented in its code comment as "becomes market-style") | **LIMIT agrees. STOP contradicts the most natural reading of the docs** (see D2) |
| GAP-6 | Unrealised P&L valuation price | bar close, mid, no spread | `snapshot(bar.close)`; `pnl_amount(entry, close)` | Agrees. Not stated in the docs: equity is not a liquidation value, since spread and slippage on exit are excluded. |
| GAP-7 | "notional = units × price": which price? | entry executed price | snapshot `used_margin` = units × **bar close** / leverage. The **entry margin check** uses the entry executed price (`open_position`) | Docs silent. My assumption was wrong. |
| GAP-8 | Commission timing and per-fill reporting for ROUND_TRIP | PER_SIDE booked at each fill; ROUND_TRIP booked once at close; entry fill reports 0 | Booking as assumed. `order_filled.commission_amount` = computed amount on **every** fill, regardless of mode | Booking agrees. Event field semantics undocumented (see D1). |
| GAP-9 | Snapshot timing relative to BAR_CLOSE fills | after | after | Agrees. Not explicitly documented. |
| GAP-10 | `exit_reason` for an explicit close | not StopLoss/TakeProfit | `"Signal"` | Enumeration undocumented. ARCHITECTURE names only StopLoss/TakeProfit. |
| GAP-11 | Cost decomposition of protective exits | — | SL/TP exits emit only `position_closed` (no `order_filled`), so the applied spread and slippage of an SL exit are not in canonical events. Only `exit_price` is. | Undocumented auditability gap |

## 4. Discrepancies

| # | Finding | Severity | Evidence |
|---|---|---|---|
| D1 | Under `ROUND_TRIP`, both the entry and the exit `order_filled` events carry `commission_amount = 7.0`, but only 7.0 is booked: `position_closed.total_commission = 7`, `commissions_paid = 7`, balance unchanged at entry. Any consumer that sums `order_filled.commission_amount` (an external agent, an MCP client, a future replay panel) would report 14. Balance, equity and P&L are **correct**. | **Ambiguity / canonical-event semantics defect (no ledger impact)**. Either document the field as "computed per-fill amount, not necessarily booked", or emit the amount actually booked on that fill. No in-repo consumer of the field was found. | G3b; `engine.rs` `commission_amount()` is used for every fill; `portfolio.rs` `open_position` books only under PER_SIDE |
| D2 | A triggered (non-gap) STOP entry receives half spread + adverse slippage (buy stop 1.1050 → 1.1052). execution-model.md says "LIMIT/STOP **triggered** fills … are not adversarially slipped beyond their trigger semantics". The code deliberately treats a triggered stop as a market order, and its own unit tests assert that. | **Doc defect** (docs misstate or obscure the code's intended semantics). Economic effect: a stop entry costs half spread + slippage more than the doc reader would expect. | G9b; `semantics.rs` `stop_outcome` |
| D3 | `docs/domain/EXECUTION.md` is stale relative to the engine and execution-model.md: full spread instead of half; "Market orders only"; "limit orders / stop orders: Not MVP"; "close orders use open with minimal slippage". | **Doc defect** | GAP-1; G1/G9 results |
| D4 | SL exits also receive half spread, which ADR-007 / ARCHITECTURE §8 do not state. | **Doc gap (ambiguity)**, no code defect | G5, G5s, G8 |
| D5 | Snapshot `used_margin` is re-marked at each bar close, while the entry affordability check uses the entry price. Both are defensible, but neither is documented. | **Ambiguity** | G1 to G10 snapshots, G11 |
| D6 | Flat snapshots serialise `used_margin` / `unrealised_pnl` as `-0.0` | Cosmetic. Numerically equal to 0, no ledger impact. | `events.jsonl` of every run |

**No economic defect was found**: every documented rule that could be checked produced the hand-computed number.

## 5. Differential check against backtesting.py

- Installed `backtesting` 0.6.6 (with pandas 3.0.6, numpy 2.5.4) into a separate venv `.../scratchpad/venv-diff`. Nothing was installed into the Observa venvs.
- Dataset: 500 daily bars from `random.Random(20261016)`, prices rounded to 0.01, with opening gaps.
- Strategy: SMA(5) / SMA(20) cross, long/flat, 100 units, market orders at the next bar open. Both engines call the same `decide()` function on identical float close lists.

**Reconciliation:**
- Units: Observa `contract_size=1`, `size=100` lots gives 100 units. backtesting.py uses `size=100`.
- Fill timing: Observa `NEXT_BAR_OPEN`, backtesting.py `trade_on_close=False`.
- Open positions are not force-closed: backtesting.py `finalize_trades=False`.
- Cost model: backtesting.py's `spread` is a relative rate (price × (1 ± s)) and it has no slippage concept. Observa's spread and slippage are absolute price units. **No identical spread/slippage configuration exists, so none was compared.**
- Commission can be expressed identically: Observa `commission=2.0`, `commission_rate_per_unit=0.01`, PER_SIDE, and backtesting.py `commission=lambda size, price: 2.0 + 0.01*|size|`, which it applies at entry and at exit.

**Results: 232 checks, 232 PASS, 0 FAIL.**

| Run | Closed trades (Observa / bt) | Per-trade entry/exit bar, entry/exit price, units, net P&L, commission | Open at end | Final equity |
|---|---|---|---|---|
| A: zero cost | 16 / 16 | all equal within tolerance (prices exactly equal) | 100 units in both | 1,000,282.00 in both |
| B: commission 2 + 0.01/unit per side | 16 / 16 | all equal; commission 6.00 per trade in both | 100 units in both | 1,000,183.00 in both |

This is supporting evidence only. Both engines share the decision code and the same simple fill convention, so the comparison checks timing, fill price, P&L and commission bookkeeping on market orders. It does not cover spread, slippage, SL/TP, LIMIT/STOP, BAR_CLOSE mode, shorts or margin.

## 6. What this does NOT establish

- **Coverage.** These are 20 hand-sized scenarios: one symbol, one position at a time, one lot size per scenario. Not covered: hedged long + short at once, many concurrent positions, partial closes (out of MVP scope), quantity-step rounding, SL/TP distance rejections, min/max quantity rejections, expiry of resting orders at dataset end, sell LIMIT / sell STOP entries, short gap cases, ROUND_TRIP with per-unit rate, negative or large prices, non-USD instruments.
- **Metrics.** Sharpe, drawdown, CAGR, win rate and the rest of `metrics.json` were not verified.
- **Regression role.** Literals that depend on GAP-2, 5, 7 and 8 now encode **current code behaviour**, so the harness is a regression ledger for those points, not an independent spec. Whether that behaviour is the *intended* economics is a product decision; the documentation gaps above must be resolved by the owners.
- **Builds.** The results hold for the specific wheel tested, not for later builds, including the uncommitted working-tree edits made concurrently by another process.
- **Differential.** Agreement with backtesting.py does not prove correctness. The two engines were deliberately configured onto the narrow common subset described in §5.
- **Exactness.** The engine uses binary floating point. Values match to within 1e-9 (price) and 1e-6 (money), not exactly. For example, gross P&L 360.0000000000048.

---

# Review of OBS-TRUST-01..03 (fixed build)

Date: 2026-10-16. Independent Finance/QA review of the three tickets, looking for economic consequences and for changes to what a persisted run means. No tracked file was modified.

**Verdict: APPROVE WITH CHANGES.**
- For valid inputs, the fixed build is byte-identical to released 0.1.6 in every comparison I ran: events, metrics, `run.json`, everything the strategy observed and every signal it returned. I found no change to fills, P&L, margin or metrics.
- The changes I recommend are F1, F2 and F4 below (one compatibility regression and two silent or semantic changes). F3 and F5 need release-note or doc coverage.

## Builds compared

| Build | Interpreter | `_observa` sha256 prefix | Built (UTC) |
|---|---|---|---|
| Released 0.1.6 | `scratchpad/venv-rel313/bin/python` | `aea05b73f49eba1c` | 09:12 |
| Fixed (OBS-TRUST-01..03) | `scratchpad/venv-dev/bin/python` | `693d4fdde387626b` | 10:12, after the last code edit (`signal.rs` 10:10) |

Both run CPython 3.13.5. I gave the probe scripts access to pandas 3.0.6 and numpy 2.5.4 by appending the `venv-diff` site-packages to `sys.path` at runtime. Nothing was installed into the Observa venvs.

## What I ran (all reproducible from `harness/finance/`)

| Check | Command | Result |
|---|---|---|
| Golden ledgers, fixed | `venv-dev/bin/python golden_ledgers.py` | **616/616 PASS**, exit 0 |
| Golden ledgers, released (control) | `venv-rel313/bin/python golden_ledgers.py` | **616/616 PASS** |
| Differential vs backtesting.py, fixed | `differential_backtesting_py.py --bt-python venv-diff/bin/python` | **232/232 PASS** |
| Cross-build comparison | `cross_build_compare.py run` under each build, then `compare` | **260/260 PASS** |
| Edge probes (data, timestamps, return shapes, config, history) | `trust_edge_probes.py run` under each build, then `compare` | 51 probes (29 end in an error on the fixed build); see findings |
| CSV strictness | `trust_csv_strict_probe.py` (both builds) | see F8 |
| Retained history views never show later bars | `trust_kept_view_probe.py` (both builds) | 1830 view checks, 0 violations on both |

Outputs are in `harness/finance/trust_evidence/`.

**Cross-build battery: 41 valid cases.** For each case it compares status, `events.jsonl`, `metrics.json` and `run.json` byte for byte, plus a sha256 of every `bar` dict and the full `history` the strategy received on every bar (with the new `timestamp_ms` key removed) and of every signal list returned. The cases:
- All 20 golden scenarios: both fill modes, LIMIT/STOP, SL/TP, gaps, PER_SIDE and ROUND_TRIP, margin rejection.
- On 600 EURUSD-like 15-minute bars (including zero volume), each in NEXT_BAR_OPEN × BAR_CLOSE × PER_SIDE × ROUND_TRIP:
  - SMA cross with SL/TP, longs and shorts;
  - a history-heavy Donchian strategy that walks the full history every bar (iteration, `reversed`, slicing, negative indexing, `in`, `.index`) with STOP and LIMIT entries and hedged positions;
  - a seeded random trader issuing market, limit and stop orders with SL/TP and random explicit closes.
- The same data in seven input forms: `+00:00`, the space form, epoch int, whole epoch floats, no volume key, volume `None`, and CSV.
- The bundled sample strategy on both bundled CSVs.

Across the 41 cases the fixed build produced 1,913 fills, 430 SL/TP exits, 4 order expiries and 1 rejection (the intended G11 margin rejection). Every one of the 41 cases was identical across builds. Within each build, all seven input forms gave identical `events.jsonl`.

## Findings

| # | Finding | Severity | Reproduction (ran) |
|---|---|---|---|
| F1 | **A NaN volume now rejects the whole run**, on list, DataFrame and CSV inputs alike (`DATA_INVALID`), yet volume has no economic role: it feeds only the dataset hash and replay. In 0.1.6 these runs completed with economics **identical** to the clean baseline (9 fills, final 10220 / 10000). Missing volume is also treated inconsistently: an empty CSV cell, `None` or an absent key is accepted as missing, but NaN, which is how pandas represents a missing value, is fatal. Real DataFrames with gaps in volume will stop running. | **Medium: compatibility regression, no economic change** | probes D03, C03, P03 vs D00 / C02 / `input_volume_none` |
| F2 | **In-place edits to history dicts are now silently discarded, even within the same bar.** `history[-1]["close"] = -1.0; history[-1]["close"]` returns -1.0 on 0.1.6 and 1.104 (the original) on the fixed build, with no error. A strategy that adjusts history in place and then reads it back now computes different signals silently. That is the class of silent intent loss OBS-TRUST-01 is meant to remove. Neither build leaks a mutation into the next bar. | **Low–Medium: silent behaviour change for valid strategies** | H probe `mutate_then_reread` |
| F3 | **`timestamp_ms` is added to every `bar` and `history` dict.** As a result: `len(bar)` goes from 6 to 7; summing a bar's numeric values goes from 104.418 to 1704085200104.418; `pd.DataFrame(history).select_dtypes("number")` now includes an epoch-millisecond column (about 1.7e12). A strategy that feeds "all numeric columns" into a model, z-score or PCA changes its features silently. Strategies that read fields by name are unaffected; all 41 cross-build cases were identical. | **Low–Medium: silent for some strategy styles; needs release-note coverage** | H probes `bar_keys`, `len_bar`, `sum_values_last`, `pd_df_numeric_mean_cols` |
| F4 | **`Config.strategy_name` now overrides the class name in three places**: `run.json` `strategy.name`, `run_started.strategy_name`, and the strategy identity hash `strategy.params_sha256` (which is `sha256(name\|params)` when no source file is given). Two *different* classes run with the same label and params now get the **same** identity hash (`f2d822aa…`), whereas 0.1.6 distinguished them (`ae7a630f…` for Trader, `28bdfb4f…` for Other). The same class run with and without a label gets two identities. The bundled example (`AgentExample`) and smoke validation (`AgentSmoke`) set a label. There is no economic effect, but it changes what a persisted run's identity means. | **Low: persisted-run semantics.** Recommend keeping the class name in the hash payload and recording the label as a separate field. | K00, K01, K02 |
| F5 | **`history` is no longer a `list`.** Several operations now raise: `json.dumps(history)`, `copy.deepcopy(history)` and `pickle.dumps(history)` raise `TypeError`; `.append` and `.sort` raise `AttributeError`; `isinstance(history, list)` is False. `np.array(history)` silently becomes a 0-d object array (shape `()` instead of `(6,)`), though `len()` of it then raises. Everything else probed behaves like before: slicing, negative indexing, `reversed`, `sorted`, `max`, `+` in both orders, `== []`, `.copy()`, `bool`, `pd.DataFrame(history)`. All except the numpy case fail loudly. The ticket's compatibility note covers `append` and `isinstance` but not json, pickle, deepcopy or numpy. | **Low: compatibility, mostly loud** | H probes |
| F6 | **Sub-second epoch floats are kept** (the intended change in (d)). With `t + 0.5` timestamps, events are identical apart from the `timestamp` fields (163/163 events), and the economics are identical. What differs is `.500Z` in the timestamps, the dataset `sha256` (`25032e87…` becomes `e12ce8b7…`) and the `metrics.json` `max_drawdown_start`/`end` strings. **Ordering cannot change**: both the old floor and the new microsecond rounding are monotone non-decreasing. The only effect is that bars which floored to the same second, and which 0.1.6 therefore rejected with "strictly increasing chronological order", are now accepted (D15). Inputs within 0.5 µs of each other collapse to equal timestamps and are still rejected loudly. One consequence: re-running a 0.1.6 sub-second dataset gives a different dataset hash, so cross-version hash comparisons will not match for such inputs. | Info (intended; corrects the run's timestamps) | D14, D15 |
| F7 | **Previously accepted invalid inputs now fail loudly.** In 0.1.6 these ran silently, and several changed economics or meaning: <ul><li>NaN close: completed with different P&L (7 fills, 10360 / 10140).</li><li>`inf` high, high < low, negative or zero prices on the list path.</li><li>Epoch milliseconds: accepted with timestamps in year +55969.</li><li>Naive `YYYY-MM-DD HH:MM:SS` strings: accepted and assumed UTC.</li><li>`stop_loss` or `SL` signal keys: silently ignored, so a position opened **without a stop** (1 fill, equity 9780).</li><li>An extra envelope key: ignored while the signals still executed.</li><li>`None`, a bare dict, `{}`, `{"signals": None}`: zero-trade "successful" runs.</li></ul>A config typo (`spred`) now raises `CONFIG_INVALID` with a suggestion. Rejecting a drawings-only envelope (`{"drawings": [...]}`) is a minor compatibility break for a pattern that used to be harmless. | Info (intended); low compatibility note for drawings-only | D04–D13, R_*, K03 |
| F8 | **Real-world data checks.** Accepted on both builds with identical economics: <ul><li>flat bars (O = H = L = C),</li><li>zero volume, absent volume, `None` volume, int and int64 volume,</li><li>`+03:00` offsets (converted to UTC),</li><li>sub-second strings,</li><li>an empty CSV volume cell.</li></ul>Newly accepted: tz-aware `datetime` and pandas tz-aware `Timestamp`, with economics identical to the string form. OHLC validation has **no tolerance**: a 1e-12 inconsistency is rejected. That was already the rule on the 0.1.6 CSV path and now also applies to lists and DataFrames, so vendor float noise (e.g. split-adjusted closes 1 ulp above the high) will be rejected on every path. Negative-price instruments can't be backtested on any path. In 0.1.6 the CSV path accepted `inf` (now rejected). | Info / Low (document; consider a rounding hint) | D01, D02, D12, D16, D18, D20, C02, C04, P01, P04; `trust_csv_strict_probe.py` |
| F9 | **`tick_size` / `pip_size` on `Config`.** They are economically inert. With `tick_size=0.00001, pip_size=0.0001`, the results equal the baseline on both the dict path (both builds) and the new `Config` path (fixed). In the engine they feed only config validation; execution does not use them. | Info | K04, K05 |

## Assessment against the claims

- **(a) Rejecting invalid inputs.** Every probed invalid form now fails loudly with a code. One case rejects input that was economically valid: **NaN volume (F1)**.
- **(b) `timestamp_ms` and the read-only `history`.**
  - `history` content and causality are identical: a full-history digest on every bar of 600-bar runs matched, and retained views never exposed later bars (0 violations in 1830 checks).
  - The additive key and the type change can silently alter some strategy styles (F2, F3, F5).
- **(c) `strategy_name` honoured.** It now names the run and changes the identity hash. There is a collision risk across classes (F4).
- **(d) Sub-second timestamps not floored.** There is no ordering or economic change. Timestamps, dataset hash and drawdown timestamps change only for fractional-epoch inputs (F6).

## What remains unverified

- **CLI path not exercised.** The CLI/YAML strategy bridge (`crates/observa-python/src/signal.rs`) was not run.
- **Test suites not run.** I did not run the Rust or Python suites, including `test_trust_boundary.py` and `test_history_contract.py`.
- **Performance not measured.** I did not measure the O(1) history claim or the 100k-bar runtime.
- **No other platforms.** Only Linux / CPython 3.13 was exercised. Concurrency or threading use of `History` was not tested.
- **Not reviewed:** replay/MCP rendering of fixed-build runs, and `validate-strategy` output. I did not do a line-by-line review of the documentation changes.
- **Input forms not covered:**
  - DataFrames whose timestamps are a `DatetimeIndex` (the index is dropped by `to_dict("records")`);
  - raw numpy `datetime64` scalars;
  - very large or negative epochs near the 1e11 limit;
  - non-UTC tz-aware datetimes across DST changes.
- **Not a full equivalence proof.** The equivalence is shown on the battery above only. Strategies whose logic depends on the dict's key set, on `type(history)`, or on in-place mutation (F2, F3, F5) are exactly where differences can arise.
