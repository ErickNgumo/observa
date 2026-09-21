"""Demo strategy for the bundled real-market EUR/USD dataset.

A long-only fast/slow **EMA crossover** over the fixed EUR/USD 15-minute demo
series (:func:`observa.demo_data_path`). It is intentionally simple and visual:

* the fast and slow EMA are drawn on the price pane as two `series` annotations;
* entries and exits are drawn as arrow markers;
* every decision carries a plain-language persisted ``reason``.

The goal is *visual clarity* — showing what the strategy saw and why it acted —
not profitability. This is a technical example only, not financial advice, and
no result on this sample implies anything about future performance.
"""

from __future__ import annotations

#: Default EMA periods (classic fast/slow pair).
FAST_PERIOD = 12
SLOW_PERIOD = 26

_FAST_COLOR = "#58a6ff"
_SLOW_COLOR = "#d29922"
_ENTRY_COLOR = "#3fb950"
_EXIT_COLOR = "#f85149"


class EmaCrossover:
    """Long-only EMA crossover over the bundled EUR/USD demo dataset.

    Enters long on a fast-over-slow crossover when flat, and closes that exact
    position by ticket on the opposite crossover. Never opens a second position,
    never assumes FIFO, and never implements its own fill model — the Engine
    owns execution and economics.
    """

    def __init__(self):
        self.fast_period = FAST_PERIOD
        self.slow_period = SLOW_PERIOD
        self.fast_ema = None
        self.slow_ema = None
        self.prev_fast = None
        self.prev_slow = None

    def initialize(self, params=None):
        params = params or {}
        self.fast_period = int(params.get("fast", FAST_PERIOD))
        self.slow_period = int(params.get("slow", SLOW_PERIOD))
        self.fast_ema = None
        self.slow_ema = None
        self.prev_fast = None
        self.prev_slow = None

    @staticmethod
    def _step(current, price, period):
        """One incremental EMA step (seeded with the first observed price)."""
        if current is None:
            return price
        k = 2.0 / (period + 1.0)
        return price * k + current * (1.0 - k)

    def on_bar(self, bar, portfolio, history):
        price = bar["close"]
        self.prev_fast = self.fast_ema
        self.prev_slow = self.slow_ema
        self.fast_ema = self._step(self.fast_ema, price, self.fast_period)
        self.slow_ema = self._step(self.slow_ema, price, self.slow_period)

        # The two indicator lines are descriptive only: they never affect
        # orders, fills, P&L or chronology.
        drawings = [
            {
                "id": "ema_fast",
                "type": "series",
                "value": round(self.fast_ema, 5),
                "color": _FAST_COLOR,
                "pane": "price",
                "label": "EMA %d" % self.fast_period,
            },
            {
                "id": "ema_slow",
                "type": "series",
                "value": round(self.slow_ema, 5),
                "color": _SLOW_COLOR,
                "pane": "price",
                "label": "EMA %d" % self.slow_period,
            },
        ]

        if self.prev_fast is None or self.prev_slow is None:
            return {"signals": [], "drawings": drawings}

        crossed_up = self.prev_fast <= self.prev_slow and self.fast_ema > self.slow_ema
        crossed_down = self.prev_fast >= self.prev_slow and self.fast_ema < self.slow_ema

        # ``history`` holds strictly prior bars, so its length is the bar index —
        # used only to give each marker a unique drawing id.
        bar_index = len(history)

        if crossed_up and not portfolio["has_open_position"]:
            drawings.append(
                {
                    "id": "entry_%d" % bar_index,
                    "type": "marker",
                    "time": bar["timestamp"],
                    "position": "below",
                    "shape": "arrow_up",
                    "color": _ENTRY_COLOR,
                    "text": "long",
                }
            )
            return {
                "signals": [
                    {
                        "direction": "buy",
                        "size": 1.0,
                        "price": price,
                        "reason": "Fast EMA crossed above slow EMA",
                    }
                ],
                "drawings": drawings,
            }

        if crossed_down and portfolio["has_open_position"]:
            positions = portfolio["open_positions"]
            if positions:
                position = positions[0]  # single-position demo: exact ticket close
                drawings.append(
                    {
                        "id": "exit_%d" % bar_index,
                        "type": "marker",
                        "time": bar["timestamp"],
                        "position": "above",
                        "shape": "arrow_down",
                        "color": _EXIT_COLOR,
                        "text": "close",
                    }
                )
                return {
                    "signals": [
                        {
                            "direction": "close",
                            "size": position["size"],
                            "ticket": position["position_id"],
                            "reason": "Fast EMA crossed below slow EMA",
                        }
                    ],
                    "drawings": drawings,
                }

        return {"signals": [], "drawings": drawings}

    def teardown(self):
        pass
