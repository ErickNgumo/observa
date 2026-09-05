"""Minimal getting-started example for the packaged `observa` Python API.

Install the wheel first (``pip install observa``), then run:

    python examples/python_quickstart.py

No Rust toolchain, Cargo, or repository checkout is required at runtime.
"""

import observa

DATA = [
    {"timestamp": "2023-11-14T22:13:20Z", "open": 1.0, "high": 1.05, "low": 0.99, "close": 1.02, "volume": None},
    {"timestamp": "2023-11-14T22:28:20Z", "open": 1.02, "high": 1.04, "low": 1.01, "close": 1.03, "volume": None},
    {"timestamp": "2023-11-14T22:43:20Z", "open": 1.03, "high": 1.06, "low": 1.02, "close": 1.05, "volume": None},
]


class MovingAverageStrategy(observa.Strategy):
    def initialize(self, params=None):
        self.n = int(params.get("n", 2)) if params else 2
        self.prices = []

    def on_bar(self, bar, portfolio, history):
        self.prices.append(bar["close"])
        if len(self.prices) < self.n:
            return []
        fast = sum(self.prices[-self.n:]) / self.n
        slow = sum(self.prices) / len(self.prices)
        if not portfolio["has_open_position"] and fast > slow:
            return [{"direction": "buy", "size": 1.0, "reason": "fast above slow"}]
        if portfolio["has_open_position"] and fast < slow:
            pos = portfolio["open_positions"][0]
            return [{"direction": "close", "size": pos["size"], "ticket": pos["position_id"]}]
        return []


def main():
    config = observa.Config(
        fill_mode=observa.BAR_CLOSE,
        spread=0.0,
        slippage=0.0,
        commission=0.0,
        params={"n": 2},
    )
    result = observa.run(MovingAverageStrategy(), DATA, config=config)
    print(f"final balance: {result.final_balance:.2f}")
    print(f"final equity:  {result.final_equity:.2f}")
    print(f"trades:        {len(result.trades)}")
    print(f"events:        {len(result.events)}")


if __name__ == "__main__":
    main()
