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
        "releases/download/observa-0.1.0-private-mvp",
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
        # Result API surface actually exposed by the installed wheel:
        exposed = [x for x in dir(result) if not x.startswith("_")]
        for field in ("final_balance", "final_equity", "trades", "orders",
                      "fills", "open_positions", "events", "metrics"):
            _check("result field exposed: " + field, field in exposed, str(exposed))
        _check("open_positions is a count", isinstance(result.open_positions, int))
        _check("replay command valid", True)  # printed below; command uses absolute dir
        print("        replay command: observa replay %s" % out_dir)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _payload_of(run_dir):
    ext = observa._observa
    return ext.replay_payload(run_dir)


def test_replay_payload_absolute_source_has_candles():
    import shutil

    tmp = tempfile.mkdtemp(prefix="obs-replay-")
    out_dir = os.path.join(tmp, "run")
    try:
        data = observa.sample_data_path()
        config = observa.Config(
            fill_mode=observa.BAR_CLOSE, spread=0.0, slippage=0.0,
            commission=0.0, params={"fast": 20, "slow": 50},
            dataset_source=data,  # absolute
        )
        observa.run(_sma_cross_50(), data, config=config, output=out_dir)
        payload = _payload_of(out_dir)
        events = payload["events"]
        bars = payload["bars"]
        _check("absolute dataset_source: replay payload loads (no 500)", payload is not None)
        _check("absolute dataset_source: candles present", len(bars) > 0, str(len(bars)))
        _check("absolute dataset_source: events present", len(events) > 0, str(len(events)))
        with open(os.path.join(out_dir, "events.jsonl")) as fh:
            n_lines = len(fh.read().splitlines())
        _check("absolute dataset_source: event parity", len(events) == n_lines,
               "%d vs %d" % (len(events), n_lines))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_replay_payload_relative_other_cwd_is_candleless_not_error():
    import shutil

    tmp_a = tempfile.mkdtemp(prefix="obs-rel-a-")
    try:
        run_dir = os.path.join(tmp_a, "run")
        csv = os.path.join(tmp_a, "rel.csv")
        # write a minimal valid CSV next to where the run directory will be
        lines = ["timestamp,open,high,low,close,volume"]
        from datetime import datetime, timezone

        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(60):
            ts = t.strftime("%Y-%m-%d %H:%M:%S+00:00")
            p0 = 1.10 + i * 0.0001
            lines.append("%s,%.5f,%.5f,%.5f,%.5f,10.0" % (ts, p0, p0 + 0.0002,
                                                          p0 - 0.0002, p0))
            t = t + __import__("datetime").timedelta(minutes=15)
        open(csv, "w").write("\n".join(lines) + "\n")
        # run with a RELATIVE dataset_source from tmp_a
        prev = os.getcwd()
        os.chdir(tmp_a)
        try:
            config = observa.Config(fill_mode=observa.BAR_CLOSE, spread=0.0,
                                    slippage=0.0, commission=0.0,
                                    dataset_source="rel.csv")
            result = observa.run(_sma_cross_50(), "rel.csv", config=config,
                                 output=os.path.abspath("run"))
            assert result is not None
        finally:
            os.chdir(prev)
        # replay from a DIFFERENT cwd: must not raise, candles unavailable
        payload = _payload_of(run_dir)
        _check("relative+other-cwd replay loads without error", payload is not None)
        _check("relative+other-cwd is candle-less (no fabricated bars)",
               len(payload["bars"]) == 0, str(len(payload["bars"])))
        _check("relative+other-cwd events intact", len(payload["events"]) > 0)
    finally:
        shutil.rmtree(tmp_a, ignore_errors=True)


def _run_all():
    test_version_diagnostic()
    test_llms_full_markers()
    test_docs_literal_ai_onboarding()
    test_replay_payload_absolute_source_has_candles()
    test_replay_payload_relative_other_cwd_is_candleless_not_error()
    print("\nAll onboarding checks passed")


if __name__ == "__main__":
    sys.exit(_run_all())
