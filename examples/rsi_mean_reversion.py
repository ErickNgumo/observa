"""Second canonical strategy pattern: dependency-light RSI mean reversion.

Install Observa using the official private-MVP release URL in README.md
(do not run bare `pip install observa` — that is an unrelated PyPI package).

Obtain this file from the private-MVP GitHub Release assets, or copy the code
below into your own file, then run:

    python rsi_mean_reversion.py

Then:

    observa replay runs/rsi

Demonstrates: indicator calculation, strategy state, entry condition,
explicit-ticket close, and the canonical Observa run/persist/replay flow.
This is a technical example, not trading advice.
"""

import os
from datetime import datetime
from pathlib import Path

import observa

# A dependency-light RSI (Wilder's smoothing) over a rolling window.
def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


class RsiMeanReversion:
    def __init__(self):
        self.closes = []
        self.bought = False

    def initialize(self, params=None):
        params = params or {}
        self.period = int(params.get("period", 14))
        self.buy_at = float(params.get("buy_at", 30.0))
        self.sell_at = float(params.get("sell_at", 70.0))
        self.closes = []
        self.bought = False

    def on_bar(self, bar, portfolio, history):
        self.closes.append(bar["close"])
        value = rsi(self.closes, self.period)
        if value is None:
            return []
        if not self.bought and value < self.buy_at and not portfolio["has_open_position"]:
            self.bought = True
            return [{"direction": "buy", "size": 1.0, "price": bar["close"],
                     "reason": "RSI below oversold threshold"}]
        if self.bought and value > self.sell_at and portfolio["has_open_position"]:
            pos = portfolio["open_positions"][0]  # explicit ticket close
            self.bought = False
            return [{"direction": "close", "size": pos["size"],
                     "ticket": pos["position_id"], "reason": "RSI above overbought"}]
        return []

    def teardown(self):
        pass


def main() -> None:
    data_file = observa.sample_data_path()
    config = observa.Config(
        fill_mode=observa.BAR_CLOSE,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"period": 14, "buy_at": 35.0, "sell_at": 65.0},
        strategy_name="RsiMeanReversion",
        dataset_source=data_file,
    )
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = str(Path("runs") / ("rsi_" + run_tag))
    result = observa.run(RsiMeanReversion(), data_file, config=config, output=out_dir)

    print("final balance:  %.2f" % result.final_balance)
    print("final equity:   %.2f" % result.final_equity)
    print("trades:         %d" % len(result.trades))
    print("open positions: %d" % result.open_positions)
    print("events:         %d" % len(result.events))
    print("Run saved to:    %s" % out_dir)
    print("Replay with:     observa replay %s" % out_dir)
    print("Then open:       http://localhost:7878")


if __name__ == "__main__":
    main()
