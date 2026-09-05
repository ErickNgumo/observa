"""Minimal getting-started example for the installed ``observa`` Python package.

Install the wheel first (``pip install observa``), then run:

    python examples/python_quickstart.py

This example uses the bundled sample dataset and sample strategy, so it runs
from anywhere — no repository checkout or Rust toolchain is required. It runs
a backtest, prints the result, saves canonical artifacts, and prints how to
launch the visual replay.

To launch the replay of the saved run:

    observa replay runs/quickstart
"""

import importlib.util
import os

import observa

# Bundled deterministic sample assets (shipped inside the wheel).
data_file = observa.sample_data_path()
strategy_file = observa.sample_strategy_path()

spec = importlib.util.spec_from_file_location("sample_strategy", strategy_file)
strategy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strategy_module)

config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    params={"fast": 5, "slow": 20},
    strategy_name="SampleEma",
    strategy_source=strategy_file,
    dataset_source=data_file,
)

out_dir = os.path.abspath("runs/quickstart")
result = observa.run(strategy_module.SampleEma(), data_file, config=config, output=out_dir)

print(f"final balance:   {result.final_balance:.2f}")
print(f"final equity:    {result.final_equity:.2f}")
print(f"trades:          {len(result.trades)}")
print(f"open positions:  {result.open_positions}")
print(f"events:          {len(result.events)}")
print()
print(f"artifacts saved to {out_dir}  (run.json / events.jsonl / metrics.json)")
print("replay it with:   observa replay %s" % out_dir)
