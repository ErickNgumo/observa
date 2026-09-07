"""Canonical real-data onboarding example — single self-contained file.

Quickstart B (real data): downloads intraday EUR/USD with yfinance, normalizes
it to Observa's CSV format, runs an EMA crossover, persists the run, and
prints the replay command. Everything is in this one file.

Setup (external dependency, only needed for real data):

    python -m pip install yfinance pandas

Then run from a fresh directory:

    python ema_observa.py

Then start replay:

    observa replay runs/ema_observa_<timestamp>

Notes
-----
* yfinance data availability/quality are NOT guaranteed (network/rate limits
  happen). If the download fails, the script explains what to do.
* The dataset is saved to an ABSOLUTE path recorded as dataset_source so
  replay can restore candles no matter where you run `observa replay`.
* Run directories are unique (timestamped) because Observa persistence is
  create-only: rerunning never overwrites a historical run.
* Technical example, not financial advice.
"""

import os
from datetime import datetime
from pathlib import Path

import observa


def download_eurusd(csv_path: Path) -> int:
    try:
        import pandas as pd  # noqa: F401 (used for MultiIndex detection)
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "This example needs:  python -m pip install yfinance pandas\n"
            "then re-run:         python ema_observa.py"
        ) from exc

    print("Downloading EUR/USD 15-minute data (yfinance ticker 'EURUSD=X')...")
    frame = yf.download("EURUSD=X", interval="15m", period="5d",
                        progress=False, auto_adjust=False)
    if frame is None or frame.empty:
        raise SystemExit(
            "yfinance returned no data right now (offline or rate-limited). "
            "Try later, or use the bundled sample with examples/quickstart.py."
        )
    if isinstance(frame.columns, pd.MultiIndex):  # flatten if present
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index().rename(columns={
        "Datetime": "timestamp", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    frame = frame[["timestamp", "open", "high", "low", "close", "volume"]]
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

    # Basic validation before saving (observa re-validates on load).
    assert frame["open"].notna().all() and frame["high"].notna().all()
    assert frame["low"].notna().all() and frame["close"].notna().all()

    frame.to_csv(csv_path, index=False)
    print("Saved %d bars to %s" % (len(frame), csv_path))
    return len(frame)


class EmaCrossover:
    """Fast/slow EMA crossover; closes positions by exact ticket."""

    def __init__(self):
        self.closes = []

    def initialize(self, params=None):
        params = params or {}
        self.fast = int(params.get("fast", 5))
        self.slow = int(params.get("slow", 20))
        self.closes = []

    def _ema(self, period):
        closes = self.closes
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = closes[0]
        for price in closes[1:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def on_bar(self, bar, portfolio, history):
        self.closes.append(bar["close"])
        fast = self._ema(self.fast)
        slow = self._ema(self.slow)
        if fast is None or slow is None:
            return []
        prev_fast = self._ema_prev(self.fast)
        prev_slow = self._ema_prev(self.slow)
        crossed_up = prev_fast is not None and prev_slow is not None \
            and prev_fast <= prev_slow and fast > slow
        crossed_down = prev_fast is not None and prev_slow is not None \
            and prev_fast >= prev_slow and fast < slow
        if crossed_up and not portfolio["has_open_position"]:
            return [{"direction": "buy", "size": 1.0,
                     "price": bar["close"], "reason": "fast EMA above slow"}]
        if crossed_down and portfolio["has_open_position"]:
            pos = portfolio["open_positions"][0]  # explicit ticket close
            return [{"direction": "close", "size": pos["size"],
                     "ticket": pos["position_id"], "reason": "fast EMA below slow"}]
        return []

    def _ema_prev(self, period):
        closes = self.closes[:-1]
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = closes[0]
        for price in closes[1:]:
            ema = price * k + ema * (1.0 - k)
        return ema

    def teardown(self):
        pass


def main() -> None:
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_file = Path("eurusd_m15.csv").resolve()       # absolute path
    run_dir = Path("runs") / ("ema_observa_" + run_tag)  # unique (create-only)

    download_eurusd(data_file)

    config = observa.Config(
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"fast": 5, "slow": 20},
        strategy_name="EmaCrossover",
        dataset_source=str(data_file),  # absolute, so replay restores candles
    )

    result = observa.run(EmaCrossover(), str(data_file), config=config,
                         output=str(run_dir))

    print()
    print("final balance:   %.2f" % result.final_balance)
    print("final equity:    %.2f" % result.final_equity)
    print("trades:          %d" % len(result.trades))
    print("open positions:  %d" % result.open_positions)
    print("events:          %d" % len(result.events))
    print()
    print("Run saved to:    %s" % run_dir)
    print("Replay with:     observa replay %s" % run_dir)
    print("Then open:       http://localhost:7878")


if __name__ == "__main__":
    main()
