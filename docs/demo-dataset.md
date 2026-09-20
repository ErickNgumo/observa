# EUR/USD Demo Dataset

The repository ships a **fixed historical** EUR/USD dataset so the demo, the
README and replay screenshots/videos always show the same real market data —
with no network access, no `yfinance` and no `pandas` required.

```python
import observa
from observa.samples import EmaCrossover

data = observa.demo_data_path()          # bundled CSV, works offline

result = observa.run(
    EmaCrossover(),
    data,
    config=observa.Config(dataset_source=data, interval="15m"),
    output="runs/eurusd-demo",
)
```

then

```bash
observa replay runs/eurusd-demo
```

## Provenance

| Field | Value |
| --- | --- |
| Source | Yahoo Finance, via `yfinance` |
| Ticker | `EURUSD=X` |
| Interval | `15m` |
| Downloaded (UTC) | `2026-09-20` |
| Downloaded window | last 60 days available for 15m (Yahoo's limit for this interval) |
| Selected UTC range | `2026-08-12 01:30:00` → `2026-08-20 08:45:00` |
| Bars | **600** |
| Prices | rounded to 5 decimals |
| Volume | **not included** — Yahoo reports `0` for FX, so the column is written empty rather than implying real volume |
| Bundled at | `observa/samples/eurusd_m15_demo.csv` (`observa.demo_data_path()`) |

The window was selected for **visually useful market behaviour**, not for
profitability: it contains quiet consolidation days, a pullback, a clear trend
leg and a weekend gap (~50 h), which makes the replay worth looking at. The
strategy's result on this sample says nothing about future performance.

## Why this is not the regression fixture

| Dataset | Used for |
| --- | --- |
| `observa.sample_data_path()` — synthetic, deterministic | tests, the canonical economic baseline, CI |
| `observa.demo_data_path()` — real EUR/USD | README, replay, screenshots/videos, onboarding |

The synthetic fixture is never replaced by this dataset. Tests never download
market data and never depend on `yfinance`.

## Regenerating (maintainers only)

`yfinance` is used exactly once, at fixture-creation time:

```bash
python -m pip install yfinance pandas
python -m observa.samples.generate_demo_data          # re-downloads + rewrites
python -m observa.samples.generate_demo_data --check  # offline provenance check
```

Yahoo only serves roughly the last 60 days of 15-minute data, so the recorded
window stops being downloadable over time. The committed CSV stays valid; a new
fixture would record a new range and bar count in the module docstring and in
the table above.

The module `observa/samples/generate_demo_data.py` is shipped for transparency
but is never imported at runtime. End users never install `yfinance` or
`pandas` to run the demo.
