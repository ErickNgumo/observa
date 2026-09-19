"""Gold authoring example (OBS-AI-04) — imitate this file.

It demonstrates the whole canonical strategy authoring contract in ~45 lines:

* ``initialize`` with parameters
* an explicit warm-up guard (``history`` holds strictly prior bars only)
* one entry with ``size``, ``sl`` and a persisted ``reason``
* one exact-ticket close with its own ``reason``
* one annotation (an ``hline`` at the entry price)
* ``Config`` + ``observa.run(..., output=...)`` persistence

Run it directly::

    python example_strategy.py

This is the *authoring* example. It is deliberately not the economic oracle —
``observa.samples.sample_strategy.SampleEma`` remains the canonical baseline
strategy. Do not change execution behaviour here; the Engine owns all economics.
"""

from __future__ import annotations

import observa


class AgentExample(observa.Strategy):
    """Short simple-moving-average crossover, long only, one position at a time."""

    def initialize(self, params=None):
        params = params or {}
        self.period = int(params.get("period", 5))
        self.entered = False

    def on_bar(self, bar, portfolio, history):
        # Warm-up guard: history contains only strictly prior bars, so it is
        # empty on the first bar. Never index it without checking.
        if len(history) < self.period:
            return []

        window = [b["close"] for b in history[-self.period:]]
        sma = sum(window) / float(self.period)
        price = bar["close"]

        if not portfolio["has_open_position"]:
            if price > sma:
                self.entered = True
                return {
                    "signals": [
                        {
                            "direction": "buy",
                            "size": 1.0,
                            "price": price,
                            "sl": round(price - 0.0040, 5),
                            "reason": "close above %d-bar SMA" % self.period,
                        }
                    ],
                    "drawings": [
                        {
                            "id": "entry_line",
                            "type": "hline",
                            "price": price,
                            "color": "#58a6ff",
                            "label": "entry",
                        }
                    ],
                }
            return []

        if price < sma:
            # Exact-ticket close. There is no FIFO and no implicit close.
            pos = portfolio["open_positions"][0]
            return {
                "signals": [
                    {
                        "direction": "close",
                        "size": pos["size"],
                        "ticket": pos["position_id"],
                        "reason": "close below %d-bar SMA" % self.period,
                    }
                ]
            }
        return []

    def teardown(self):
        pass


def main():
    import datetime
    import os

    data = observa.sample_data_path()
    config = observa.Config(
        dataset_source=data,
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"period": 5},
        strategy_name="AgentExample",
    )
    run_dir = os.path.join(
        "runs", "agent_example_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    result = observa.run(AgentExample(), data, config=config, output=run_dir)
    summary = result.summary()
    print("status:        %s" % summary["status"])
    print("bars:          %s" % summary["total_bars"])
    print("trades:        %s" % summary["trades"])
    print("final_balance: %.2f" % summary["final_balance"])
    print("final_equity:  %.2f" % summary["final_equity"])
    print("run saved to:  %s" % run_dir)
    print("inspect with:  observa replay %s" % run_dir)


if __name__ == "__main__":
    main()
