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
* **Annualised metrics need `bars_per_year` for intraday bars** — it is not
  guessed (see `docs/metrics.md`). Without it, annualised return, volatility,
  Sharpe, Sortino and Calmar are reported as unavailable with the reason.
  Returns over less than one year are never annualised. Ratios from short
  samples are noisy; read them with the recorded `sample` sizes.
* **No financing / swap / funding costs** — positions held overnight carry no
  cost, so `total_costs` covers commission, spread and slippage only.
* **Metrics mark equity at the bar close without exit costs**, and there are
  no margin calls: drawdowns can exceed 100 % if equity goes negative, and
  return-based ratios are then unavailable.
* **Memory** — every bar's canonical events and snapshot are kept in memory;
  expect roughly 1 KB per bar (about 1 GB for 1,000,000 bars).
* **Offline replay** — the chart library is bundled in the wheel (Apache-2.0
  licensed), so replay works offline after installation.
