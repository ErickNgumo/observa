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
> 📦 **Private-MVP distribution:** Observa 0.1.3 is distributed as an official
> wheel attached to the private-MVP GitHub Release. Install it with the URL
> below. Building a wheel yourself is a contributor task, not a user task
> (see Development below).

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl"
```

SHA-256: `e92feed284d2fcba84455b6c4d4ef84fe02f641da7d35de5652ceb5592216534`

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

print(observa.__version__)                      # must print 0.1.3
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

## Inspect a persisted run programmatically

`observa.inspect_run(dir)` answers structured questions about a saved run
**without re-running the engine** — no strategy code, no parsing `events.jsonl`
by hand. It reads only the persisted artifacts and never recomputes economics:

```python
import observa

run = observa.inspect_run("runs/sample")

run.meta, run.metrics                  # persisted run.json / metrics.json
run.trades()                           # completed canonical trades
run.positions(open=None)               # None = all, True = open, False = closed

pid = run.trades()[0]["position_id"]
run.position(pid)                      # lifecycle: opened/closed/order/annotations
run.position(pid)["events"]            # every canonical event for that position

run.order(17)                          # one order's lifecycle
run.rejections()                       # rejected orders + why (verbatim)
run.bar(421)                           # everything canonical on that bar
run.events(event_type="order_filled", bar_index=421)

run.event(254)                         # one event by event_seq
```

Guarantees: canonical `event_seq` ordering everywhere; `bar_index` queries use
canonical chronology buckets (so `events(bar_index=n) == bar(n)["events"]`);
results are plain JSON-serializable dicts; a failed run inspects fine
(`metrics is None`); OHLC is only returned when it still matches the persisted
dataset hash. Unknown ids raise `KeyError` with `exc.code` of
`EVENT_NOT_FOUND` / `BAR_NOT_FOUND` / `POSITION_NOT_FOUND` / `ORDER_NOT_FOUND`.

The strategy's own per-signal `reason` is persisted on the canonical
`strategy_decision` event, so a saved run can be inspected for *why* a strategy
acted:

```python
run.bar(421)["strategy_decisions"][0]["signals"]
# [{'signal_index': 0, 'reason': 'price crossed above VWAP'}]
```

Reasons are optional, per signal, at most 1024 UTF-8 bytes, preserved exactly as
authored, and never influence execution. Runs produced before this schema simply
have no `signals` key.

Every explicit ticket close is also linked to its exact order: `position_closed`
carries the canonical `order_seq` of the order that closed the position, so
`run.position(pid)["closing_order"]` returns that order's full lifecycle and
`run.order(seq)["position_id"]` points back at the position. A closing order is
recorded whenever one exists — protective SL/TP exits have no closing order in
the current execution model, and runs produced before this linkage was
persisted report `None` rather than guessing.

## Writing a strategy with an AI agent

The strategy authoring contract ships **inside the wheel**, so an agent working
in a fresh environment with no repository checkout can discover it directly:

```python
import observa
observa.agent_spec()          # canonical machine-readable contract (dict)
observa.agent_spec_path()     # bundled spec.json
observa.agent_guide_path()    # short authoring guide
observa.agent_example_path()  # gold example to imitate
```

```bash
observa agent-spec --json                        # same contract, on stdout
observa validate-strategy strategy.py --json     # structured, repairable errors
observa validate-strategy strategy.py --smoke    # + 6 deterministic bars
```

`validate-strategy` exits `0` valid, `1` invalid strategy, `2` usage/setup
error, and reports problems as coded entries (`SIGNAL_FIELD_UNKNOWN`,
`STRATEGY_RETURN_INVALID`, `CLOSE_TICKET_REQUIRED`, …) that a model can repair
without a human explaining Observa syntax. See
[`docs/agent/strategy-authoring.md`](docs/agent/strategy-authoring.md) and
[`examples/ai_starter/`](examples/ai_starter/).

## Inspect a persisted run over MCP

Observa ships a **read-only MCP server** so an external agent can interrogate
saved runs without learning the artifact formats. It is a thin adapter over
`observa.inspect_run(...)` and `observa.run_summary(...)`: it never runs a
strategy, never writes to a run directory, and never infers anything.

MCP support is an **optional extra**, so the base package stays
dependency-free. Install it **from the 0.1.3 wheel** — the extra attaches to
the wheel reference:

```bash
# base wheel (core only, still zero-dependency):
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl"

# same wheel + the official MCP SDK (append [mcp] to the wheel reference):
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"

# or, from a wheel you downloaded locally:
python -m pip install "./observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"
```

> ⚠️ Do **not** run bare `pip install "observa[mcp]"`. That resolves the
> unrelated PyPI project named `observa`, not this wheel.

Start it over **stdio** (the transport MCP clients launch locally):

```bash
observa mcp --runs-dir runs/
# equivalently:
python -m observa.mcp_server --runs-dir runs/
```

The server is scoped to one runs root; runs are addressed by their path
relative to it. Ten read-only tools are exposed: `list_runs`,
`get_run_summary`, `list_events`, `get_event`, `get_bar`, `list_positions`,
`get_position`, `get_order`, `list_trades`, `list_rejections`.

```jsonc
// generic MCP client configuration (stdio)
{ "command": "observa", "args": ["mcp", "--runs-dir", "/abs/path/to/runs"] }
```

Answers that come back are canonical evidence, e.g.
`get_position(pid)["closing_order"]` for "which order closed this position?",
or `list_events(bar_index=n, event_type="strategy_decision")` for the recorded
per-signal reason. All human-facing output goes to stderr, so stdout carries
only protocol traffic. Full reference, security model and client setup:
[`docs/MCP.md`](docs/MCP.md).

## Show the strategy's reasoning

`on_bar` may return annotations next to signals, and replay renders them over
the candles so a human can see **what the strategy was looking at** — without
reading the code:

```python
def on_bar(self, bar, portfolio, history):
    return {
        "signals": [...],
        "drawings": [
            {"id": "ema_20", "type": "series", "value": ema20,
             "color": "#58a6ff", "label": "EMA 20"},
            {"id": "zone_1", "type": "rectangle", "time_start": bar["timestamp"],
             "time_end": None, "price_top": high, "price_bot": low,
             "color": "#3fb950", "opacity": 0.14, "label": "FVG"},
            {"id": "poc", "type": "hline", "price": poc, "color": "#d29922", "label": "POC"},
        ],
    }
```

Series (EMA, VWAP, z-score, spread), levels, zones, regions, markers and
labels are supported. Annotations are descriptive only — they never affect
fills, P&L or execution. Use the **Annotations** button in replay to show or
hide them. A malformed drawing fails the run with a coded error (`exc.code`)
instead of disappearing. Full contract: [`docs/STRATEGY_API.md`](docs/STRATEGY_API.md).

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
