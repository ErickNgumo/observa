"""Deterministic generator for the tracked sample dataset (no dependencies).

Regenerate with:  python python/observa/samples/generate_sample_data.py

The sample is a synthetic, clearly non-financial price series used only to
demonstrate the API (it is not market data and implies nothing about
tradability).
"""

import math
import pathlib

HERE = pathlib.Path(__file__).parent
OUT = HERE / "sample_m15.csv"

N = 200
START = 1_704_067_200  # 2024-01-01T00:00:00Z
STEP = 15 * 60  # M15


def generate():
    seed = 12345
    price = 1.1000
    rows = []
    for i in range(N):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        rnd = (seed % 10000) / 10000.0  # 0..1
        drift = math.sin(i / 14.0) * 0.0006 + (rnd - 0.5) * 0.0004
        open_ = price
        close = max(0.0001, open_ + drift)
        hi = max(open_, close) + rnd * 0.0003
        lo = min(open_, close) - (1 - rnd) * 0.0003
        volume = round(100 + rnd * 900, 1)
        ts = START + i * STEP
        rows.append(
            "%s,%.5f,%.5f,%.5f,%.5f,%.1f"
            % (format_ts(ts), round(open_, 5), round(hi, 5), round(lo, 5), round(close, 5), volume)
        )
        price = close
    return rows


def format_ts(epoch: int) -> str:
    # epoch -> UTC "YYYY-MM-DD HH:MM:SS+00:00" (the CSV loader's expected form)
    days, rem = divmod(epoch, 86400)
    h, rem2 = divmod(rem, 3600)
    m, s = divmod(rem2, 60)
    # civil-from-days (Howard Hinnant algorithm)
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


def main() -> None:
    OUT.write_text("timestamp,open,high,low,close,volume\n" + "\n".join(generate()) + "\n")
    print("wrote %d bars to %s" % (N, OUT))


if __name__ == "__main__":
    main()
