# Observa — Getting Started

This is the first-run path: install Observa once, run the included real EUR/USD
example, replay it, and inspect what happened.

No Rust toolchain, no repository checkout, no data download.

## 1. Install

> ⚠️ **Do not `pip install observa`.** The public PyPI name `observa` is an
> unrelated project.

Install the wheel from the official GitHub Release:

```bash
python -m pip install "<OFFICIAL_OBSERVA_WHEEL_URL>"
```

The exact URL is on the
[Releases page](https://github.com/ErickNgumo/observa/releases) — copy the
newest `observa-*.whl` link.

That is the complete installation. It includes everything Observa offers:

- the Python API
- `observa replay`
- `observa validate-strategy`
- `observa mcp`

There are no extras to choose between and no second install step.

Verify you imported *this* Observa (and not the unrelated PyPI package):

```python
import observa
print(observa.__version__)   # e.g. 0.1.4
print(observa.__file__)      # must point into this wheel's site-packages
```

**Notebook users:** if Observa was installed or replaced while a Jupyter /
VS Code kernel was already running, restart the kernel before `import observa`.

**Platform:** verified on Linux x86_64, CPython 3.10+ (the wheel is `abi3` and
`manylinux_2_34`). Windows, macOS and Google Colab are not runtime-verified.

## 2. Run the EUR/USD example

The wheel ships a fixed sample of **real EUR/USD 15-minute data** (600 bars)
and a simple EMA crossover strategy, so this works offline with no extra
libraries:

```bash
python examples/eurusd_demo.py
```

The same thing in Python:

```python
import observa
from observa.samples import EmaCrossover

data = observa.demo_data_path()          # bundled real EUR/USD

result = observa.run(
    EmaCrossover(),
    data,
    config=observa.Config(dataset_source=data, interval="15m"),
    output="runs/eurusd-demo",
)

print(result.summary())
```

Either way the run is saved to `runs/eurusd-demo`.

> `dataset_source=data` is what lets the replay draw the price candles later.
> Without it the run still works, but replay has no candles to show.

Where the demo data came from, and what it contains:
[demo dataset](demo-dataset.md).

## 3. Replay it

```bash
observa replay runs/eurusd-demo
```

Open the printed local URL. You can step through the backtest bar by bar and see
the candles, the fast and slow EMA, each strategy decision, entries and exits,
the trade markers, account state, trade history and final metrics.

Replay is reading the **saved** run. It is not running a second backtest in the
browser.

If you prefer a quick machine-readable summary instead:

```bash
python -c "import observa; print(observa.run_summary('runs/eurusd-demo'))"
```

## 4. Inspect the run from Python

```python
import observa

run = observa.inspect_run("runs/eurusd-demo")

run.meta, run.metrics      # the run's own saved summary and metrics
run.trades()               # completed trades
run.positions(open=None)   # every position, or open=True / open=False
run.rejections()           # orders the engine rejected, and its reason
run.bar(100)               # everything recorded on one bar

trades = run.trades()
pid = trades[0]["position_id"]   # a real position id from this run
run.position(pid)                # one position's full life: entry, exit, orders
```

This is the way to analyse a backtest programmatically instead of looking at
the chart. Full reference: [inspection & strategy API](STRATEGY_API.md).

## 5. Validate a strategy before running it

```bash
observa validate-strategy strategy.py --json
observa validate-strategy strategy.py --smoke --json
```

Exit `0` means valid, `1` means the reported errors tell you what to fix, and
`2` means a usage or setup problem.

> ⚠️ **Security:** validation is not a sandbox. It imports the strategy module,
> and `--smoke` executes `on_bar()`. Only validate code you trust.

## 6. Next steps

**Write your own strategy.** A strategy is a Python class with `initialize`,
`on_bar` and `teardown`; `on_bar` returns the signals it wants. Start with the
gold example and the short guide:
[writing a strategy for Observa](agent/strategy-authoring.md) ·
[strategy reference](strategy-contract.md).

**Let an AI write one.** Observa ships its strategy instructions, a working
example and a machine-readable description of the rules inside the installed
package, so a coding agent can learn the format instead of guessing. Validate
anything it produces with `observa validate-strategy`.

**Connect an AI with MCP.** MCP lets supported AI tools inspect your saved
backtests directly. It is already installed — see
[connecting an AI to Observa](MCP.md).

## 7. Using your own data

Observa accepts an OHLCV CSV, a list of bar dicts, or a DataFrame-like object:

```python
import observa

# replace MyStrategy() and the CSV path with your own
result = observa.run(
    MyStrategy(),
    "my_data.csv",
    config=observa.Config(dataset_source="my_data.csv", interval="1h"),
    output="runs/my-run",
)
```

Requirements (columns, timestamps, ordering) are in
[data format](data-format.md).

## 8. Trading costs

Backtests depend on how orders are simulated. Costs are applied to the
simulated trades as they happen:

```python
# a fragment to add to the run above
config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,   # or observa.BAR_CLOSE
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,                    # per round trip
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    dataset_source=data,
)
```

Fill modes, spread, slippage, SL/TP evaluation and margin:
[execution model](execution-model.md).

## If something goes wrong

- `RUN_DIR_NOT_FOUND` — the run directory or dataset path is wrong, or the run
  was never persisted with `output=`.
- A rejected order is **not** an exception: it is recorded in the run. Read
  `run.rejections()`.
- Replay shows no candles — the run was created without
  `config=Config(dataset_source=...)`.

Error codes and their meanings: [inspection & strategy API](STRATEGY_API.md).

## More

- [Connect an AI to Observa (MCP)](MCP.md)
- [Execution model & assumptions](execution-model.md)
- [Known limitations](known-limitations.md)
- [`llms-full.txt`](../llms-full.txt) — the complete technical guide
- [Architecture](ARCHITECTURE.md) — contributors and the curious
