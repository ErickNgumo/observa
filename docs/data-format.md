# Data Format

Observa accepts an OHLCV CSV, a Python list of bar dicts/sequences, or a
DataFrame-like object (duck-typed via `.to_dict("records")`).

## CSV columns

```text
timestamp,open,high,low,close,volume
```

`volume` is optional. Example rows:

```text
timestamp,open,high,low,close,volume
2024-01-01 00:00:00+00:00,1.10000,1.10008,1.09968,1.09990,334.5
2024-01-01 00:15:00+00:00,1.09990,1.10002,1.09971,1.09990,439.8
```

Requirements (identical for CSV, list and DataFrame inputs):

* `timestamp` must carry a timezone: RFC 3339 with `Z` or an offset, or
  `YYYY-MM-DD HH:MM:SS+00:00`. List/DataFrame inputs may also use
  timezone-aware `datetime` objects (incl. `pandas.Timestamp`) or numeric epoch
  **seconds** (sub-second precision is kept). Timezone-less timestamps,
  booleans and numbers too large to be epoch seconds (e.g. milliseconds) are
  rejected with `DATA_INVALID` and a hint — Observa never guesses a timezone or
  a unit.
* Prices must be finite and positive (NaN/inf are rejected). Volume, when
  present, must be finite and non-negative; a NaN volume (pandas' missing-value
  marker) is treated as missing, like an empty cell.
* `open ≤ high`, `low ≤ open/close ≤ high`, `low ≤ close` are validated per
  bar.
* The error names the offending row: `exc.details["row"]` is the zero-based
  data row (the first bar is row 0) for CSV and list inputs alike.

Strategies always see `bar["timestamp"]` as the canonical UTC string
`YYYY-MM-DDTHH:MM:SS[.f…]+00:00` (fractional seconds only when non-zero, with
3, 6 or 9 digits) plus `bar["timestamp_ms"]` (epoch
milliseconds). Join external data on `timestamp_ms`, not on input strings.
Extra columns are ignored (see issue #1 for external features).
* Bars must be strictly chronological — the Engine refuses out-of-order data.
* Data rows are used exactly as supplied: Observa does not invent missing
  candles or interpolate prices. A time gap in the file is treated as a real
  market gap, not as missing continuity.

Two datasets ship in the wheel:

* `observa.sample_data_path()` — the **synthetic, deterministic** sample used by
  the quickstart and the regression oracle. Not market data.
* `observa.demo_data_path()` — a fixed **real** EUR/USD 15-minute series
  (600 bars) for the demo, replay and screenshots. It omits the `volume` column
  because Yahoo Finance reports no FX volume; see
  [demo-dataset.md](demo-dataset.md) for full provenance. Reading it needs no
  network, no `yfinance` and no `pandas`.

Errors name the row and problem, e.g. a failed price parse or a
non-monotonic timestamp.
