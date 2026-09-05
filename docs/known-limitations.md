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
* **Strategy drawings** — drawings are recorded and carried in the replay
  payload but not yet rendered interactively.
* **Platform verification** — wheel verified on Linux x86_64 / CPython 3.13;
  other platforms are unverified (see README).
* **Offline replay** — the chart library is bundled in the wheel (Apache-2.0
  licensed), so replay works offline after installation.
