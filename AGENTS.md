# AGENTS.md — Observa Context for AI Assistants

## What Observa is
Observa is an event-driven visual backtesting engine.
The Rust engine is the source of truth. Python strategies
are loaded at runtime via PyO3.

## How to write a strategy

Strategies are plain Python classes with three required methods:

    class MyStrategy:
        def initialize(self, params=None):
            # Called once before replay starts
            # Set up indicators and state here
            pass

        def on_bar(self, bar, portfolio, history):
            # Called on every closed bar
            # bar: dict with open/high/low/close/volume/timestamp
            # portfolio: dict with balance/equity/has_open_position/
            #            position_direction/position_entry_price/unrealised_pnl
            # history: list of previous bar dicts
            # Returns: list of signal dicts, or empty list
            return []

        def teardown(self):
            # Called once after replay ends
            pass

## Signal format

on_bar() must return a list of dicts:

    {
        'direction': 'buy' | 'sell' | 'close',  # required
        'size':      1.0,                         # required, in lots
        'price':     1.1376,                      # optional, defaults to bar close
        'sl':        1.1350,                      # optional, stop loss price
        'tp':        1.1420,                      # optional, take profit price
        'reason':    'RSI divergence',            # optional, shown on chart tooltip
    }

## Running a strategy

    cargo run -p observa-cli -- run \
        --strategy strategies/my_strategy.py \
        --data data/EURUSD_M15.csv

    # Or with options:
    cargo run -p observa-cli -- run \
        --strategy strategies/my_strategy.py \
        --data data/EURUSD_M15.csv \
        --balance 50000 \
        --spread 0.0002 \
        --commission 7.0

## Example strategy

    class EMACrossover:
        def initialize(self, params=None):
            self.fast_ema = None
            self.slow_ema = None
            self.prev_fast = None
            self.prev_slow = None

        def _ema(self, current, price, period):
            if current is None:
                return price
            k = 2.0 / (period + 1.0)
            return price * k + current * (1.0 - k)

        def on_bar(self, bar, portfolio, history):
            self.prev_fast = self.fast_ema
            self.prev_slow = self.slow_ema
            self.fast_ema = self._ema(self.fast_ema, bar['close'], 5)
            self.slow_ema = self._ema(self.slow_ema, bar['close'], 20)

            if self.prev_fast is None:
                return []

            crossed_up   = self.prev_fast <= self.prev_slow \
                           and self.fast_ema > self.slow_ema
            crossed_down = self.prev_fast >= self.prev_slow \
                           and self.fast_ema < self.slow_ema

            if crossed_up and not portfolio['has_open_position']:
                return [{'direction': 'buy', 'size': 1.0,
                         'sl': bar['close'] - 0.003,
                         'tp': bar['close'] + 0.006,
                         'reason': 'EMA crossover up'}]

            if crossed_down and portfolio['has_open_position']:
                return [{'direction': 'close', 'size': 1.0,
                         'reason': 'EMA crossover down'}]

            return []

        def teardown(self):
            pass

## Architecture — for contributors

The engine is event-sourced. Every meaningful action emits
an immutable event. The event log is the source of truth.

Crate responsibilities:
  observa-core      — Bar, all event types, shared enums
  observa-data      — CSV reader, validation
  observa-engine    — Event Bus, Strategy trait, replay loop
  observa-execution — Fill simulation, spread/slippage/commission
  observa-portfolio — Positions, capital, PnL tracking
  observa-metrics   — Drawdown, Sharpe, Calmar, win rate
  observa-python    — PyO3 bridge, loads Python strategies
  observa-cli       — CLI binary, argument parsing, HTTP server

The four hard rules:
  1. Strategy never places orders directly — it emits signals
  2. Visualization never computes truth — it subscribes to events
  3. Execution model is the only place realism is applied
  4. Every state change emits an event

## Common mistakes to avoid

Wrong — returning a signal without the required fields:
    return [{'direction': 'buy'}]  # missing 'size'

Wrong — mutating the bar dict:
    bar['close'] = 1.1376  # don't do this

Wrong — using future data:
    history[10]  # this is fine, history is past bars only
    # but never try to access future bars — the engine
    # structurally prevents this

Right — always return a list, never a single dict:
    return [signal]   # correct
    return signal     # wrong — must be wrapped in a list