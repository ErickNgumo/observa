# Observa — Strategy API Design

> This document defines the complete interface between a user-written
> strategy and the Observa engine. This is what a trader writes.
> Everything the engine builds must serve this interface.

---

## Design Principles

1. **The strategy declares intent. The engine handles reality.**
   A strategy never places orders — it submits intentions. The execution
   model decides what happens next.

2. **The strategy is isolated.** It cannot reference the engine, the
   data source, or the portfolio directly. It only sees what the engine
   hands it.

3. **Indicators update automatically.** When `on_bar` is called, all
   indicators are already current. The trader just reads and decides —
   exactly like a live chart.

4. **The strategy can look back freely, never forward.** Access to any
   previously closed bar is allowed. Access to future bars is
   structurally impossible.

5. **Every meaningful action is traceable.** Orders carry reasons.
   Fills carry context. Annotations tie notes to specific events.

---

## Full Lifecycle

```
initialize()        → called once before replay starts
  ↓
on_bar(bar)         → called on every closed bar, in strict time order
  ↓ (if order filled)
on_fill(fill)       → called when an entry order is confirmed filled
  ↓ (if position closed)
on_close(fill)      → called when a position is fully closed
  ↓
teardown()          → called once after replay ends
```

---

## Complete Strategy Example — EMA Crossover

```python
from observa import Strategy, OrderIntent, Direction, EMA

class EMACrossover(Strategy):

    def initialize(self, params):
        """
        Called once before replay starts.
        Register indicators and initialise state here.
        """
        self.ema20 = self.indicator(EMA(period=params.get("ema_period_fast", 20)))
        self.ema50 = self.indicator(EMA(period=params.get("ema_period_slow", 50)))
        self.in_trade = False

    def on_bar(self, bar):
        """
        Called on every closed bar, in strict time order.
        Indicators are already updated before this is called.
        bar is the ONLY way to see current market data.
        """

        # Wait until indicators have enough history
        if not self.ema20.ready or not self.ema50.ready:
            return

        # Detect crossover using current and previous values
        crossed_up   = (self.ema20.previous <= self.ema50.previous and
                        self.ema20.value    >  self.ema50.value)

        crossed_down = (self.ema20.previous >= self.ema50.previous and
                        self.ema20.value    <  self.ema50.value)

        # --- Entry ---
        if crossed_up and not self.in_trade:
            self.submit(OrderIntent(
                direction = Direction.BUY,
                size      = 1.0,
                sl        = bar.close - 0.0020,
                tp        = bar.close + 0.0040,
                reason    = "EMA20 crossed above EMA50",
            ))

        # --- Exit ---
        elif crossed_down and self.in_trade:
            self.close(reason="EMA20 crossed below EMA50")

    def on_fill(self, fill):
        """
        Called when an entry order is confirmed filled.
        This is where you update state based on execution reality.
        """
        self.in_trade = True
        self.annotate(fill.event_id, "Entered on EMA crossover")
        self.log(f"Filled at {fill.executed_price} "
                 f"(slippage: {fill.slippage})")

    def on_close(self, fill):
        """
        Called when a position is fully closed.
        PnL and exit reason are available here.
        """
        self.in_trade = False
        self.annotate(fill.event_id,
                      f"Closed — {fill.exit_reason} | PnL: {fill.pnl}")
        self.log(f"Trade closed. PnL: {fill.pnl} | "
                 f"Duration: {fill.duration} | "
                 f"Reason: {fill.exit_reason}")

    def teardown(self):
        """
        Called once after replay ends.
        Good place to emit final annotations or summary logs.
        """
        self.log("Strategy teardown complete.")
```

---

## The Bar Object

What the strategy receives on every `on_bar` call.

```python
bar.open       # opening price of this bar
bar.high       # highest price of this bar
bar.low        # lowest price of this bar
bar.close      # closing price of this bar
bar.volume     # volume for this bar (if available)
bar.timestamp  # exact time this bar closed
```

---

## Lookback — Accessing Previous Bars

The strategy can look back as far as it needs. The engine enforces
the boundary — future bars are structurally inaccessible.

```python
def on_bar(self, bar):

    # Always wait until enough history exists
    if len(self.bars) < 10:
        return

    # Access individual previous bars
    prev1 = self.bars[-1]   # one bar ago
    prev5 = self.bars[-5]   # five bars ago

    # Access slices
    last_10 = self.bars[-10:]
    highest_high = max(b.high for b in last_10)
    lowest_low   = min(b.low  for b in last_10)

    # Detect structure — e.g. three consecutive lower lows
    three_lower_lows = (
        self.bars[-3].low > self.bars[-2].low > self.bars[-1].low
    )
```

**Rules enforced by the engine:**

| Access | Result |
|---|---|
| `self.bars[-1]` | Previous closed bar — allowed |
| `self.bars[-N]` | N bars ago — allowed |
| `self.bars[-10:]` | Slice of last 10 bars — allowed |
| `self.bars[+1]` | Future bar — raises `FutureDataAccessError` |

---

## Indicators

Indicators are registered in `initialize` and updated automatically
by the engine before every `on_bar` call.

```python
def initialize(self, params):
    self.ema20  = self.indicator(EMA(period=20))
    self.rsi14  = self.indicator(RSI(period=14))
    self.bb     = self.indicator(BollingerBands(period=20, std=2.0))
```

**Reading indicator values in `on_bar`:**

```python
def on_bar(self, bar):
    # Check if indicator has enough history to be valid
    if not self.ema20.ready:
        return

    current  = self.ema20.value     # current bar value
    previous = self.ema20.previous  # previous bar value

    # Indicators with multiple outputs
    upper = self.bb.upper
    lower = self.bb.lower
    mid   = self.bb.mid
```

**Indicator update rule:**

> When `on_bar` is called, all indicators are already updated.
> The trader never calls `.update()` manually.
> This mirrors exactly how indicators behave on a live chart.

---

## Submitting Orders

The strategy never places orders directly. It submits an intent.
The execution model decides what happens — applying spread,
slippage, commission, and fill logic.

```python
# Entry — market order with SL and TP
self.submit(OrderIntent(
    direction = Direction.BUY,       # Direction.BUY or Direction.SELL
    size      = 1.0,                 # lot size
    sl        = bar.close - 0.0020,  # stop loss price
    tp        = bar.close + 0.0040,  # take profit price
    reason    = "EMA crossover",     # appears on chart tooltip
))

# Exit — close current position
self.close(reason="EMA crossed back")
```

**What happens next:**

```
self.submit(OrderIntent)
  → OrderIntentCreatedEvent emitted
  → Execution Model applies spread, slippage, commission
  → OrderFilledEvent emitted
  → on_fill(fill) called on strategy
```

The strategy never assumes the order was filled. It waits for
`on_fill` to confirm execution reality.

---

## The Fill Object

Received in both `on_fill` (entry) and `on_close` (exit).

```python
def on_fill(self, fill):
    fill.executed_price  # actual fill price after slippage
    fill.intended_price  # price the strategy requested
    fill.slippage        # difference between intended and executed
    fill.spread_cost     # cost of spread applied at fill
    fill.commission      # broker commission charged
    fill.direction       # Direction.BUY or Direction.SELL
    fill.fill_type       # FillType.ENTRY or FillType.EXIT
    fill.timestamp       # exact time of fill
    fill.event_id        # ties this fill to the event log

def on_close(self, fill):
    fill.pnl             # realised PnL for this trade
    fill.exit_reason     # ExitReason.TP | ExitReason.SL | ExitReason.SIGNAL
    fill.duration        # how long the trade was open
    fill.executed_price  # exit price
    fill.commission      # commission on exit
    fill.event_id        # ties this close to the event log
```

**Exit reasons:**

| Reason | Meaning |
|---|---|
| `ExitReason.TP` | Take profit was hit |
| `ExitReason.SL` | Stop loss was hit |
| `ExitReason.SIGNAL` | Strategy called `self.close()` |
| `ExitReason.REJECTED` | Order was rejected by execution model |

---

## Utility Methods

Methods available on `self` inside any strategy hook.

```python
# Submit a trade intent
self.submit(OrderIntent(...))

# Close current open position
self.close(reason="optional reason string")

# Register an indicator
self.indicator(EMA(period=20))

# Attach a journal note to a specific event
self.annotate(fill.event_id, "Note text here")

# Emit a structured log entry into the event stream
self.log("Any message here")
```

---

## What Self Exposes and Does Not Expose

The sandbox boundary — what the strategy is and is not allowed to touch.

| Allowed | Not Allowed |
|---|---|
| `self.bars` — read-only bar history | `self.data` — no data source reference |
| `self.indicator(...)` — register indicators | `self.portfolio` — no direct portfolio write |
| `self.submit(...)` — declare intent | `self.engine` — no engine reference |
| `self.close(...)` — declare exit intent | Any mutable shared state |
| `self.annotate(...)` — journal notes | Future bar access |
| `self.log(...)` — structured logging | |
| `self.params` — config passed at init | |

---

## What the Engine Guarantees

These are promises the engine makes to every strategy.

1. `on_bar` is called in strict chronological order — never out of sequence
2. All indicators are updated before `on_bar` is called
3. `self.bars` contains only closed bars — never the current or future
4. `on_fill` is always called before the next `on_bar` after a fill
5. `on_close` is always called when a position closes, regardless of reason
6. Same inputs always produce the same sequence of calls — determinism

---

*This API is frozen for MVP. Extensions — multiple positions, limit
orders, multi-timeframe — are added after the core is proven correct.*