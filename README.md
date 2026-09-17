# Observa

> A visual backtesting engine that shows you *exactly what happened* in a
> backtest — every decision, order, fill, position close, SL/TP trigger, and
> balance change — replayed bar by bar from the canonical event history.

The goal is the end of blind trust: you inspect why a backtest behaved the
way it did, instead of only trusting final statistics.

## Install

> ⚠️ Do **not** `pip install observa`. The public PyPI name `observa` is an
> unrelated project.
>
> 📦 **Private-MVP distribution:** Observa 0.1.1 is distributed as an official
> wheel attached to the private-MVP GitHub Release. Install it with the URL
> below. Building a wheel yourself is a contributor task, not a user task
> (see Development below).

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.1-private-mvp/observa-0.1.1-cp310-abi3-manylinux_2_34_x86_64.whl"
```

SHA-256: `9cb10ee386c41b6b8fe5b0ba553894d4a7ff3cafb74ff69b83ae0d3a65a26cf8`

For real-data examples, also install:

```bash
python -m pip install yfinance pandas
```

**Notebook users:** if Observa was installed or replaced while a
Jupyter/VS Code notebook kernel was already running, **restart the kernel**
before `import observa` (an old kernel can still hold the unrelated PyPI
"observa" module in memory).

Verify you imported *this* Observa:

```python
import observa

print(observa.__version__)                      # must print 0.1.1
print(observa.__file__)                         # .../site-packages/observa/__init__.py
print(hasattr(observa, "Config"), hasattr(observa, "run"))  # True True
```

## Quickstart A — bundled deterministic sample (no data download)

Run the bundled example (copy, paste, run):

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
    dataset_source=data,                    # absolute path (replay candles)
)

result = observa.run(SampleEma(), data, config=config, output="runs/sample")

print(result.final_balance)
print(result.final_equity)
print(len(result.trades))
print(result.open_positions)
print(result.summary())       # machine-readable dict, no arrays duplicated
```

`result.summary()` returns one JSON-serializable dict with `status`,
`artifact_dir`, `total_bars`, `trades`, `open_positions`, `final_balance`,
`final_equity`, `events`, `metrics`, `dataset_source`, and
`run_schema_version` — convenient for agents and notebooks that should not
walk the full event/order arrays.

Or the ready-made file:

```bash
python examples/quickstart.py
```

## Quickstart B — real EUR/USD data (one self-contained file)

Get the complete example file one of two repo-free ways:

* **copy it from the docs** — the full file is embedded in
  [Getting Started → Quickstart B](docs/getting-started.md) (save it as
  `ema_observa.py`), or
* **download it from the GitHub Release** — `ema_observa.py` is attached to
  the same private-MVP Release as the wheel.

Then:

```bash
python -m pip install yfinance pandas
python ema_observa.py
```

`ema_observa.py` is a single file that: downloads intraday EUR/USD via
yfinance, normalizes the columns to Observa's CSV format, validates them,
saves the CSV to an absolute path, runs an EMA crossover, persists the run to
a unique (timestamped) run directory, prints results, and prints the replay
command. No repository, wheel paths, `importlib`, Rust, or Maturin needed.

## Replay it

Running a backtest and launching replay are **two separate actions**. After a
run is saved, start the replay with:

```bash
observa replay runs/<run-directory>
```

The CLI picks a free port automatically and prints the URL it bound, for
example `http://127.0.0.1:42689`. Pass `--port N` to require a specific port;
if it is already in use the command prints a one-line error and exits `2`.
Replay never opens a browser for you.

From a script, notebook, or coding agent, use the same programmatic entry
point:

```python
import observa

# Run once and persist it (replay only needs the run artifacts).
result = observa.run(MyStrategy(), data, config=config, output="runs/ema")

# Cheap machine-readable result summary (no array walking).
summary = result.summary()
print(summary["status"], summary["trades"], summary["final_balance"])

# Serve the run without blocking, then shut it down.
server = observa.replay(result, block=False)
print(server.url)          # e.g. http://127.0.0.1:42689
server.stop()              # idempotent

# Serving an already-persisted run directory works too.
server = observa.replay("runs/ema", block=False)
server.stop()
```

Key points:

* `observa.replay(run_dir_or_result, port=None, block=True, open_browser=False)`
  is the one canonical replay entry point.
* `port=None` (default) binds port `0` and lets the OS choose a free port, so
  concurrent replay servers never collide.
* An explicit `port` is strict: if it is taken, replay raises `OSError` with
  `exc.code == "REPLAY_PORT_IN_USE"` and `exc.details["port"]`.
* The run must be persisted (`output=` on `observa.run(...)` or
  `result.save(dir)`); an in-memory result raises `ValueError` with
  `exc.code == "REPLAY_RUN_NOT_PERSISTED"`.

Then open the printed URL in a browser. Replay is a view of the
canonical events — fills, position pairing, SL/TP prices and account state
all come from the run's event log, never recomputed in the browser. The chart
library is bundled, so replay works offline.

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

* [`examples/quickstart.py`](examples/quickstart.py) — Quickstart A (bundled sample).
* [`examples/ema_observa.py`](examples/ema_observa.py) — Quickstart B (real EUR/USD via yfinance, one file).
* [`examples/rsi_mean_reversion.py`](examples/rsi_mean_reversion.py) — RSI mean-reversion pattern.

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

Private MVP tester build. Not production-ready. Distribution is via the
official private-MVP GitHub Release (install URL in the Install section).
See [`docs/known-limitations.md`](docs/known-limitations.md).

## Development (contributors — not end users)

Building Observa yourself requires Rust, Cargo and Maturin:

```bash
python -m pip install maturin
cd python && maturin build --release   # wheel in python/target/wheels/
```

End users never need these. Repository layout: Rust workspace under
`crates/`, Python package under `python/`, replay frontend under
`python/observa/static/`.

```bash
cargo test --workspace
cargo build --workspace
node python/tests/replay.test.js
```
