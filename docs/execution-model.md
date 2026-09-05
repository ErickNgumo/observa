# Execution Model & Assumptions

Observa is a **bar-based** backtester with deterministic conventions. It is
not a tick/broker simulation; treat results as research output.

## Fill modes

Market orders generated while the strategy observes completed bar `N` execute
by fill mode:

* `BAR_CLOSE` — fills at bar `N`'s close.
* `NEXT_BAR_OPEN` — fills at bar `N+1`'s open.

The replay shows the decision bar and the fill bar separately, so the absence
of lookahead is visible.

## LIMIT / STOP

A LIMIT/STOP created after observing bar `N` **cannot** retroactively fill
using bar `N`'s range; it starts evaluating on future market data and rests
until triggered. LIMIT fills when price trades at/through the limit price;
STOP triggers when price reaches the stop price, with gap handling below.

## Spread & slippage

* Spread is applied half on each side of the market reference (a fixed
  `spread` config is treated as a full spread).
* Market-style executions (entries and explicit closes) receive **adverse**
  slippage.
* LIMIT/STOP **triggered** fills and protective TP are not adversarially
  slipped beyond their trigger semantics; gap-through stops execute at the
  currently available canonical market reference with applicable adjustments.

Example (SL gap): `SL = 1.0000`, next open `0.9900`. The stop cannot execute
at 1.0000; it fills at the canonical market reference with applicable
adjustments (replay shows the executed price).

## Protective SL / TP

* `sl`/`tp` are attached to a position when it opens and are Engine-evaluated
  thereafter.
* Protective chronology: a position **opened at bar open** is eligible for
  same-bar protective processing; a position **opened intrabar** (resting
  LIMIT/STOP) or **at BAR_CLOSE** becomes eligible starting the next bar.
  Reason: the full OHLC range may contain prices that occurred before the
  intrabar entry.
* Same-bar ambiguity: when both SL and TP are reachable in one OHLC bar and
  opening-gap logic does not resolve it, the Engine applies the accepted
  **SL-first** convention. This is a deterministic backtesting convention,
  not a claim about the true intrabar path — OHLC bars do not reveal it.

## Commission

Canonical commission = `flat_per_fill + rate_per_unit × units`, charged per
side (`PER_SIDE`) or once per completed round trip (`ROUND_TRIP`). Python
`Config` exposes both: `commission` (flat) and
`commission_rate_per_unit` (per base unit; e.g. `0.00005` == $5 per 100,000
units).

## Margin & leverage

```text
units           = lots × contract_size
notional        = units × price
margin_required = notional / leverage
free_margin     = equity - used_margin
```

Margin is **reserved**, not deducted from balance. Balance excludes
unrealised P&L; equity includes it. At the end of a run with open positions,
`balance != equity`.

## Positions & hedging

Multiple simultaneous positions are supported, including long and short on
the same symbol. Closes always target an exact `position_id`.

## End of run

Open positions are **not** force-closed at dataset end; their unrealised P&L
remains in final equity and is reported in the result/replay.

## Config reference (public Python fields)

`starting_balance`, `currency`, `leverage`, `symbol`, `base_currency`,
`quote_currency`, `contract_size`, `price_decimals`, `tick_size`,
`pip_size`, `min_quantity`, `max_quantity`, `quantity_step`, `fill_mode`,
`spread`, `slippage`, `commission`, `commission_mode`,
`commission_rate_per_unit`, `interval`, `order_model`, `params`,
`strategy_name`, `strategy_source`, `dataset_source`.

See `docs/known-limitations.md` for what is explicitly not modeled.
