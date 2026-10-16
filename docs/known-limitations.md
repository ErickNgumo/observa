# Known Limitations (release candidate)

Honest scope of the MVP release candidate:

* **Bar-based execution** — no ticks, order books, or partial fills.
* **No margin calls / liquidation** — insufficient margin rejects an entry
  (`financial` rejection) but open positions are never force-liquidated.
* **No multi-currency conversion** — the account currency must equal the
  instrument quote currency.
* **No advanced time-in-force** — MVP orders are GTC-style (pending, filled,
  rejected, or expired at dataset end).
* **OHLC ambiguity** — intrabar paths are not modeled; deterministic
  conventions (SL-first etc.) are documented in `docs/execution-model.md`.
* **Pending trigger price in replay** — canonical events do not currently
  carry a resting LIMIT/STOP trigger price, so replay shows `pending` status
  without the requested price. It never invents one. A schema addition is a
  planned backlog item.
* **Strategy drawings** — annotations are canonical events
  (`drawings_emitted`), persisted in `events.jsonl`, reconstructed by replay and
  rendered (series, levels, zones, regions, markers, labels). A shaded band
  primitive and multi-pane layouts beyond one generic secondary pane are not
  part of the contract yet; a band is expressed as three series.
* **Platform verification** — wheel verified on Linux x86_64 / CPython 3.13;
  other platforms are unverified (see README).
* **Annualised metrics assume `bars_per_year=252`** unless you pass
  `observa.run(..., bars_per_year=...)`; the `interval` setting does not change
  it, and the factor is not recorded in the run artifacts. For intraday data,
  annualised return, Sharpe and Calmar are mis-scaled unless you set it (see the
  2026-10 trust audit, finding M01, pending a product decision).
* **Memory** — every bar's canonical events and snapshot are kept in memory;
  expect roughly 1 KB per bar (about 1 GB for 1,000,000 bars).
* **Offline replay** — the chart library is bundled in the wheel (Apache-2.0
  licensed), so replay works offline after installation.
