# Observa — next release (DRAFT, not published)

> Draft prepared by the 2026-10 trust audit. The version number is not chosen
> yet (see "Versioning" below). Nothing here has been released.

This release removes three ways Observa could give a wrong or misleading
answer without saying so. Execution and backtest economics for valid inputs are
unchanged (byte-identical canonical events; golden ledgers 616/616).

## Mistakes now fail loudly instead of silently

- A signal key that Observa does not know — for example `stop_loss` instead of
  `sl` — used to be ignored, so the position opened **without a stop**. The run
  now stops at that bar with `SIGNAL_FIELD_UNKNOWN` and suggests the right key.
- Returning `None` from `on_bar` (a missing `return`), a bare signal dict, or a
  dict without a `signals` list used to produce a "successful" run with no
  trades. It now fails with `STRATEGY_RETURN_INVALID` at the offending bar.
- A misspelled key in a config dict (`{"spred": 0}`) used to fall back to the
  default silently. It now fails with `CONFIG_INVALID` and suggests the key.
- `observa.Config` accepts `tick_size` and `pip_size` (issue #5).
  (`strategy_name` is still accepted but not recorded; recording it safely
  needs a run-schema change — see the audit's deferred items.)

## Market data is validated the same way on every input path

- NaN and infinite prices are rejected (CSV and Python inputs). A NaN
  volume — pandas' marker for a missing value — is treated as missing, like an
  empty cell; an infinite or negative volume is rejected.
- Python lists and DataFrames now get the same OHLC checks as CSV files
  (high below low, negative prices, … were accepted before).
- Timestamps must carry a timezone. Epoch values must be **seconds** — a
  millisecond value is rejected instead of being read as the year 56971.
  Timezone-aware `datetime` / `pandas.Timestamp` values are accepted.
  Sub-second epoch precision is kept instead of floored.
- Errors name the row: `exc.details["row"]`.

## Timestamps you can join on (issue #8)

- `bar["timestamp"]` is documented and test-pinned as the canonical UTC string
  `YYYY-MM-DDTHH:MM:SS[.f…]+00:00` (fractional seconds only when non-zero) (an input `...Z` is shown as `...+00:00`).
- New `bar["timestamp_ms"]`: integer epoch milliseconds. Join external data on
  it, never on the input string.

## Long intraday runs are fast (issue #6)

- `history` is now a read-only, list-like view that costs O(1) per bar. A
  100,000-bar one-minute run takes about 2 seconds (it was roughly 3 hours);
  1,000,000 bars take about 16 seconds for a strategy that ignores history.
- What strategies see is unchanged: the same bar dicts, slices return lists,
  `history[0] is history[0]` within a bar, and edits never leak into later
  bars. `copy.copy`, `copy.deepcopy` and `pickle` give lists.

## Upgrading

| If your strategy… | Change |
| --- | --- |
| uses `stop_loss` / `take_profit` / `quantity` / `qty` in a signal | use `sl` / `tp` / `size` |
| returns `None` or nothing on "no action" bars | `return []` |
| returns a bare signal dict | `return [signal]` |
| returns `{"drawings": [...]}` only | `{"signals": [], "drawings": [...]}` |
| calls `history.append(...)` or checks `isinstance(history, list)` | use `list(history)` |
| passes timezone-less timestamps | append `Z` or `+00:00`, or attach a tzinfo |
| passes epoch milliseconds | divide by 1000 |
| passes extra keys in a config dict | remove or fix them |
| serialises `history` with `json.dumps` | `json.dumps(list(history))` |
| feeds *every* numeric column of `bar`/`history` into a model | exclude the new `timestamp_ms` column |
| relies on `len(bar) == 6` | bar dicts now have 7 keys (`timestamp_ms`) |
| passes Python/DataFrame bars with tiny OHLC float noise (high < close by 1e-12) | clean the data; the list path now applies the CSV path's exact checks |

## Versioning

These are intentional contract tightenings (previously silent inputs now
fail). Under the project's pre-1.0 versioning this suggests a minor bump
(0.2.0) rather than 0.1.7. The version number and release tag are for the
maintainer to choose; installation URLs in the docs still point to 0.1.6.

## Known limitations still open

See `docs/audit/2026-10-trust-audit.md` §8: intraday annualisation of
metrics (`bars_per_year`), zero-trade-run diagnostics, execution-model
documentation gaps found by Finance/QA, and roughly 1 KB of memory per bar.
