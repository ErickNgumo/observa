"""Real-data example: download intraday EUR/USD with yfinance and backtest an
EMA crossover with Observa.

Setup (external dependency, only needed for this example):

    pip install yfinance pandas

Then:

    python examples/ema_yfinance.py

Notes
-----
* yfinance data availability and quality are NOT guaranteed by Observa or by
  Yahoo; this is a data-source demonstration. If the download fails (offline,
  rate-limited, ticker unavailable) the example exits with a clear message.
* The EMA strategy is a technical example, not financial advice.
"""

import os

import observa


def main() -> None:
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "yfinance is required for this example.\n"
            "Install it with:  pip install yfinance pandas\n"
            "then re-run:      python examples/ema_yfinance.py"
        ) from exc

    print("Downloading EUR/USD 15-minute data (yfinance ticker 'EURUSD=X')...")
    frame = yf.download("EURUSD=X", interval="15m", period="5d", progress=False,
                        auto_adjust=False)
    if frame is None or frame.empty:
        raise SystemExit(
            "yfinance returned no data for EURUSD=X right now. This can happen "
            "offline or when Yahoo is rate-limiting. Try again later, or use "
            "the bundled sample (python examples/quickstart.py)."
        )
    if isinstance(frame.columns, __import__("pandas").MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index().rename(columns={
        "Datetime": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    frame = frame[["timestamp", "open", "high", "low", "close", "volume"]]
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

    data_path = os.path.abspath("eurusd_m15.csv")
    frame.to_csv(data_path, index=False)
    print("Saved %d bars to %s" % (len(frame), data_path))

    class EmaCrossover:
        def __init__(self):
            self.fast = 5
            self.slow = 20
            self.fast_ema = None
            self.slow_ema = None
            self.prev_fast = None
            self.prev_slow = None

        def initialize(self, params=None):
            params = params or {}
            self.fast = int(params.get("fast", 5))
            self.slow = int(params.get("slow", 20))

        def _update(self, current, price, period):
            if current is None:
                return price
            k = 2.0 / (period + 1.0)
            return price * k + current * (1.0 - k)

        def on_bar(self, bar, portfolio, history):
            self.prev_fast = self.fast_ema
            self.prev_slow = self.slow_ema
            self.fast_ema = self._update(self.fast_ema, bar["close"], self.fast)
            self.slow_ema = self._update(self.slow_ema, bar["close"], self.slow)
            if self.prev_fast is None or self.prev_slow is None:
                return []
            crossed_up = self.prev_fast <= self.prev_slow and self.fast_ema > self.slow_ema
            crossed_down = self.prev_fast >= self.prev_slow and self.fast_ema < self.slow_ema
            if crossed_up and not portfolio["has_open_position"]:
                return [{"direction": "buy", "size": 1.0,
                         "price": bar["close"], "reason": "fast EMA above slow EMA"}]
            if crossed_down and portfolio["has_open_position"]:
                pos = portfolio["open_positions"][0]  # explicit ticket close
                return [{"direction": "close", "size": pos["size"],
                         "ticket": pos["position_id"], "reason": "fast EMA below slow EMA"}]
            return []

        def teardown(self):
            pass

    config = observa.Config(
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"fast": 5, "slow": 20},
        strategy_name="EmaCrossoverYf",
        dataset_source=data_path,
    )
    out_dir = os.path.abspath("runs/ema_yfinance")
    result = observa.run(EmaCrossover(), data_path, config=config, output=out_dir)

    print("final balance:  %.2f" % result.final_balance)
    print("final equity:   %.2f" % result.final_equity)
    print("trades:         %d" % len(result.trades))
    print("open positions: %d" % result.open_positions)
    print("events:         %d" % len(result.events))
    print("artifacts:      %s" % out_dir)
    print("replay it with: observa replay %s" % out_dir)


if __name__ == "__main__":
    main()
