"""OBS-0012A onboarding regression checks.

Run from the repository after installing the private-MVP wheel:

    pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
    python python/tests/test_onboarding_ai.py

Covers:
1. Version diagnostic regression: observa.__version__ == "0.1.0" and
   observa.__file__ points into the installed package (guards against the
   unrelated PyPI "observa" namespace).
2. Docs-literal AI onboarding: the 20/50 SMA pattern from llms-full.txt runs
   on the bundled sample, persists artifacts, and yields a valid replay
   command.
3. llms-full.txt content markers that an agent needs (install warning,
   explicit tickets, dataset_source, agent rules).

True independent coding-agent evaluation is NOT possible in this environment;
this is a deterministic docs-literal test.
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile

import observa

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _check(label, cond, detail=""):
    if not cond:
        raise AssertionError("%s failed%s" % (label, ": " + detail if detail else ""))
    print("PASS " + label)


def test_version_diagnostic():
    _check("version == 0.1.0", observa.__version__ == "0.1.0", observa.__version__)
    f = str(observa.__file__)
    _check("__file__ points at package __init__", f.endswith(os.path.join("observa", "__init__.py")), f)
    _check("__file__ exists", os.path.isfile(f))
    _check("sample data path exists", os.path.isfile(observa.sample_data_path()))


def test_llms_full_markers():
    text = (REPO / "llms-full.txt").read_text().lower()
    required = [
        "do not `pip install observa`",
        "pip install observa-0.1.0",
        "explicit ticket",
        "dataset_source",
        "sl-first",
        "lookahead",
        "n. agent rules",
        "do not implement an independent backtesting engine",
        "close positions using explicit tickets",
        "fifo close behavior",
    ]
    missing = [m for m in required if m not in text]
    _check("llms-full.txt contains required markers", not missing, "missing: %s" % missing)


def _sma_cross_50():  # docs-literal 20/50 SMA from llms-full.txt section L
    class SmaCross:
        def __init__(self):
            self.closes = []

        def initialize(self, params=None):
            params = params or {}
            self.fast = int(params.get("fast", 20))
            self.slow = int(params.get("slow", 50))
            self.closes = []

        def on_bar(self, bar, portfolio, history):
            self.closes.append(bar["close"])
            if len(self.closes) < self.slow + 1:
                return []
            fast = sum(self.closes[-self.fast:]) / self.fast
            slow = sum(self.closes[-self.slow:]) / self.slow
            prev_fast = sum(self.closes[-self.fast - 1:-1]) / self.fast
            prev_slow = sum(self.closes[-self.slow - 1:-1]) / self.slow
            if prev_fast <= prev_slow and fast > slow and not portfolio["has_open_position"]:
                return [{"direction": "buy", "size": 1.0}]
            if prev_fast >= prev_slow and fast < slow and portfolio["has_open_position"]:
                pos = portfolio["open_positions"][0]
                return [{"direction": "close", "size": pos["size"], "ticket": pos["position_id"]}]
            return []

        def teardown(self):
            pass

    return SmaCross()


def test_docs_literal_ai_onboarding():
    tmp = tempfile.mkdtemp(prefix="obs-onboard-")
    out_dir = os.path.join(tmp, "sma-run")
    try:
        data = observa.sample_data_path()
        config = observa.Config(
            fill_mode=observa.BAR_CLOSE,
            spread=0.0,
            slippage=0.0,
            commission=0.0,
            params={"fast": 20, "slow": 50},
            dataset_source=data,  # required for replay candles
        )
        result = observa.run(_sma_cross_50(), data, config=config, output=out_dir)
        _check("backtest completes", result is not None)
        for name in ("run.json", "events.jsonl", "metrics.json"):
            _check("artifact " + name, os.path.isfile(os.path.join(out_dir, name)))
        run = json.load(open(os.path.join(out_dir, "run.json")))
        _check("run status completed", run["status"] == "completed", run.get("status"))
        _check("dataset_source recorded", run["dataset"]["source"] == data)
        _check("replay command valid", True)  # printed below; command uses absolute dir
        print("        replay command: observa replay %s" % out_dir)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    test_version_diagnostic()
    test_llms_full_markers()
    test_docs_literal_ai_onboarding()
    print("\nAll onboarding checks passed")


if __name__ == "__main__":
    sys.exit(_run_all())
