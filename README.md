# Observa

> A visual backtesting engine for algorithmic traders who need to *see*
> their strategy execute, not just trust the numbers.

## What This Is

Observa is an event-driven backtesting platform that replays market data
bar by bar, showing fills, exits, indicators, and strategy decisions as
they happen. Instead of returning a Sharpe ratio and asking you to trust
it, Observa lets you watch your strategy think — and catch what the
numbers hide.

## Project Status

> Active development — MVP phase. Core engine, Python bridge, and visual
> replay are working. UI polish and pip packaging are in progress.

---

## Installation

### Prerequisites

**Rust** — the engine is written in Rust. Install it with:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Restart your terminal after installation, then verify:

```bash
rustc --version   # should show rustc 1.75 or later
cargo --version
```

**Python 3.10+** — strategies are written in Python.

```bash
python3 --version   # should show 3.10 or later
```

**Python development headers** — required for the Rust/Python bridge:

```bash
# Ubuntu / Debian
sudo apt install python3-dev

# macOS (headers included with Xcode Command Line Tools)
xcode-select --install

# Fedora / RHEL
sudo dnf install python3-devel
```

---

### Clone and Build

```bash
git clone https://github.com/ErickNgumo/observa.git
cd observa
cargo build -p observa-cli
```

Build time is approximately 60-90 seconds on first run while dependencies
compile. Subsequent builds are much faster.

Verify the build succeeded:

```bash
cargo run -p observa-cli -- --help
```

You should see the Observa help output.

---

## Quick Start

### 1. Prepare your data

Observa accepts CSV files in OHLCV format:

```
timestamp,open,high,low,close,volume
2022-01-03 09:00:00+00:00,1.1376,1.13787,1.1376,1.13786,278.19
2022-01-03 09:15:00+00:00,1.13785,1.13793,1.1376,1.13786,271.72
```

Place your CSV file in the `data/` folder:

```bash
mkdir -p data
cp your_data.csv data/EURUSD_M15.csv
```

Free data sources:
- [Dukascopy](https://www.dukascopy.com/swiss/english/marketwatch/historical/) — forex historical data
- [Alpha Vantage](https://www.alphavantage.co/) — stocks, forex, crypto (free API key)
- [Yahoo Finance](https://finance.yahoo.com/) — stocks via `yfinance` Python library

### 2. Generate a config file

```bash
cargo run -p observa-cli -- init
```

This creates `config.yaml` in your current directory with all default
settings. Edit it to match your instrument and broker:

```yaml
execution:
  spread:     0.0002   # 2 pips for EURUSD
  slippage:   0.0001   # 1 pip
  commission: 7.0      # $7 per trade

account:
  initial_balance: 10000.0

instrument:
  symbol:        EURUSD
  contract_size: 100000
  pip_value:     10.0
  price_decimals: 5
  margin_rate:   0.01
```

### 3. Write your strategy

Create a Python file. A strategy is a plain class with three methods:

```python
# strategies/my_strategy.py

class MyStrategy:

    def initialize(self, params=None):
        # Called once before the first bar
        # Set up your state and indicators here
        self.fast_ema = None
        self.slow_ema = None

    def on_bar(self, bar, portfolio, history):
        # Called on every closed bar
        # bar        — dict with open/high/low/close/volume/timestamp
        # portfolio  — dict with balance/equity/open_positions
        # history    — list of previous bar dicts
        # Returns a list of signal dicts, or []
        return []

    def teardown(self):
        # Called once after the last bar
        pass
```

See the [example strategies](#example-strategies) section for complete
working examples.

### 4. Run the backtest

```bash
cargo run -p observa-cli -- run \
  --strategy strategies/my_strategy.py \
  --data data/EURUSD_M15.csv
```

Observa will:
1. Detect the strategy class automatically
2. Load and validate the CSV data
3. Run the backtest
4. Print a summary to the terminal
5. Open `http://localhost:7878` — press Play to watch the replay

---

## The Strategy API

### What your strategy receives

Every bar, `on_bar` receives three arguments:

**`bar`** — the current closed candle:
```python
bar['open']       # float
bar['high']       # float
bar['low']        # float
bar['close']      # float
bar['volume']     # float or None
bar['timestamp']  # ISO 8601 string e.g. "2022-01-03T09:00:00+00:00"
```

**`portfolio`** — current account state:
```python
portfolio['balance']           # float — realised balance
portfolio['equity']            # float — balance + unrealised PnL
portfolio['has_open_position'] # bool
portfolio['unrealised_pnl']    # float
portfolio['open_positions']    # list of open position dicts
```

Each open position:
```python
position['ticket']         # string — use this to close the position
position['direction']      # "Buy" or "Sell"
position['size']           # float
position['entry_price']    # float
position['unrealised_pnl'] # float
position['sl']             # float or None
position['tp']             # float or None
```

**`history`** — list of all previous bar dicts, oldest first:
```python
history[-1]   # previous bar
history[-5]   # 5 bars ago
history[-20:] # last 20 bars as a list
```

### Returning signals

`on_bar` must return a list. Each item is a signal dict:

```python
# Open a long position
return [{
    'direction': 'buy',      # required: 'buy', 'sell', or 'close'
    'size':      1.0,        # required: lot size
    'price':     1.1376,     # optional: defaults to bar close
    'sl':        1.1346,     # optional: stop loss price
    'tp':        1.1436,     # optional: take profit price
    'reason':    'My reason', # optional: shown on chart tooltip
}]

# Close a specific position by ticket
return [{
    'direction': 'close',
    'ticket':    position['ticket'],   # which position to close
    'size':      1.0,
    'reason':    'Exit signal',
}]

# Do nothing this bar
return []
```

### Custom drawings

Strategies can draw directly on the chart:

```python
return {
    'signals': signals,
    'drawings': [
        {
            'id':         'my_box',
            'type':       'rectangle',
            'time_start': history[-2]['timestamp'],
            'time_end':   None,
            'price_top':  1.1420,
            'price_bot':  1.1376,
            'color':      '#3fb95044',
            'border':     '#3fb950',
        },
        {
            'id':    'key_level',
            'type':  'hline',
            'time':  bar['timestamp'],
            'price': 1.1400,
            'color': '#f85149',
            'style': 'dashed',
        },
        {
            'id':       'my_label',
            'type':     'label',
            'time':     bar['timestamp'],
            'price':    1.1420,
            'text':     'Resistance',
            'color':    '#e6edf3',
            'position': 'above',
        },
    ]
}
```

Drawing types: `rectangle`, `hline`, `line`, `label`, `region`, `bar_color`

To update or remove a drawing later:
```python
# Update
{'id': 'my_box', 'action': 'update', 'color': '#f8514944', ...}

# Remove
{'id': 'my_box', 'action': 'remove'}
```

---

## Example Strategies

Example strategies live in the `strategies/` folder.

### EMA Crossover (`strategies/ema_crossover.py`)

Buys when the fast EMA crosses above the slow EMA.
Closes when it crosses back below.

```python
class EMACrossover:

    def initialize(self, params=None):
        self.fast_ema  = None
        self.slow_ema  = None
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
        self.fast_ema  = self._ema(self.fast_ema, bar['close'], 5)
        self.slow_ema  = self._ema(self.slow_ema, bar['close'], 20)

        if self.prev_fast is None:
            return []

        crossed_up   = self.prev_fast <= self.prev_slow \
                       and self.fast_ema > self.slow_ema
        crossed_down = self.prev_fast >= self.prev_slow \
                       and self.fast_ema < self.slow_ema

        positions = portfolio['open_positions']

        if crossed_up and not portfolio['has_open_position']:
            return [{
                'direction': 'buy',
                'size':      1.0,
                'sl':        bar['close'] - 0.003,
                'tp':        bar['close'] + 0.006,
                'reason':    'EMA crossover up',
            }]

        if crossed_down and positions:
            return [{
                'direction': 'close',
                'ticket':    positions[0]['ticket'],
                'size':      1.0,
                'reason':    'EMA crossover down',
            }]

        return []

    def teardown(self):
        pass
```

Run it:
```bash
cargo run -p observa-cli -- run \
  --strategy strategies/ema_crossover.py \
  --data data/EURUSD_M15.csv
```

### RSI Mean Reversion (`strategies/rsi_strategy.py`)

Buys when RSI drops below 30 (oversold).
Closes when RSI rises above 70 (overbought).

```python
class RSIStrategy:

    def initialize(self, params=None):
        self.period     = 14
        self.prev_close = None
        self.avg_gain   = None
        self.avg_loss   = None
        self.gains      = []
        self.losses     = []

    def _rsi(self, close):
        if self.prev_close is None:
            self.prev_close = close
            return None

        change = close - self.prev_close
        self.prev_close = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self.avg_gain is None:
            self.gains.append(gain)
            self.losses.append(loss)
            if len(self.gains) < self.period:
                return None
            self.avg_gain = sum(self.gains) / self.period
            self.avg_loss = sum(self.losses) / self.period
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) \
                            / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) \
                            / self.period

        if self.avg_loss == 0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar, portfolio, history):
        rsi = self._rsi(bar['close'])
        if rsi is None:
            return []

        positions = portfolio['open_positions']

        # Oversold — buy signal
        if rsi < 30 and not portfolio['has_open_position']:
            return [{
                'direction': 'buy',
                'size':      1.0,
                'sl':        bar['close'] - 0.0030,
                'tp':        bar['close'] + 0.0060,
                'reason':    f'RSI oversold: {rsi:.1f}',
            }]

        # Overbought — close signal
        if rsi > 70 and positions:
            return [{
                'direction': 'close',
                'ticket':    positions[0]['ticket'],
                'size':      1.0,
                'reason':    f'RSI overbought: {rsi:.1f}',
            }]

        return []

    def teardown(self):
        pass
```

Run it:
```bash
cargo run -p observa-cli -- run \
  --strategy strategies/rsi_strategy.py \
  --data data/EURUSD_M15.csv
```

### FVG Strategy (`strategies/fvg_strategy.py`)

Detects Fair Value Gaps and draws them on the chart.
Demonstrates the custom drawings API.

```python
class FVGStrategy:

    def initialize(self, params=None):
        self.fvg_count = 0

    def on_bar(self, bar, portfolio, history):
        if len(history) < 2:
            return {'signals': [], 'drawings': []}

        c1 = history[-2]
        c3 = bar
        drawings = []
        signals  = []

        # Bullish FVG — gap between candle 1 low and candle 3 high
        if c3['low'] > c1['high']:
            self.fvg_count += 1
            drawings.append({
                'id':         f'bull_fvg_{self.fvg_count}',
                'type':       'rectangle',
                'time_start': c1['timestamp'],
                'time_end':   None,
                'price_top':  c3['low'],
                'price_bot':  c1['high'],
                'color':      '#3fb95033',
                'border':     '#3fb950',
                'persist':    'until_filled',
                'fill_price': c1['high'],
            })
            if not portfolio['has_open_position']:
                signals.append({
                    'direction': 'buy',
                    'size':      1.0,
                    'sl':        c1['low'] - 0.001,
                    'tp':        c3['high'] + 0.003,
                    'reason':    'Bullish FVG',
                })

        # Bearish FVG — gap between candle 1 high and candle 3 low
        if c3['high'] < c1['low']:
            self.fvg_count += 1
            drawings.append({
                'id':         f'bear_fvg_{self.fvg_count}',
                'type':       'rectangle',
                'time_start': c1['timestamp'],
                'time_end':   None,
                'price_top':  c1['low'],
                'price_bot':  c3['high'],
                'color':      '#f8514933',
                'border':     '#f85149',
            })

        return {'signals': signals, 'drawings': drawings}

    def teardown(self):
        print(f'Detected {self.fvg_count} FVGs')
```

---

## CLI Reference

```
USAGE:
    observa init
    observa run --strategy <file.py> --data <file.csv> [OPTIONS]

COMMANDS:
    init     Generate a default config.yaml in the current directory
    run      Run a backtest and open the visual replay

REQUIRED (run):
    --strategy, -s <path>   Python strategy file
    --data,     -d <path>   CSV data file (OHLCV format)

OPTIONAL (run):
    --config,   -c <path>   Config file path (default: config.yaml)
    --class        <name>   Strategy class name (auto-detected if omitted)
    --port,     -p <port>   Visualization server port (default: 7878)
    --help,     -h          Show this message
```

---

## Architecture

Observa is built on an event-sourced architecture. Every meaningful action
emits an immutable event. The event log is the source of truth.

```
CSV Data
  ↓
Replay Engine (Rust)
  ↓ BarReceivedEvent
Event Bus
  ├→ Strategy Sandbox (Python via PyO3)
  │    ↓ SignalEmittedEvent
  ├→ Execution Model (spread, slippage, commission)
  │    ↓ OrderFilledEvent
  ├→ Portfolio Manager (positions, PnL)
  │    ↓ PositionOpenedEvent / PositionClosedEvent
  ├→ Metrics Engine (Sharpe, drawdown, win rate)
  └→ Visualization (browser chart)
```

**The four hard rules:**
1. Strategy never places orders directly — it emits signals
2. Visualization never computes truth — it subscribes to events
3. Execution model is the only place realism is applied
4. Every state change emits an event

### Crate structure

```
observa-core      — Bar, all event types, shared enums, instrument specs
observa-data      — CSV reader, validation
observa-engine    — Event Bus, Strategy trait, replay loop
observa-execution — Fill simulation, spread/slippage/commission
observa-portfolio — Positions, capital, PnL tracking
observa-metrics   — Drawdown, Sharpe, Calmar, win rate
observa-python    — PyO3 bridge, loads Python strategies
observa-cli       — CLI binary, argument parsing, HTTP server
```

---

## Problem Statement

Algorithmic trading strategies fail in live markets for two reasons that
are almost never caught during backtesting: silent logic errors in code,
and unrealistic simulation assumptions.

Current backtesting tools produce a result — a return figure, a Sharpe
ratio, an equity curve — but offer little to no way of verifying that the
strategy behaved correctly to produce that result. A trader has no way of
seeing, bar by bar, whether entries fired at the right moment, whether
indicators were calculated correctly, or whether exit logic triggered as
intended. The code either runs or it doesn't. The number either looks good
or it doesn't. There is no middle ground where a trader can observe the
strategy thinking.

This creates a dangerous illusion of validation.

## Why Current Tools Fail

The failure isn't accidental — it reflects a fundamental assumption baked
into every major backtesting platform: that the output is the truth, and
the process that generated it is a black box the trader should trust.

MT5 offers visual replay, but locks traders into MQL5 — a C-like language
hostile to most traders, painful to write custom plots in, and entirely
platform-dependent. A strategy built in MQL5 cannot easily transfer to a
broker outside the MT5 ecosystem. The majority of algorithmic traders work
in Python. MT5 simply doesn't serve them.

Python-native tools like Backtrader and QuantConnect offer flexibility but
treat visualization as an afterthought, or exclude it entirely. A trader
running a backtest in these environments receives numbers. They do not see
their strategy execute. They cannot step through a losing trade and
understand why it lost.

The deeper failure is this: none of these tools are built around the idea
that seeing is understanding. They are calculators dressed up as research
platforms.

## The Truth This System Is Built to Reveal

Two things must be true for a strategy to be worth trading: the code must
do exactly what the trader intends, and it must remain viable when exposed
to real market conditions — spreads, slippage, commission, invalid stop
distances, partial fills.

Neither truth can be confirmed by looking at a number. They can only be
confirmed by watching.

This system exists to make strategy execution fully observable — bar by
bar, fill by fill, indicator by indicator — so a trader can see with their
own eyes whether their logic is sound, whether their intuition translated
correctly into code, and whether their strategy can survive contact with a
real market.

The goal is not a better backtest. The goal is the end of blind trust.

---

## Roadmap

- [x] Problem definition and invariants
- [x] Domain model and event taxonomy
- [x] Core engine (Rust)
- [x] Strategy interface (Python)
- [x] Python bridge (PyO3 — CLI)
- [x] Visual replay layer
- [x] Metrics (drawdown, Sharpe, Calmar, win rate)
- [x] Custom drawings API (FVGs, levels, annotations)
- [x] Multiple simultaneous positions
- [x] Instrument specifications (forex, stocks, crypto)
- [x] YAML configuration
- [ ] UI polish
- [ ] pip installable package
- [ ] Live data integration
- [ ] MVP release

---

## Contributing

Observa is early stage and welcomes contributors. The architecture docs
in `docs/` explain the design decisions in detail.

```
docs/
  DOMAIN_MODEL.md    — core concepts and definitions
  ARCHITECTURE.md    — system design and component boundaries
  MVP_SCOPE.md       — what is and isn't in the MVP
  STRATEGY_API.md    — strategy interface specification
  EVENT_SCHEMAS.md   — all event types and their fields
```

---

## License

MIT