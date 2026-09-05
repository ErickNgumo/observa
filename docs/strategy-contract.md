# Python Strategy Contract

A strategy is a plain Python class. The canonical Rust Engine drives its
lifecycle; Python expresses intent, the Engine determines execution.

## Lifecycle

```python
class MyStrategy:
    def initialize(self, params=None):
        """Called once before the first bar, with the resolved parameters
        dict (empty dict when no parameters are configured)."""

    def on_bar(self, bar, portfolio, history):
        """Called once per closed bar, in chronological order. Returns a list
        of signal dicts (or an empty list)."""

    def teardown(self):
        """Called once after the last bar. Raising here fails the run."""
```

* `history` contains strictly earlier bars only — the current bar is never in
  `history`, so there is no lookahead.
* A Python exception in any callback fails the run with the exception message;
  it is never silently converted into "no signal".

## `bar`

A read-only dict: `timestamp` (RFC 3339 string), `open`, `high`, `low`,
`close`, `volume` (float or `None`).

## `portfolio`

A read-only dict with canonical snapshot fields:

```python
portfolio["balance"]         # realised cash
portfolio["equity"]          # balance + unrealised P&L
portfolio["used_margin"]
portfolio["free_margin"]
portfolio["has_open_position"]
portfolio["open_positions"]  # list of position dicts
```

Each position dict exposes `position_id` (and alias `ticket`), `symbol`,
`direction` (`Buy`/`Sell`), `quantity` (alias `size`), `entry_price`,
`stop_loss`, `take_profit`, `unrealized_pnl`.

Positions must be closed by **exact `position_id`** — there is no implicit
"close the oldest" fallback.

## Signals

`on_bar` returns a list of signal dicts.

### Direction

```python
{"direction": "buy",  "size": 1.0}
{"direction": "sell", "size": 1.0}
{"direction": "close", "size": pos["size"], "ticket": pos["position_id"]}
```

### Order type

Market is the default. Entries may specify `order_type`:

```python
# MARKET (default)
{"direction": "buy", "size": 1.0, "order_type": "market",
 "price": bar["close"], "sl": ..., "tp": ...}

# LIMIT — trigger price in "price"
{"direction": "buy", "size": 1.0, "order_type": "limit", "price": 1.05}

# STOP — trigger price in "price"
{"direction": "sell", "size": 1.0, "order_type": "stop", "price": 1.10}
```

Optional fields on entry signals: `sl`, `tp` (protective levels), `reason`
(display text).

**Rule:** Python specifies intent. Triggering, fill timing, spread/slippage,
SL/TP evaluation and P&L are owned by the Engine. See
`docs/execution-model.md`.

## Constants

The package exposes string constants for ergonomics:
`observa.MARKET / LIMIT / STOP`, `observa.BUY / SELL / CLOSE`,
`observa.BAR_CLOSE / NEXT_BAR_OPEN`, `observa.PER_SIDE / ROUND_TRIP`.
