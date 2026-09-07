# Tester Onboarding — Observa 0.1.0 (Private MVP)

This is the whole kit. Please try it **without help first** — we want to see
what is naturally understandable. Expected total time: about five minutes for
the sample, more if you try your own strategy.

You will be asked to report:

1. Where you got stuck and what you expected to happen.
2. What the replay helped you understand (or not).
3. Whether you would use this on one of your real strategies.

## 1. Install

Install the **official private-MVP wheel** from the private GitHub Release
(the command below). Do not `pip install observa` — that is an unrelated
PyPI package.

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.0-private-mvp/observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl"
```

SHA-256: `8367263b786243e0fd89d289cb8a9df1cf1e0ec961316697c95d36f2605fc23c`

For the real-data example also:

```bash
python -m pip install yfinance pandas
```

**Notebook users:** if you installed/replaced Observa while a notebook kernel
was running, restart the kernel first.

```python
import observa
print(observa.__version__)   # should print 0.1.0
print(observa.__file__)      # .../site-packages/observa/__init__.py
```


## Diagnostics

If anything fails, include this snippet's output in your report:

```bash
python -c "import observa, platform, sys; print(observa.__version__); print(platform.platform()); print(sys.version)"
```

## 1b. Run your own example later

For real EUR/USD data, one self-contained file:
`python examples/ema_observa.py` (needs `pip install yfinance pandas`). It
downloads, normalizes, saves, runs, persists to a unique timestamped run dir,
and prints the replay command.

## 2. Run the bundled sample

```python
import importlib.util
import observa

data = observa.sample_data_path()
spec = importlib.util.spec_from_file_location("sample", observa.sample_strategy_path())
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    dataset_source=data,  # records the data path so replay can restore candles
)

result = observa.run(mod.SampleEma(), data, config=config, output="runs/sample")
```

Inspect the result:

```python
print(result.final_balance)
print(result.final_equity)
print(len(result.trades))     # closed trades
print(result.open_positions)  # positions still open at the end
print(result.metrics)
```

Questions to answer later: do `final_balance` and `final_equity` make sense?
What do you think the open position means?

## 3. Open the replay

```bash
observa replay runs/sample
```

Open http://localhost:7878 in a browser. Controls: Play, Step (next bar),
Previous, Reset, Jump to end. The bottom panel has tabs: Equity Curve, Trade
Log, **Replay State** (account, positions, orders, current-bar events),
Metrics.

Try to explain out loud (or in notes): *what happened in this run and why* —
when the strategy decided to buy, when the order filled, what the position
did, and why equity differs from balance at the end.

## 4. Optional — your own simple strategy

Write a small strategy class with `initialize(params)`, `on_bar(bar,
portfolio, history)`, and `teardown()`. Return signal dicts such as
`{"direction": "buy", "size": 1.0}` or close by exact ticket with
`{"direction": "close", "size": ..., "ticket": pos["position_id"]}`.

If you hit a blocker, record it **before** asking for help:
what you were doing, what you expected, what happened.

## 5. Feedback

Report using the categories and template in `docs/mvp-feedback.md`. Key
questions we care about:

* What did you think Observa was for before using it?
* What did the replay change about how you understood the backtest?
* Do you trust the result more, less, or the same as a normal backtest? Why?
* What would stop you from using Observa again?
* What is the first feature you would add?

## Reference

* Getting started: `docs/getting-started.md`
* Strategy contract: `docs/strategy-contract.md`
* Execution assumptions: `docs/execution-model.md`
* Known limitations: `docs/known-limitations.md`
