"""One-time sourcing tool for the bundled real-market EUR/USD demo dataset.

**Development only.** This script is the only place in the project that talks to
``yfinance``. It is never imported at runtime, and the packaged demo never
downloads anything: the fixed CSV it produces is committed and shipped inside
the wheel (see :func:`observa.demo_data_path`).

Provenance of the committed fixture
-----------------------------------
=========================  ==============================================
Source                     Yahoo Finance, via ``yfinance``
Ticker                     ``EURUSD=X``
Interval                   ``15m``
Downloaded (UTC)           ``2026-09-20``
Downloaded window          last 60 days available for 15m (Yahoo's limit)
Selected UTC range         ``2026-08-12 01:30:00`` .. ``2026-08-20 08:45:00``
Bars                       600
Prices                     rounded to 5 decimals
Volume                     not included — Yahoo reports 0 for FX, so the
                           column is written empty rather than implying
                           real volume
=========================  ==============================================

The window was chosen for *visually useful market behaviour* — quiet
consolidation, a pullback, a trend leg, a weekend gap and some whipsaw — not
because it makes the demo strategy profitable. Trade counts and P&L on this
sample imply nothing about future performance.

Regenerate (requires network + ``python -m pip install yfinance pandas``)::

    python -m observa.samples.generate_demo_data

Verify the committed CSV without touching the network::

    python -m observa.samples.generate_demo_data --check
"""

from __future__ import annotations

import csv
import os
import sys

#: Recorded provenance — the committed fixture must match these exactly.
SOURCE = "Yahoo Finance via yfinance"
TICKER = "EURUSD=X"
INTERVAL = "15m"
DOWNLOADED_ON = "2026-09-20"
UTC_START = "2026-08-12 01:30:00+00:00"
UTC_END = "2026-08-20 08:45:00+00:00"
BAR_COUNT = 600

_TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "eurusd_m15_demo.csv")
_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def download() -> list[dict]:
    """Downloads and normalizes the demo window. Needs network + yfinance."""
    try:
        import pandas as pd  # noqa: F401  (used for MultiIndex handling)
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - development only
        raise SystemExit(
            "Regenerating the demo dataset needs:\n"
            "    python -m pip install yfinance pandas\n"
            "End users never need these — the fixture is bundled."
        ) from exc

    frame = yf.download(TICKER, interval=INTERVAL, period="60d",
                        progress=False, auto_adjust=False)
    if frame is None or frame.empty:
        raise SystemExit("yfinance returned no data (offline or rate-limited).")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns={"Open": "open", "High": "high",
                                  "Low": "low", "Close": "close"})
    frame = frame[["open", "high", "low", "close"]].copy()
    frame.index = frame.index.tz_convert("UTC")

    start = pd.Timestamp(UTC_START)
    end = pd.Timestamp(UTC_END)
    window = frame.loc[(frame.index >= start) & (frame.index <= end)]
    if len(window) != BAR_COUNT:
        raise SystemExit(
            "expected %d bars in %s..%s, got %d — Yahoo only serves ~60 days of "
            "15m data, so this window is no longer downloadable. The committed "
            "CSV remains valid; update the recorded range to re-source."
            % (BAR_COUNT, UTC_START, UTC_END, len(window))
        )

    rows = []
    for stamp, bar in window.iterrows():
        rows.append({
            "timestamp": stamp.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "open": round(float(bar["open"]), 5),
            "high": round(float(bar["high"]), 5),
            "low": round(float(bar["low"]), 5),
            "close": round(float(bar["close"]), 5),
            "volume": "",  # Yahoo reports 0 volume for FX: no real data
        })
    return rows


def write(rows, path: str = _TARGET) -> str:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def load(path: str = _TARGET) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def check(path: str = _TARGET) -> int:
    """Offline check: the bundled fixture matches the recorded provenance."""
    rows = load(path)
    problems = []
    if len(rows) != BAR_COUNT:
        problems.append("bar count %d != %d" % (len(rows), BAR_COUNT))
    if rows:
        if rows[0]["timestamp"] != (UTC_START[:-6] + "+00:00"):
            problems.append("first timestamp %r != %r"
                            % (rows[0]["timestamp"], UTC_START[:-6] + "+00:00"))
        if rows[-1]["timestamp"] != (UTC_END[:-6] + "+00:00"):
            problems.append("last timestamp %r != %r"
                            % (rows[-1]["timestamp"], UTC_END[:-6] + "+00:00"))
    for i, row in enumerate(rows):
        try:
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        except (TypeError, ValueError):
            problems.append("row %d has unparseable prices" % i)
            break
        if not (low <= o <= h and low <= c <= h):
            problems.append("row %d violates OHLC bounds" % i)
            break
    for problem in problems:
        print("FAIL %s" % problem, file=sys.stderr)
    if problems:
        return 1
    print("demo dataset OK: %d bars, %s .. %s" % (len(rows), UTC_START, UTC_END))
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        return check()
    rows = download()
    path = write(rows)
    print("wrote %d bars to %s" % (len(rows), path))
    print("source: %s | ticker: %s | interval: %s | downloaded: %s"
          % (SOURCE, TICKER, INTERVAL, DOWNLOADED_ON))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
