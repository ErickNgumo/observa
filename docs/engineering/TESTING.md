# Observa Testing

## Philosophy

Tests should prove invariants and known behavior, not just execute code.

## Rules

- Every new feature has tests.
- Every bug fix has a regression test.
- Validation should report all relevant errors rather than only the first.
- PyO3 tests must initialize the Python runtime as required by the project implementation.
- Use the Python mock harness for rapid strategy-side iteration where appropriate.

## Test levels

### Unit tests

Test individual calculations and invariants inside each crate/module.

### Integration tests

Verify interactions between crates and event sequences.

### Known-answer tests

Use deterministic fixtures where exact expected PnL, fills, positions, and metrics are known.
See [Canonical deterministic regression baseline](#canonical-deterministic-regression-baseline)
for the project-wide oracle.

### End-to-end tests

Verify the user workflow from loading data and strategy through completed replay and rendered output/API payload.

## High-value regression areas

- SL/TP validation after spread/slippage.
- SL slippage versus TP no-slippage behavior.
- Portfolio snapshots every bar.
- Timestamp correctness using market-data timestamps.
- InstrumentSpec exposure calculations.
- Position ticket closing.
- PyO3 conversion contracts.
- Event chain integrity.
- Documentation/API synchronization.

## CI expectations from the source KB

The historical proposal calls for GitHub Actions to run tests on pushes and to add checks that strategy-facing documentation stays synchronized with the Rust conversion code.

## Canonical deterministic regression baseline

`python/tests/test_canonical_baseline.py` is the project's canonical economic
regression oracle. It runs one fixed strategy over one fixed synthetic dataset
and asserts the canonical economics explicitly. Any change to fills,
spread/slippage, commission, SL/TP execution, position pairing, portfolio
accounting, events or metrics changes these values and fails CI with an
explicit expected/actual table.

### Where the fixture lives

| Item | Value |
| --- | --- |
| Fixture | `python/tests/fixtures/canonical_m15.csv` (1500 M15 bars, ~94 KB) |
| Generator | `python/tests/fixtures/generate_canonical_dataset.py` |
| Reproduce fixture | `python python/tests/fixtures/generate_canonical_dataset.py` |
| Integrity check | the test regenerates in memory and asserts the committed file matches byte for byte |

The generator is fully deterministic: a fixed start timestamp
(`2024-01-01T00:00:00Z`, never "now"), a fixed bar count, an integer LCG and a
closed-form price level. It uses no network, no clock, no unseeded randomness
and no user-local files, so the fixture bytes are identical on any machine at
any time.

### Exact canonical case

| Setting | Value |
| --- | --- |
| Strategy | `observa.samples.sample_strategy.SampleEma` (`fast=5`, `slow=20`) |
| Fill mode | `next_bar_open` |
| Spread | `0.0002` |
| Slippage | `0.0001` |
| Commission | `7.0`, `round_trip` (flat per fill) |
| Interval | `15m` |
| Account / instrument | Observa defaults (10 000 USD, 100:1 leverage, 100 000 contract, max 100 lots) |

### Exact command to reproduce

```bash
python -m pip install <observa wheel>
python python/tests/test_canonical_baseline.py
```

### Expected outputs

| Field | Expected |
| --- | --- |
| total_bars | 1500 |
| events | 4862 |
| trades | 47 |
| orders | 88 |
| fills | 95 |
| open_positions | 1 |
| final_balance | 7718.000000000193 |
| final_equity | 7737.0000000002065 |
| total_return_pct | -22.629999999997935 |
| max_drawdown_pct | 35.615097026881344 |
| max_drawdown_start / end | 2024-01-01T11:45:00Z / 2024-01-11T21:30:00Z |
| sharpe_ratio | -0.4797045550240251 |
| calmar_ratio | -0.1184558643823262 |
| total / winning / losing trades | 47 / 7 / 40 |
| win_rate_pct | 14.893617021276595 |
| profit_factor | 0.6987060998151756 |
| expectancy | -48.5531914893576 |
| metrics digest (supplemental) | `6c23dc6c0c0630e66bd21290c47f48bb00ac6612d66b2b7047df7a191ea77b44` |

`orders` (88) counts strategy-submitted orders; protective `StopLoss` exits
appear as additional `fills` (95) and as `position_closed` events with
`exit_reason` set, not as order records. The fixture deliberately produces a
mix of signal exits (40) and stop-loss exits (7), and both winning (7) and
losing (40) trades, so win/loss and drawdown metric paths are exercised.

The fixture is synthetic: these numbers are a regression oracle, not a
performance claim.

### Supplemental digest

The test derives a SHA-256 over the canonical metrics JSON and asserts it in
addition to the explicit fields above. The digest is supplemental — a failure
must still show the expected/actual table for the key economics, never an
opaque hash only.

### Why rolling/live market data must never be a regression oracle

The former "1500-bar canonical baseline" used `data/EURUSD_M15.csv`. That file
is **untracked and gitignored**, and it is produced by `data/data_download.py`
from a rolling yfinance window (`period="60d"`, `tail(1500)`), so its contents
change between downloads. As a result the numbers recorded from it
(4877 events / 8689.465385437186) could never be reproduced once the file was
refreshed, which is exactly the kind of phantom regression this baseline
removes. A one-bar shift in that file already moves the canonical event count
by ~11 and the balance by ~86. Regression oracles must be checked in and
deterministic.

### Deliberately re-baselining

Only change `EXPECTED`, `EXPECTED_METRICS` or the fixture when the change is
intended and reviewed:

1. regenerate the fixture (if the model changed),
2. run the test and inspect every differing field,
3. explain the change in the commit message / ticket,
4. update the expected values (and the digest) in the same commit,
5. never accept a new baseline just to make a failing test pass.
