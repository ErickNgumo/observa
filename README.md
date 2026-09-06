# Observa

> A visual backtesting engine that shows you *exactly what happened* in a
> backtest — every decision, order, fill, position close, SL/TP trigger, and
> balance change — replayed bar by bar from the canonical event history.

The goal is the end of blind trust: you inspect why a backtest behaved the
way it did, instead of only trusting final statistics.

## Install (private MVP wheel)

> ⚠️ **Do not `pip install observa`.** The public PyPI name `observa` is an
> unrelated project. This private MVP is distributed as a built wheel.

```bash
pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
```

Verified on Linux x86_64 (glibc ≥ 2.34) with CPython 3.13. Windows, macOS and
Colab are not runtime-verified for this build.

Verify you imported *this* Observa (not the unrelated PyPI package):

```python
import observa
print(observa.__version__)   # must print 0.1.0
print(observa.__file__)      # must point into this wheel's site-packages
```

## Run your first backtest (≈2 minutes)

```python
import observa
from observa.samples.sample_strategy import SampleEma

data = observa.sample_data_path()          # bundled deterministic sample
config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    dataset_source=data,                    # records the data path
)

result = observa.run(SampleEma(), data, config=config, output="runs/sample")

print(result.final_balance)
print(result.final_equity)
print(len(result.trades))
print(result.open_positions)
```

Or run the ready-made example (same thing, with prints and replay guidance):

```bash
python examples/quickstart.py
```

## Replay it

```bash
observa replay runs/sample
```

Open http://localhost:7878. The replay is a view of the canonical events —
fills, position pairing, SL/TP prices and account state all come from the
run's event log, never recomputed in the browser. The chart library is
bundled, so replay works offline.

## Use Observa with AI

You can give Observa's official AI guide to a coding agent and describe your
strategy in natural language:

```text
Use Observa to backtest an RSI mean-reversion strategy.

Read the official Observa agent guide:
[llms-full.txt in this repository]

Use Observa's canonical Engine.
Do not implement your own fills or P&L.
Run the backtest and give me the replay.
```

* Full agent guide: [`llms-full.txt`](llms-full.txt)
* Compact doc index: [`llms.txt`](llms.txt)
* Official copy-paste prompt: [`prompts/implement-strategy.md`](prompts/implement-strategy.md)
* AI starter project: [`examples/ai_starter/`](examples/ai_starter/)

## Examples

* [`examples/quickstart.py`](examples/quickstart.py) — copy-paste first run (bundled sample).
* [`examples/ema_yfinance.py`](examples/ema_yfinance.py) — real intraday data via `yfinance`.
* [`examples/rsi_mean_reversion.py`](examples/rsi_mean_reversion.py) — a second strategy pattern (RSI mean reversion).

Technical examples only — not financial advice.

## Documentation

* [Getting started](docs/getting-started.md)
* [Strategy contract](docs/strategy-contract.md)
* [Execution model & assumptions](docs/execution-model.md)
* [Data format](docs/data-format.md)
* [Known limitations](docs/known-limitations.md)
* [Architecture](docs/ARCHITECTURE.md)
* [Private MVP release notes](docs/mvp-release-notes.md)

## Status

Private MVP tester build. Not production-ready. See
[`docs/known-limitations.md`](docs/known-limitations.md).

## Development (contributors)

Rust workspace under `crates/`, Python package under `python/`, replay
frontend under `python/observa/static/`. End users need only Python; maintainers need Rust.

```bash
cargo test --workspace
cargo build --workspace
node python/tests/replay.test.js
```
