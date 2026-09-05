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

Requirements:

* `timestamp` must parse as RFC 3339 (with timezone) or
  `YYYY-MM-DD HH:MM:SS+00:00` (UTC).
* `open ≤ high`, `low ≤ open/close ≤ high`, `low ≤ close` are validated per
  bar.
* Bars must be strictly chronological — the Engine refuses out-of-order data.
* Data rows are used exactly as supplied: Observa does not invent missing
  candles or interpolate prices. A time gap in the file is treated as a real
  market gap, not as missing continuity.

The bundled deterministic sample (`observa.sample_data_path()`) follows this
format and is synthetic (not market data).

Errors name the row and problem, e.g. a failed price parse or a
non-monotonic timestamp.
