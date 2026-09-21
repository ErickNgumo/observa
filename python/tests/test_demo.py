"""OBS-DEMO-01 — bundled real EUR/USD demo dataset and strategy.

Run against an installed wheel (or the source tree):

    python python/tests/test_demo.py

Verifies the fixed real-market demo fixture and the ``EmaCrossover`` demo
strategy **offline**: no network, no ``yfinance``, no ``pandas``. The dataset
was sourced once from Yahoo Finance (see ``docs/demo-dataset.md``); these checks
never download anything.

This file deliberately does not replace or re-baseline the synthetic canonical
regression fixture — that stays the deterministic oracle.
"""

import csv
import hashlib
import importlib.util
import os
import sys
import tempfile

import observa
from observa.samples import EmaCrossover

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: %s" % (detail,)))


def _rows(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_dataset_is_bundled_and_offline():
    path = observa.demo_data_path()
    check("demo_data_path() returns an existing file", os.path.isfile(path), path)
    check("demo dataset is bundled inside the installed package",
          os.path.dirname(os.path.dirname(path)).endswith("observa"), path)
    check("demo dataset is not the synthetic regression fixture",
          os.path.abspath(path) != os.path.abspath(observa.sample_data_path()))
    check("synthetic regression fixture is still present",
          os.path.isfile(observa.sample_data_path()))
    # Reading the demo must not pull in the sourcing-only dependencies.
    check("yfinance is not imported by the demo path",
          "yfinance" not in sys.modules)
    check("pandas is not imported by the demo path", "pandas" not in sys.modules)


def test_dataset_provenance_and_format():
    rows = _rows(observa.demo_data_path())
    check("recorded bar count is 600", len(rows) == 600, len(rows))
    check("header matches Observa's CSV format",
          list(rows[0].keys()) == ["timestamp", "open", "high", "low", "close", "volume"],
          list(rows[0].keys()))
    check("first timestamp matches the recorded UTC range",
          rows[0]["timestamp"] == "2026-08-12 01:30:00+00:00", rows[0]["timestamp"])
    check("last timestamp matches the recorded UTC range",
          rows[-1]["timestamp"] == "2026-08-20 08:45:00+00:00", rows[-1]["timestamp"])
    check("volume is absent (Yahoo reports no FX volume)",
          all(r["volume"] == "" for r in rows))

    stamps = [r["timestamp"] for r in rows]
    check("timestamps are strictly increasing", stamps == sorted(stamps) and
          len(set(stamps)) == len(stamps))
    bad = []
    for i, r in enumerate(rows):
        o, h, lo, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        if not (lo <= o <= h and lo <= c <= h):
            bad.append(i)
    check("every bar satisfies OHLC bounds", not bad, bad[:3])
    check("prices are 5-decimal FX quotes",
          all(len(r["close"].split(".")[-1]) <= 5 for r in rows))

    # Real market data, not the synthetic generator's output.
    check("demo prices differ from the synthetic sample",
          open(observa.demo_data_path()).read() != open(observa.sample_data_path()).read())

    # The provenance module's own offline check must agree.
    spec = importlib.util.spec_from_file_location(
        "observa_demo_generator",
        os.path.join(os.path.dirname(observa.demo_data_path()), "generate_demo_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check("generator records 600 bars", module.BAR_COUNT == 600, module.BAR_COUNT)
    check("generator records the same UTC range",
          module.UTC_START == "2026-08-12 01:30:00+00:00"
          and module.UTC_END == "2026-08-20 08:45:00+00:00")
    check("generator names the real source",
          module.SOURCE == "Yahoo Finance via yfinance"
          and module.TICKER == "EURUSD=X" and module.INTERVAL == "15m")
    check("generator --check passes offline", module.check() == 0)


def test_demo_run_is_dependency_free(tmp_dir):
    data = observa.demo_data_path()
    result = observa.run(
        EmaCrossover(),
        data,
        config=observa.Config(dataset_source=data, interval="15m"),
        output=os.path.join(tmp_dir, "eurusd-demo"),
    )
    summary = result.summary()
    check("demo run completes", summary["status"] == "completed", summary)
    check("demo run uses all 600 bars", summary["total_bars"] == 600, summary["total_bars"])
    trades = len(result.trades)
    check("demo produces 5-20 completed trades", 5 <= trades <= 20, trades)
    check("no yfinance/pandas needed at run time",
          "yfinance" not in sys.modules and "pandas" not in sys.modules)


def test_demo_reasons_and_drawings(tmp_dir):
    data = observa.demo_data_path()
    run_dir = os.path.join(tmp_dir, "demo")
    observa.run(EmaCrossover(), data,
                config=observa.Config(dataset_source=data, interval="15m"),
                output=run_dir)
    persisted = observa.inspect_run(run_dir)

    reasons = []
    for event in persisted.events(event_type="strategy_decision"):
        for signal in event.get("signals") or []:
            if signal.get("reason"):
                reasons.append(signal["reason"])
    check("every signal carries a plain-language reason", len(reasons) == 23, len(reasons))
    check("reasons are exactly the documented pair",
          set(reasons) == {"Fast EMA crossed above slow EMA",
                           "Fast EMA crossed below slow EMA"},
          sorted(set(reasons)))

    series_ids, marker_bars = set(), 0
    for index in range(600):
        drawings = persisted.bar(index)["drawings"] or []
        for d in drawings:
            if d["type"] == "series":
                series_ids.add(d["id"])
            if d["type"] == "marker":
                marker_bars += 1
    check("fast and slow EMA are drawn as series",
          {"ema_fast", "ema_slow"} <= series_ids, sorted(series_ids))
    check("entry/exit markers are drawn", marker_bars == 23, marker_bars)
    check("candles are restored for replay",
          persisted.bar(100)["ohlc_available"] is True)


def test_task_example_from_the_ticket(tmp_dir):
    """The documented call shape must work as written (config is optional)."""
    data = observa.demo_data_path()
    result = observa.run(EmaCrossover(), data, output=os.path.join(tmp_dir, "plain"))
    check("run(strategy, data, output=...) works without an explicit Config",
          result.summary()["status"] == "completed", result.summary())


def main():
    tmp = tempfile.mkdtemp(prefix="obs-demo-")
    try:
        test_dataset_is_bundled_and_offline()
        test_dataset_provenance_and_format()
        test_demo_run_is_dependency_free(tmp)
        test_demo_reasons_and_drawings(tmp)
        test_task_example_from_the_ticket(tmp)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:")
        for name in FAILED:
            print("  -", name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
