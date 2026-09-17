"""Deterministic generator for the canonical regression dataset.

Regenerate with:

    python python/tests/fixtures/generate_canonical_dataset.py

The dataset is synthetic and produced by this file alone: a fixed start
timestamp, a fixed bar count, an integer LCG and closed-form arithmetic. It
uses no network, no clock, no unseeded randomness and no user-local files, so
the bytes it writes are reproducible on any machine and at any time.

This fixture is the regression oracle for the canonical backtest baseline
(see ``docs/engineering/TESTING.md``). The real ``data/EURUSD_M15.csv`` is
gitignored and comes from a rolling yfinance window, so it must never be used
as a regression oracle.
"""

import math
import pathlib

HERE = pathlib.Path(__file__).parent
OUT = HERE / "canonical_m15.csv"

N = 1500
START = 1_704_067_200  # 2024-01-01T00:00:00Z — fixed, never "now"
STEP = 15 * 60  # M15
SEED = 987_654_321
PRICE0 = 1.100_00

# Synthetic price model constants (deterministic; tune only with a regenerated
# baseline, never silently). The level is built directly (not by integrating a
# drift) so the series stays in a realistic band around PRICE0:
#   level(i) = PRICE0 + TREND_AMP*sin(i/TREND_PERIOD)
#                     + CYCLE_AMP*sin(i/CYCLE_PERIOD)
#                     + mean-reverting noise walk
TREND_AMP = 0.0140
TREND_PERIOD = 170.0
CYCLE_AMP = 0.0045
CYCLE_PERIOD = 45.0
NOISE_AMP = 0.002_00
WALK_DECAY = 0.995
WICK_SCALE = 1.7
VOLUME_BASE = 120.0
VOLUME_SPAN = 880.0


def format_ts(epoch: int) -> str:
    """epoch -> UTC ``YYYY-MM-DD HH:MM:SS+00:00`` (the CSV loader's form)."""
    days, rem = divmod(epoch, 86400)
    h, rem2 = divmod(rem, 3600)
    m, s = divmod(rem2, 60)
    # civil-from-days (Howard Hinnant algorithm) — no timezone library needed
    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    mo = mp + (3 if mp < 10 else -9)
    y += 1 if mo <= 2 else 0
    return "%04d-%02d-%02d %02d:%02d:%02d+00:00" % (y, mo, d, h, m, s)


def _lcg(state: int) -> int:
    """Numerical Recipes LCG (deterministic, platform independent)."""
    return (state * 1_664_525 + 1_013_904_223) & 0xFFFF_FFFF


def generate():
    """Returns the CSV body rows (without the header)."""
    state = SEED
    walk = 0.0
    prev_close = PRICE0
    rows = []
    for i in range(N):
        state = _lcg(state)
        rnd = (state >> 8) / float(1 << 24)  # 0..1
        state = _lcg(state)
        rnd2 = (state >> 8) / float(1 << 24)

        walk = walk * WALK_DECAY + NOISE_AMP * (rnd - 0.5)
        close = (
            PRICE0
            + TREND_AMP * math.sin(i / TREND_PERIOD)
            + CYCLE_AMP * math.sin(i / CYCLE_PERIOD)
            + walk
        )
        open_ = prev_close
        high = max(open_, close) + rnd2 * NOISE_AMP * WICK_SCALE
        low = min(open_, close) - (1.0 - rnd2) * NOISE_AMP * WICK_SCALE
        volume = round(VOLUME_BASE + rnd * VOLUME_SPAN, 1)

        rows.append(
            "%s,%.5f,%.5f,%.5f,%.5f,%.1f"
            % (format_ts(START + i * STEP), open_, high, low, close, volume)
        )
        prev_close = close
    return rows


def main() -> None:
    rows = generate()
    OUT.write_text("timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n")
    print("wrote %d bars to %s" % (len(rows), OUT))


if __name__ == "__main__":
    main()
