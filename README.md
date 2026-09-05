# Observa

> A visual backtesting engine for algorithmic traders who need to *see* their
> strategy execute — not just trust the numbers.

Observa runs a backtest once, records the **canonical ordered event history**
of exactly what happened (what the strategy saw, which orders were created,
when they filled, which exact position closed, why SL/TP fired, and what
happened to balance and equity), and lets you replay that history bar by bar.

**The goal is the end of blind trust.** The visualizer is a view of the
canonical event log; it never recomputes fills, P&L, or position pairing.

## What's inside

* Canonical Rust Engine (one replay loop) with a deterministic execution and
  portfolio model.
* Python API backed by that same Engine.
* Persisted runs: `run.json` (what produced the run), `events.jsonl`
  (authoritative history), `metrics.json` (derived statistics).
* Bar-by-bar visual replay derived from canonical events (multi-position,
  exact close pairing, SL/TP/gap execution prices shown as executed).
* CLI (`observa run …`, `observa replay --dir …`) and installed-package
  replay (`observa replay …` after `pip install`).

## Install

```bash
pip install observa
```

**Verified:** Linux x86_64, CPython 3.13. The wheel is `abi3`
(Python >= 3.10) and `manylinux_2_34`. Windows/macOS/Colab are not
runtime-verified. No Rust toolchain is required to use the installed package.

```python
import observa
print(observa.__version__)
```

## First backtest

The package ships a deterministic sample dataset and a small strategy:

```python
import importlib.util
import observa

data = observa.sample_data_path()
spec = importlib.util.spec_from_file_location("sample", observa.sample_strategy_path())
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

config = observa.Config(fill_mode=observa.NEXT_BAR_OPEN, spread=0.0002,
                        slippage=0.0001, commission=7.0,
                        commission_mode=observa.ROUND_TRIP, interval="15m")

result = observa.run(mod.SampleEma(), data, config=config, output="runs/example")
print(result.final_balance, result.final_equity)
```

## Replay it

```bash
observa replay runs/example        # after pip install
# or, from the source tree:  observa replay --dir runs/example   (workspace CLI)
```

Open http://localhost:7878. The chart library is bundled, so replay works
offline.

## Documentation

* [Getting started](docs/getting-started.md)
* [Strategy contract](docs/strategy-contract.md)
* [Execution model & assumptions](docs/execution-model.md)
* [Data format](docs/data-format.md)
* [Known limitations](docs/known-limitations.md)
* [Architecture](docs/ARCHITECTURE.md)

## Status

MVP release candidate. Active development.

## Development (contributors)

Rust workspace crates under `crates/`, Python package under `python/`, replay
frontend under `python/observa/static/`. Contributors need Rust + Python; end
users need only Python.

```bash
cargo test --workspace
cargo build --workspace
node python/tests/replay.test.js
```
