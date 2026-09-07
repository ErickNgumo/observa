"""Observa quickstart — copy, paste, run.

Works from the installed private-MVP wheel (no repository needed):

    pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
    python examples/quickstart.py

Uses the bundled deterministic sample data and sample strategy, persists the
run, and prints how to launch the visual replay. Then run:

    observa replay runs/quickstart
"""

import os
from datetime import datetime
from pathlib import Path

import observa
from observa.samples.sample_strategy import SampleEma

data_file = observa.sample_data_path()

config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    params={"fast": 5, "slow": 20},
    strategy_name="SampleEma",
    dataset_source=data_file,  # records the data path so replay restores candles
)

run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = str(Path("runs") / ("quickstart_" + run_tag))
result = observa.run(SampleEma(), data_file, config=config, output=out_dir)

print(f"final balance:   {result.final_balance:.2f}")
print(f"final equity:    {result.final_equity:.2f}")
print(f"trades:          {len(result.trades)}")
print(f"open positions:  {result.open_positions}")
print(f"events:          {len(result.events)}")
print()
print(f"Run saved to:      {out_dir}")
print("Replay with:       observa replay %s" % out_dir)
print("Then open:         http://localhost:7878")
