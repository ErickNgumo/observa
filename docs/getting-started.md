# Observa — Getting Started

This is the single canonical first-run path: install the Python package, run a
backtest with the bundled sample data and strategy, inspect the result, and
open the visual replay — without a Rust toolchain or a repository checkout.

## 1. Install (private MVP wheel)

> ⚠️ **Do not `pip install observa`.** The public PyPI name `observa` is an
> unrelated project. This private MVP is distributed as a built wheel, not
> from PyPI.

```bash
pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
```

**Verified:** Linux x86_64, CPython 3.13. The wheel is `abi3` (Python >= 3.10
metadata) and `manylinux_2_34`. Windows/macOS/Colab are not runtime-verified.

Import test — verify you imported *this* Observa:

```python
import observa
print(observa.__version__)   # must print 0.1.0
print(observa.__file__)      # must point into this wheel's site-packages
```

## 2. Bundled sample assets

The wheel ships a deterministic, clearly synthetic sample dataset and a small
strategy (a technical example — not financial advice):

```python
data_file = observa.sample_data_path()          # sample CSV (200 x M15 bars)
strategy_file = observa.sample_strategy_path()  # SampleEma strategy module
```

## 3. Write / load a strategy

A strategy is a plain Python class implementing the lifecycle
(`initialize` / `on_bar` / `teardown`). Load the bundled sample:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("sample", strategy_file)
strategy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strategy_module)
strategy = strategy_module.SampleEma()
```

See `docs/strategy-contract.md` for the full contract (signals, order types,
portfolio view).

## 4. Configure and run

```python
import observa

config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,   # or observa.BAR_CLOSE
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    params={"fast": 5, "slow": 20},
)

result = observa.run(strategy, data_file, config=config, output="runs/example")
```

`Config` fields are documented in `docs/execution-model.md`. `output=`
persists the canonical artifacts; without it the run still returns a result.

## 5. Inspect the result

```python
print(result.final_balance)
print(result.final_equity)
print(len(result.trades))      # closed trades
print(result.open_positions)
print(result.orders)           # canonical order lifecycle
print(result.fills)
print(result.events)           # canonical OBS-0008 event history
print(result.metrics)
```

## 6. Saved artifacts

`output="runs/example"` writes three files:

| file            | role                                        |
| --------------- | ------------------------------------------- |
| `run.json`      | what produced the run (config/identity)     |
| `events.jsonl`  | authoritative history (one event per line)  |
| `metrics.json`  | derived statistics (never authoritative)    |

## 7. Visual replay

Replay a saved run with the installed package (no repository needed):

```bash
observa replay runs/example
```

then open http://localhost:7878 in a browser. Replay is a view of the
canonical events — it never recomputes fills, P&L, or position pairing. The
chart library is bundled in the wheel, so replay works offline.

## 8. Your own data

Data is an OHLCV CSV (`timestamp,open,high,low,close,volume`) — see
`docs/data-format.md`. A Python list of bar dicts and DataFrame-like objects
are also accepted.

## More

- `docs/strategy-contract.md` — the strategy lifecycle and order API.
- `docs/execution-model.md` — fill timing, SL/TP, gaps, spread/slippage,
  commission, margin, and assumptions.
- `docs/data-format.md` — CSV requirements.
- `docs/known-limitations.md` — honest release-candidate limitations.
