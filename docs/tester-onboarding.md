# Tester Onboarding — Observa 0.1.0 (Private MVP)

This is the whole kit. Please try it **without help first** — we want to see
what is naturally understandable. Expected total time: about five minutes for
the sample, more if you try your own strategy.

You will be asked to report:

1. Where you got stuck and what you expected to happen.
2. What the replay helped you understand (or not).
3. Whether you would use this on one of your real strategies.

## 1. Install

```bash
pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
```

```python
import observa
print(observa.__version__)   # should print 0.1.0
```

## Diagnostics

If anything fails, include this snippet's output in your report:

```bash
python -c "import observa, platform, sys; print(observa.__version__); print(platform.platform()); print(sys.version)"
```

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
