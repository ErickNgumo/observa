"""Clean-environment smoke test: run with no repo-relative imports/data and
no Rust toolchain on PATH. Executed from OUTSIDE the repository directory."""

import observa

assert observa.__version__ == "0.1.0"

bars = [
    {"timestamp": "2023-11-14T22:13:20Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": None},
    {"timestamp": "2023-11-14T22:28:20Z", "open": 1.5, "high": 1.5, "low": 1.5, "close": 1.5, "volume": None},
]


class BuyHold:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        if not getattr(self, "sent", False):
            self.sent = True
            return [{"direction": "buy", "size": 1.0}]
        return []

    def teardown(self):
        pass


cfg = observa.Config(fill_mode="bar_close", spread=0.0, slippage=0.0, commission=0.0)
res = observa.run(BuyHold(), bars, config=cfg)
# Buy at 1.0, hold to close 1.5: unrealized +50k, equity 60k, 1 open position.
assert abs(res.final_balance - 10_000.0) < 1e-9, res.final_balance
assert abs(res.final_equity - 60_000.0) < 1e-9, res.final_equity
assert res.open_positions == 1
assert len(res.events) == 12
print("EXTERNAL SMOKE OK:", res.final_balance, res.final_equity, res.open_positions)
