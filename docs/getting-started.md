# Observa — Getting Started

This is the single canonical first-run path: install the Python package, run a
backtest with the bundled sample data and strategy, inspect the result, and
open the visual replay — without a Rust toolchain or a repository checkout.

## 1. Install (official private-MVP wheel)

> ⚠️ **Do not `pip install observa`.** The public PyPI name `observa` is an
> unrelated project. Observa 0.1.4 is distributed as an official wheel
> attached to the private-MVP GitHub Release (URL below).

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.4-private-mvp/observa-0.1.4-cp310-abi3-manylinux_2_34_x86_64.whl"
```

That is the complete installation. It includes everything Observa offers —
the Python API, `observa replay`, `observa validate-strategy` and
`observa mcp`. There are no extras to choose between and no second install
step; you should never need to type `observa[...]`.

SHA-256: `PENDING`

For the real-data example also: `python -m pip install yfinance pandas`.

**Notebook users:** if Observa was installed or replaced while a
Jupyter/VS Code notebook kernel was already running, **restart the kernel**
before `import observa` (a running kernel may still hold the unrelated PyPI
"observa" module in memory).

Building the wheel yourself is a contributor task (requires Rust + Maturin);
end users never need that. See `docs/mvp-release-notes.md` for the
contributor build commands.

**Verified:** Linux x86_64, CPython 3.13. The wheel is `abi3` (Python >= 3.10
metadata) and `manylinux_2_34`. Windows/macOS/Colab are not runtime-verified.

Import test — verify you imported *this* Observa:

```python
import observa
print(observa.__version__)   # must print 0.1.4
print(observa.__file__)      # must point into this wheel's site-packages
print(hasattr(observa, "Config"), hasattr(observa, "run"))  # True True
```

## 2. Bundled sample assets

The wheel ships a deterministic, clearly synthetic sample dataset and a small
strategy (a technical example — not financial advice):

```python
data_file = observa.sample_data_path()          # sample CSV (200 x M15 bars)
strategy_file = observa.sample_strategy_path()  # SampleEma strategy module
```

It also ships a **real** EUR/USD 15-minute series (600 bars, sourced once from
Yahoo Finance) with its own demo strategy. Reading it needs no network, no
`yfinance` and no `pandas`:

```python
from observa.samples import EmaCrossover

demo_file = observa.demo_data_path()   # real EUR/USD M15 (bundled)
```

The synthetic sample above stays the deterministic fixture used by the tests
and the regression baseline. See [demo-dataset.md](demo-dataset.md) for
provenance and `examples/eurusd_demo.py` for a complete offline run.

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

Running a backtest and launching replay are **two separate actions**. Replay
a saved run with the installed package (no repository needed):

```bash
observa replay runs/example
```

The CLI binds a free port automatically and prints the exact URL it bound
(for example `http://127.0.0.1:42689`). Pass `--port 7878` to require a
specific port; if that port is already in use the command prints a one-line
error and exits with code `2`. Replay never opens a browser automatically.

From Python (scripts, notebooks, coding agents) the same entry point is:

```python
import observa

server = observa.replay("runs/example", block=False)   # returns immediately
print(server.url)          # actual bound URL, e.g. http://127.0.0.1:42689
print(server.port)         # actual bound port
print(server.run_dir)      # resolved run directory
server.stop()              # idempotent; also works as a context manager

with observa.replay("runs/example", block=False) as server:
    ...

observa.replay("runs/example")                         # block=True default
server = observa.replay(result, block=False)           # persisted RunResult
```

* `port=None` (the default) binds port `0`, so the operating system picks a
  free port and two replay servers can never race for the same port.
* An explicit `port` is strict. On collision replay raises `OSError` with
  `exc.code == "REPLAY_PORT_IN_USE"` and `exc.details["port"]`; it never
  silently falls back to another port.
* A `RunResult` is accepted only after it is persisted (`output=` on
  `observa.run(...)`, or `result.save(dir)`). An in-memory result raises
  `ValueError` with `exc.code == "REPLAY_RUN_NOT_PERSISTED"`.

Open the printed URL in a browser. Replay is a view of the canonical events —
it never recomputes fills, P&L, or position pairing. The chart library is
bundled in the wheel, so replay works offline.

### Reading a run without replay

```python
result.summary()            # dict for the live result object
observa.run_summary("runs/example")   # dict/status from run.json + metrics.json
```

`result.summary()` returns exactly: `status`, `artifact_dir`, `total_bars`,
`trades`, `open_positions`, `final_balance`, `final_equity`, `events`,
`metrics`, `dataset_source`, `run_schema_version`. `observa.run_summary(dir)`
reads only the persisted `run.json`/`metrics.json`, so it also works for runs
produced by another process — including failed runs, whose summary reports
`status="failed"` with the recorded `error`.

### Error codes for agents

Observa raises the ordinary built-in exception classes but attaches
machine-readable attributes instead of requiring message parsing:

```python
try:
    observa.replay(run_dir, port=7878)
except OSError as exc:
    print(exc.code)        # "REPLAY_PORT_IN_USE"
    print(exc.details)     # {"port": 7878}
    print(observa.error_code(exc))   # same string, works for any exception
```

Replay and CLI failures always include a code. Order rejections are **not**
exceptions at all — an invalid SL/TP, an oversized quantity, or insufficient
margin produces a canonical `order_rejected` event in `result.events` and the
run completes.

## 8. Quickstart B — real EUR/USD data

> **Offline alternative.** This quickstart downloads live EUR/USD with
> `yfinance` (needs `python -m pip install yfinance pandas`). If you just want
> real market data in replay with no download at all, use the bundled demo:
> `observa.demo_data_path()` with `observa.samples.EmaCrossover` — see
> section 2 and `examples/eurusd_demo.py`.

One complete, copy-paste runnable example. Copy the file below into a file named `ema_observa.py` (the same file is also attached to the private-MVP GitHub Release as an asset, and maintained at `examples/ema_observa.py` in the repository), then run:

```bash
python -m pip install yfinance pandas
python ema_observa.py
```

`ema_observa.py`:

```python
"""Canonical real-data onboarding example — single self-contained file.

Quickstart B (real data): downloads intraday EUR/USD with yfinance, normalizes
it to Observa's CSV format, runs an EMA crossover, persists the run, and
prints the replay command. Everything is in this one file.

Setup (external dependency, only needed for real data):

    python -m pip install yfinance pandas

Then run from a fresh directory:

    python ema_observa.py

Then start replay:

    observa replay runs/ema_observa_<timestamp>

Notes
-----
* yfinance data availability/quality are NOT guaranteed (network/rate limits
  happen). If the download fails, the script explains what to do.
* The dataset is saved to an ABSOLUTE path recorded as dataset_source so
  replay can restore candles no matter where you run `observa replay`.
* Run directories are unique (timestamped) because Observa persistence is
  create-only: rerunning never overwrites a historical run.
* Technical example, not financial advice.
"""

import os
from datetime import datetime
from pathlib import Path

import observa


def download_eurusd(csv_path: Path) -> int:
    try:
        import pandas as pd  # noqa: F401 (used for MultiIndex detection)
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "This example needs:  python -m pip install yfinance pandas\n"
            "then re-run:         python ema_observa.py"
        ) from exc

    print("Downloading EUR/USD 15-minute data (yfinance ticker 'EURUSD=X')...")
    frame = yf.download("EURUSD=X", interval="15m", period="5d",
                        progress=False, auto_adjust=False)
    if frame is None or frame.empty:
        raise SystemExit(
            "yfinance returned no data right now (offline or rate-limited). "
            "Try later, or use the bundled sample with examples/quickstart.py."
        )
    if isinstance(frame.columns, pd.MultiIndex):  # flatten if present
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index().rename(columns={
        "Datetime": "timestamp", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    frame = frame[["timestamp", "open", "high", "low", "close", "volume"]]
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

    # Basic validation before saving (observa re-validates on load).
    assert frame["open"].notna().all() and frame["high"].notna().all()
    assert frame["low"].notna().all() and frame["close"].notna().all()

    frame.to_csv(csv_path, index=False)
    print("Saved %d bars to %s" % (len(frame), csv_path))
    return len(frame)


class EmaCrossover:
    """Fast/slow EMA crossover; closes positions by exact ticket."""

    def __init__(self):
        self.closes = []

    def initialize(self, params=None):
        params = params or {}
        self.fast = int(params.get("fast", 5))
        self.slow = int(params.get("slow", 20))
        self.closes = []

    def _ema(self, period):
        closes = self.closes
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = closes[0]
        for price in closes[1:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def on_bar(self, bar, portfolio, history):
        self.closes.append(bar["close"])
        fast = self._ema(self.fast)
        slow = self._ema(self.slow)
        if fast is None or slow is None:
            return []
        prev_fast = self._ema_prev(self.fast)
        prev_slow = self._ema_prev(self.slow)
        crossed_up = prev_fast is not None and prev_slow is not None \
            and prev_fast <= prev_slow and fast > slow
        crossed_down = prev_fast is not None and prev_slow is not None \
            and prev_fast >= prev_slow and fast < slow
        if crossed_up and not portfolio["has_open_position"]:
            return [{"direction": "buy", "size": 1.0,
                     "price": bar["close"], "reason": "fast EMA above slow"}]
        if crossed_down and portfolio["has_open_position"]:
            pos = portfolio["open_positions"][0]  # explicit ticket close
            return [{"direction": "close", "size": pos["size"],
                     "ticket": pos["position_id"], "reason": "fast EMA below slow"}]
        return []

    def _ema_prev(self, period):
        closes = self.closes[:-1]
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = closes[0]
        for price in closes[1:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def teardown(self):
        pass


def main() -> None:
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_file = Path("eurusd_m15.csv").resolve()       # absolute path
    run_dir = Path("runs") / ("ema_observa_" + run_tag)  # unique (create-only)

    download_eurusd(data_file)

    config = observa.Config(
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"fast": 5, "slow": 20},
        strategy_name="EmaCrossover",
        dataset_source=str(data_file),  # absolute, so replay restores candles
    )

    result = observa.run(EmaCrossover(), str(data_file), config=config,
                         output=str(run_dir))

    print()
    print("final balance:   %.2f" % result.final_balance)
    print("final equity:    %.2f" % result.final_equity)
    print("trades:          %d" % len(result.trades))
    print("open positions:  %d" % result.open_positions)
    print("events:          %d" % len(result.events))
    print()
    print("Run saved to:    %s" % run_dir)
    print("Replay with:     observa replay %s" % run_dir)
    print("Then open:       the URL printed by observa replay")


if __name__ == "__main__":
    main()
```

Start the replay with `observa replay runs/ema_observa_<timestamp>` and open the URL it prints
(it chooses a free port automatically; pass `--port N` to require a specific one).

## 9. Your own data

Data is an OHLCV CSV (`timestamp,open,high,low,close,volume`) — see
`docs/data-format.md`. A Python list of bar dicts and DataFrame-like objects
are also accepted.

## More

- `docs/strategy-contract.md` — the strategy lifecycle and order API.
- `docs/execution-model.md` — fill timing, SL/TP, gaps, spread/slippage,
  commission, margin, and assumptions.
- `docs/data-format.md` — CSV requirements.
- `docs/known-limitations.md` — honest release-candidate limitations.
