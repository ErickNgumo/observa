"""Starter strategy — a mirror of Observa's canonical gold example.

This mirrors Observa's gold example (`examples/agent_example.py`, also bundled
at `observa.agent_example_path()`): the same canonical idioms, with the class
renamed for a user project. `python/tests/test_agent_contract.py` asserts this
file validates cleanly, so it cannot silently rot.

Edit the `on_bar` body to implement the user's rules. Do not implement
execution: Observa's Engine owns fills, spread, slippage, SL/TP and P&L.
"""

from __future__ import annotations

import observa


class UserStrategy(observa.Strategy):
    """Short simple-moving-average crossover, long only, one position at a time."""

    def initialize(self, params=None):
        params = params or {}
        self.period = int(params.get("period", 5))

    def on_bar(self, bar, portfolio, history):
        # Warm-up guard: history holds strictly prior bars only.
        if len(history) < self.period:
            return []

        window = [b["close"] for b in history[-self.period:]]
        sma = sum(window) / float(self.period)
        price = bar["close"]

        if not portfolio["has_open_position"]:
            if price > sma:
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
