# Portfolio Domain

## Responsibilities

- Track account balance.
- Track open positions.
- Calculate realised and unrealised PnL.
- Calculate mark-to-market equity.
- Check SL/TP on every bar.
- Emit portfolio events and snapshots.

## Multiple positions

Multiple simultaneous positions are supported.

Positions are identified by UUID ticket. New code should target specific tickets rather than relying on the old FIFO fallback.

## Known issue

The source KB says `pct_equity` and `pct_balance` fields are mathematically wrong because they mix quantity units and monetary units. `InstrumentSpec` was introduced to correct this but is not fully wired everywhere.

## Snapshot rule

A portfolio snapshot should be emitted on every bar, including unrealised PnL, so the equity curve is mark-to-market.
