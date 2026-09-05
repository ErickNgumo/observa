"""Minimal sample strategy for the Observa Python API.

A simple long-only moving-average crossover that demonstrates the canonical
lifecycle (initialize / on_bar / teardown), MARKET entries with optional
stop-loss, and explicit ticket-based closes. It is a technical example only —
not financial advice, and not a claim of profitability.
"""


class SampleEma:
    """Long-only EMA crossover; closes open positions by exact ticket."""

    def __init__(self):
        self.fast = None
        self.slow = None
        self.fast_ema = None
        self.slow_ema = None
        self.prev_fast = None
        self.prev_slow = None

    def initialize(self, params=None):
        params = params or {}
        self.fast = int(params.get("fast", 5))
        self.slow = int(params.get("slow", 20))
        self.fast_ema = None
        self.slow_ema = None
        self.prev_fast = None
        self.prev_slow = None

    def _update(self, current, price, period):
        if current is None:
            return price
        k = 2.0 / (period + 1.0)
        return price * k + current * (1.0 - k)

    def on_bar(self, bar, portfolio, history):
        # Warm up on the first N bars.
        if self.fast is None:
            self.initialize(None)
        self.prev_fast = self.fast_ema
        self.prev_slow = self.slow_ema
        self.fast_ema = self._update(self.fast_ema, bar["close"], self.fast)
        self.slow_ema = self._update(self.slow_ema, bar["close"], self.slow)
        if self.prev_fast is None or self.prev_slow is None:
            return []

        crossed_up = self.prev_fast <= self.prev_slow and self.fast_ema > self.slow_ema
        crossed_down = self.prev_fast >= self.prev_slow and self.fast_ema < self.slow_ema

        if crossed_up and not portfolio["has_open_position"]:
            return [{
                "direction": "buy",
                "size": 1.0,
                "price": bar["close"],
                "sl": round(bar["close"] - 0.0040, 5),
                "reason": "fast EMA crossed above slow EMA",
            }]

        if crossed_down and portfolio["has_open_position"]:
            positions = portfolio["open_positions"]
            if not positions:
                return []
            pos = positions[0]  # explicit ticket close; sample is single-position
            return [{
                "direction": "close",
                "size": pos["size"],
                "ticket": pos["position_id"],
                "reason": "fast EMA crossed below slow EMA",
            }]
        return []

    def teardown(self):
        pass
