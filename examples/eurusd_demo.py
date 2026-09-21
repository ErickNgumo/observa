"""Observa real-data demo — EUR/USD 15-minute, fully offline.

Install Observa using the official private-MVP release URL in README.md
(do not run bare `pip install observa` — that is an unrelated PyPI package).

Unlike ``examples/ema_observa.py``, this demo downloads **nothing**: the
EUR/USD series is bundled in the wheel (``observa.demo_data_path()``), so it
runs with no network, no ``yfinance`` and no ``pandas``.

    python eurusd_demo.py

It runs a 12/26 EMA crossover over the fixed demo dataset, draws both EMAs and
every entry/exit on the chart, persists the run, and prints the replay
command:

    observa replay runs/eurusd-demo

Provenance of the bundled series (source, ticker, exact range, bar count) is in
``docs/demo-dataset.md``. The deterministic synthetic sample used by
``examples/quickstart.py`` and by the regression tests is untouched.

Technical example only — not financial advice. Results on this sample say
nothing about future performance.
"""

import observa
from observa.samples import EmaCrossover

data_file = observa.demo_data_path()

config = observa.Config(
    fill_mode=observa.NEXT_BAR_OPEN,
    spread=0.0002,
    slippage=0.0001,
    commission=7.0,
    commission_mode=observa.ROUND_TRIP,
    interval="15m",
    params={"fast": 12, "slow": 26},
    strategy_name="EmaCrossover",
    dataset_source=data_file,  # records the bundled path so replay restores candles
)

result = observa.run(EmaCrossover(), data_file, config=config,
                     output="runs/eurusd-demo")

print(f"dataset:         EUR/USD 15m (bundled, 600 bars)")
print(f"final balance:   {result.final_balance:.2f}")
print(f"final equity:    {result.final_equity:.2f}")
print(f"trades:          {len(result.trades)}")
print(f"open positions:  {result.open_positions}")
print(f"events:          {len(result.events)}")
print()
print("Run saved to:      runs/eurusd-demo")
print("Replay with:       observa replay runs/eurusd-demo")
print("Then open:         the URL printed by observa replay")
