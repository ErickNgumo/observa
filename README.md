# Observa

## Stop trusting your backtest. Inspect it.

Most backtesting tools give you a result. Observa shows you **how the result
happened** — every strategy decision, order, fill, position, stop/target event
and account change — from one canonical event history.

Think of it as a **debugger for trading strategies**.

<!-- TODO(UX visual): add a replay GIF/screenshot once an approved capture exists (none is checked in; do not fabricate one). -->

```
  your strategy
        |  signals (intent)
        v
  Observa Engine          <-- owns fills, spread, slippage, SL/TP, P&L
        |  canonical event history
        v
  persisted run           (run.json · events.jsonl · metrics.json)
        |
        +--> Replay    a human inspects it bar by bar
        +--> Python    inspect_run() answers structured questions
        +--> MCP       an AI agent inspects the same evidence
```

## What problem does this solve?

A backtest result is a claim. The questions you actually ask are:

* Why did this trade happen, and what was the strategy seeing?
* What price actually filled — and did spread or slippage move it?
* Why was this order rejected?
* Did the stop trigger where and when I expected?
* Which order closed this position?
* Why does this backtest make money at all?

Observa records the evidence needed to answer them, then lets you inspect it.

## Three ways to inspect the same run

| Surface | For | What it gives you |
| --- | --- | --- |
| `observa replay runs/sample` | a human | bar-by-bar replay in the browser |
| `observa.inspect_run("runs/sample")` | Python code | structured questions about a saved run |
| `observa mcp --runs-dir runs/` | an AI agent | the same evidence over MCP |

All three read the **same persisted run**, and none of them recomputes
economics: the browser does not recalculate P&L, the inspector does not re-run
your strategy, and MCP does not invent trade history.

## Use it with AI

Tell a coding agent what strategy you want. **Observa ships its strategy
contract, a short authoring guide and a canonical example inside the installed
package**, so the agent does not have to guess the API:

```python
import observa
observa.agent_spec()          # machine-readable contract (dict)
observa.agent_guide_path()    # short authoring guide
observa.agent_example_path()  # gold example to imitate
```

```bash
observa agent-spec --json                        # the same contract, on stdout
observa validate-strategy strategy.py --smoke --json
```

The agent understands your intent and writes the strategy code. Observa defines
the contract, validates the integration, executes deterministically and
persists the evidence — **Observa does not call an LLM and does not generate
strategies.**

> ⚠️ `validate-strategy` is not a sandbox: it imports the strategy module, and
> smoke validation executes `on_bar()`. Only validate strategy code you trust.

Details: [agent guide](docs/agent/strategy-authoring.md) · [AI starter](examples/ai_starter/) · [llms-full.txt](llms-full.txt)

## Try it

> ⚠️ Do **not** run `pip install observa`. The public PyPI name `observa` is an
> unrelated project. Install the official private-MVP wheel:

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.4-private-mvp/observa-0.1.4-cp310-abi3-manylinux_2_34_x86_64.whl"
```

Run the bundled deterministic sample — no data download, no Rust toolchain:

```python
import observa
from observa.samples.sample_strategy import SampleEma

data = observa.sample_data_path()

result = observa.run(
    SampleEma(),
    data,
    config=observa.Config(dataset_source=data, interval="15m"),
    output="runs/sample",          # create-only: use a new path to run again
)

print(result.summary())
```

`output=` is what persists the run (`run.json`, `events.jsonl`, `metrics.json`)
so it can be replayed and inspected. Everything in the run is produced by the
canonical Engine; your strategy only supplies intent.

## Replay it

```bash
observa replay runs/sample
```

Open the printed local URL and step through the run bar by bar: what the
strategy saw, what it ordered, what filled, and how each position closed. The
chart library is bundled, so replay works offline.

## Inspect it from Python

```python
import observa

run = observa.inspect_run("runs/sample")

run.meta, run.metrics             # the persisted run.json / metrics.json
observa.run_summary("runs/sample")  # one machine-readable summary dict

trades = run.trades()             # completed canonical trades
run.positions(open=None)          # all / open only / closed only
run.rejections()                  # rejected orders, with the engine's reason
run.bar(100)                      # everything canonical on one bar

pid = trades[0]["position_id"]    # a real position id from this run
position = run.position(pid)      # one position's full lifecycle
seq = position["closing_order"]["order_seq"]
run.order(seq)                    # one order, and the position it closed
```

Inspection reads only the persisted artifacts — it never re-runs the strategy
and never recomputes results. Full reference:
[inspection & strategy API](docs/STRATEGY_API.md).

## Inspect a run over MCP

MCP lets an external AI agent work with Observa through thirteen read-only
tools: ten for inspecting a persisted run, and three for discovering how to
write a strategy — the canonical contract, the gold example and the authoring
guide, exactly as they ship in the wheel. It is **stdio-only**, **read-only**,
and scoped to one local runs root. MCP is an optional extra on the **same
wheel**:

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.4-private-mvp/observa-0.1.4-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"
observa mcp --runs-dir runs/
```

The runs directory may be missing or empty, so you can connect an agent before
your first backtest. The authoring tools only hand back the contract and example
that already ship in the package — they do **not** generate strategies and do
**not** validate or run code; validation stays with
`observa validate-strategy`.

> ⚠️ Do **not** run bare `pip install "observa[mcp]"` — that resolves the
> unrelated PyPI project, not this wheel.

Tool reference, security model and client setup: [docs/MCP.md](docs/MCP.md).

## Why trust the result?

* One canonical Engine owns fills, pricing and economics — there is no second
  backtest loop in the browser, the inspector or MCP.
* Spread, slippage and commission are explicit settings, applied by the Engine
  and visible in the recorded fill.
* Positions close only by an explicit ticket — never an invented FIFO rule.
* Rejected orders are recorded as canonical events, with the engine's reason.
* A strategy can attach a `reason` to each signal and annotations to the chart,
  so the *why* is persisted alongside the evidence.
* Determinism is a requirement: identical inputs produce identical artifacts.
* Runs persisted by earlier versions remain inspectable.

## Examples

* [`examples/quickstart.py`](examples/quickstart.py) — bundled deterministic sample.
* [`examples/agent_example.py`](examples/agent_example.py) — the gold authoring example.
* [`examples/ai_starter/`](examples/ai_starter/) — starter project for a coding agent.
* [`examples/rsi_mean_reversion.py`](examples/rsi_mean_reversion.py) — RSI mean-reversion pattern.
* [`examples/ema_observa.py`](examples/ema_observa.py) — real EUR/USD in one file
  (needs `python -m pip install yfinance pandas`; **not** required for Observa itself).

Technical examples only — not financial advice.

## Status

Private MVP tester build — **not** production or live-trading software.

* Verified: Linux x86_64 (glibc ≥ 2.34), CPython ≥ 3.10 via the abi3 wheel.
* Not runtime-verified: Windows, macOS, Google Colab.
* The base package has **zero third-party runtime dependencies**; MCP is an
  optional extra.

See [known limitations](docs/known-limitations.md) and the
[private MVP release notes](docs/mvp-release-notes.md).

## Documentation

* [Getting started](docs/getting-started.md)
* [Agent authoring guide](docs/agent/strategy-authoring.md) · [strategy contract](docs/strategy-contract.md)
* [Execution model & assumptions](docs/execution-model.md)
* [Inspection & strategy API](docs/STRATEGY_API.md) · [MCP](docs/MCP.md)
* [Data format](docs/data-format.md) · [known limitations](docs/known-limitations.md)
* [Architecture](docs/ARCHITECTURE.md)

## Development (contributors — not end users)

Building Observa requires Rust, Cargo and Maturin:

```bash
python -m pip install maturin
cd python && maturin build --release   # wheel in python/target/wheels/
cargo test --workspace
```

Rust workspace under `crates/`, Python package under `python/`, replay frontend
under `python/python/observa/static/`. End users never need any of this.
