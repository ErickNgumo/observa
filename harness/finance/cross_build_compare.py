#!/usr/bin/env python
"""Cross-build comparison: released Observa 0.1.6 vs the OBS-TRUST-01..03 build.

Runs a battery of VALID strategy/data cases with whichever interpreter executes
it, and stores each case's canonical artifacts plus a digest of everything the
strategy observed. A second mode compares two such output trees.

    <released-python> cross_build_compare.py run  OUT_REL
    <fixed-python>    cross_build_compare.py run  OUT_FIX
    python            cross_build_compare.py compare OUT_REL OUT_FIX

Compared per case (all must be equal):
  * run status (completed / error code)
  * events.jsonl  - byte-identical
  * metrics.json  - byte-identical
  * run.json      - byte-identical
  * observation digest - sha256 over, for every bar, the `bar` dict and the
    full `history` (as a list of dicts) the strategy received, with the NEW key
    `timestamp_ms` removed (it is reported separately as an additive change).
  * signal digest - sha256 over every signal list the strategy returned.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fx_bars(n=600, seed=7, start=1.1000, step_minutes=15):
    """EURUSD-like 15-minute bars, valid OHLC, some opening gaps."""
    rng = random.Random(seed)
    out = []
    t0 = _dt.datetime(2024, 3, 4, tzinfo=_dt.timezone.utc)
    prev = start
    for i in range(n):
        o = round(prev + rng.gauss(0, 0.00025), 5)
        c = round(o + rng.gauss(0, 0.0009), 5)
        h = round(max(o, c) + abs(rng.gauss(0, 0.0004)), 5)
        l = round(min(o, c) - abs(rng.gauss(0, 0.0004)), 5)
        ts = t0 + _dt.timedelta(minutes=step_minutes * i)
        out.append({"timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": o, "high": h, "low": l, "close": c,
                    "volume": float(rng.randint(0, 500))})  # includes zero volume
        prev = c
    return out


def variant(bars, kind):
    out = []
    for b in bars:
        b2 = dict(b)
        dt = _dt.datetime.strptime(b["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        if kind == "plus00":
            b2["timestamp"] = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        elif kind == "space":
            b2["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
        elif kind == "epoch_int":
            b2["timestamp"] = int(dt.timestamp())
        elif kind == "epoch_float_whole":
            b2["timestamp"] = float(dt.timestamp())
        elif kind == "no_volume":
            b2.pop("volume")
        elif kind == "volume_none":
            b2["volume"] = None
        out.append(b2)
    return out


def write_csv(bars, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in bars:
            dt = _dt.datetime.strptime(b["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
            w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S+00:00"), b["open"], b["high"],
                        b["low"], b["close"], b["volume"]])


# ---------------------------------------------------------------------------
# Recording wrapper
# ---------------------------------------------------------------------------

class Recorder:
    """Wraps a strategy; hashes everything observed and returned."""

    def __init__(self, inner, full_history_every=1):
        self.inner = inner
        self.obs = hashlib.sha256()
        self.sig = hashlib.sha256()
        self.full_every = full_history_every
        self.n = 0
        self.saw_timestamp_ms = None
        self.__class__ = type(inner.__class__.__name__, (Recorder,), {})

    def initialize(self, params=None):
        if hasattr(self.inner, "initialize"):
            self.inner.initialize(params)

    def on_bar(self, bar, portfolio, history):
        self.saw_timestamp_ms = "timestamp_ms" in bar
        b = {k: v for k, v in bar.items() if k != "timestamp_ms"}
        self.obs.update(json.dumps(b, sort_keys=True).encode())
        self.obs.update(json.dumps(portfolio, sort_keys=True, default=str).encode())
        if self.n % self.full_every == 0:
            hl = [{k: v for k, v in h.items() if k != "timestamp_ms"} for h in history]
            self.obs.update(json.dumps(hl, sort_keys=True).encode())
        else:
            self.obs.update(str(len(history)).encode())
        self.n += 1
        out = self.inner.on_bar(bar, portfolio, history)
        self.sig.update(json.dumps(out, sort_keys=True, default=str).encode())
        return out

    def teardown(self):
        if hasattr(self.inner, "teardown"):
            self.inner.teardown()


# ---------------------------------------------------------------------------
# Strategies (valid under BOTH builds: canonical keys, list returns)
# ---------------------------------------------------------------------------

class SmaCross:
    """SMA cross with SL/TP; touches history via slicing and negative indexing."""

    def initialize(self, params=None):
        p = params or {}
        self.fast, self.slow = int(p.get("fast", 10)), int(p.get("slow", 30))
        self.lots = float(p.get("lots", 1.0))

    def on_bar(self, bar, portfolio, history):
        if len(history) < self.slow + 1:
            return []
        closes = [h["close"] for h in history[-(self.slow + 1):]] + [bar["close"]]
        fast = sum(closes[-self.fast:]) / self.fast
        slow = sum(closes[-self.slow:]) / self.slow
        pf = sum(closes[-self.fast - 1:-1]) / self.fast
        ps = sum(closes[-self.slow - 1:-1]) / self.slow
        prev_close = history[-1]["close"]
        out = []
        longs = [p for p in portfolio["open_positions"] if p["direction"] == "Buy"]
        shorts = [p for p in portfolio["open_positions"] if p["direction"] == "Sell"]
        if pf <= ps and fast > slow:
            for p in shorts:
                out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "x up"})
            if not longs:
                out.append({"direction": "buy", "size": self.lots, "sl": round(bar["close"] - 0.0030, 5),
                            "tp": round(bar["close"] + 0.0060, 5), "reason": f"cross up {prev_close}"})
        elif pf >= ps and fast < slow:
            for p in longs:
                out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "x dn"})
            if not shorts:
                out.append({"direction": "sell", "size": self.lots, "sl": round(bar["close"] + 0.0030, 5),
                            "tp": round(bar["close"] - 0.0060, 5), "reason": "cross down"})
        return out


class HistoryHeavy:
    """Iterates the FULL history every bar (iteration, reversed, index, slices,
    `in`, count) and trades Donchian breakouts with STOP entries and LIMIT
    pullbacks, hedged, with SL/TP."""

    def initialize(self, params=None):
        self.n = 20

    def on_bar(self, bar, portfolio, history):
        if len(history) < self.n:
            return []
        all_mean = sum(h["close"] for h in history) / len(history)          # iteration
        last_rev = [h["close"] for h in reversed(history)][: self.n]          # reversed
        hi = max(h["high"] for h in history[-self.n:])                        # slice
        lo = min(history[i]["low"] for i in range(-self.n, 0))                # negative index
        first = history[0]
        _ = (first in history, history.index(first) if hasattr(history, "index") else 0)
        drift = last_rev[0] - all_mean
        out = []
        if len(portfolio["open_positions"]) < 3 and len(history) % 7 == 0:
            out.append({"direction": "buy", "order_type": "stop", "size": 0.5,
                        "price": round(hi + 0.0001, 5), "sl": round(lo, 5),
                        "tp": round(hi + (hi - lo), 5), "reason": f"donchian stop {drift:.6f}"})
            out.append({"direction": "sell", "order_type": "limit", "size": 0.3,
                        "price": round(hi, 5), "sl": round(hi + 0.0040, 5),
                        "tp": round(lo, 5), "reason": "fade at channel top"})
        for p in portfolio["open_positions"]:
            if p["unrealised_pnl"] > 40 or len(history) % 31 == 0:
                out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"],
                            "reason": "take or time exit"})
        return out


class RandomTrader:
    """Seeded random intents of every kind (market/limit/stop, buy/sell, SL/TP,
    explicit closes of random tickets)."""

    def initialize(self, params=None):
        self.rng = random.Random(int((params or {}).get("seed", 11)))

    def on_bar(self, bar, portfolio, history):
        r = self.rng
        out = []
        c = bar["close"]
        if r.random() < 0.25 and len(portfolio["open_positions"]) < 5:
            side = r.choice(["buy", "sell"])
            kind = r.choice(["market", "market", "limit", "stop"])
            sgn = 1 if side == "buy" else -1
            sig = {"direction": side, "size": r.choice([0.1, 0.5, 1.0]), "order_type": kind,
                   "reason": f"random {kind}"}
            if kind == "limit":
                sig["price"] = round(c - sgn * 0.0005, 5)
            elif kind == "stop":
                sig["price"] = round(c + sgn * 0.0005, 5)
            if r.random() < 0.7:
                sig["sl"] = round(c - sgn * 0.0025, 5)
            if r.random() < 0.7:
                sig["tp"] = round(c + sgn * 0.0035, 5)
            out.append(sig)
        if portfolio["open_positions"] and r.random() < 0.1:
            p = r.choice(portfolio["open_positions"])
            out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"],
                        "reason": "random close"})
        return out


def load_sample_strategy():
    import observa
    path = observa.sample_strategy_path()
    spec = importlib.util.spec_from_file_location("observa_sample_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "on_bar") and obj.__module__ == mod.__name__:
            return obj, path
    raise RuntimeError("no strategy class in sample")


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

def cases(tmp):
    import observa
    import golden_ledgers as g

    out = []
    for name, sc in g.SCENARIOS.items():
        out.append((f"golden_{name}", lambda sc=sc: Recorder(g.Scripted(sc["script"])),
                    lambda sc=sc: sc["bars"], lambda sc=sc: g.make_config(sc["config"])))

    fx = fx_bars()
    for fm in ("NEXT_BAR_OPEN", "BAR_CLOSE"):
        for cm, comm, rate in (("PER_SIDE", 3.5, 0.0), ("ROUND_TRIP", 7.0, 0.00002)):
            base = dict(fill_mode=getattr(observa, fm), commission_mode=getattr(observa, cm),
                        commission=comm, commission_rate_per_unit=rate, interval="15m",
                        spread=0.00012, slippage=0.00003)
            out.append((f"sma_{fm}_{cm}", lambda: Recorder(SmaCross()), lambda: fx,
                        lambda base=base: observa.Config(params={"fast": 8, "slow": 34}, **base)))
            out.append((f"history_heavy_{fm}_{cm}", lambda: Recorder(HistoryHeavy()), lambda: fx,
                        lambda base=base: observa.Config(**base)))
            out.append((f"random_{fm}_{cm}", lambda: Recorder(RandomTrader(), full_history_every=50),
                        lambda: fx, lambda base=base: observa.Config(params={"seed": 5}, **base)))

    # same data in every accepted input form (expected identical economics)
    cfg_v = lambda: observa.Config(interval="15m", params={"fast": 8, "slow": 34})
    for kind in ("plus00", "space", "epoch_int", "epoch_float_whole", "no_volume", "volume_none"):
        out.append((f"input_{kind}", lambda: Recorder(SmaCross()),
                    lambda kind=kind: variant(fx, kind), cfg_v))
    csv_path = os.path.join(tmp, "fx.csv")
    write_csv(fx, csv_path)
    out.append(("input_csv", lambda: Recorder(SmaCross()), lambda: csv_path, cfg_v))

    # bundled sample strategy on bundled sample + demo CSVs
    def sample_case(data_path):
        def mk():
            cls, _ = load_sample_strategy()
            return Recorder(cls(), full_history_every=97)
        return mk
    out.append(("bundled_sample_m15", sample_case(None), lambda: observa.sample_data_path(),
                lambda: observa.Config(interval="15m")))
    out.append(("bundled_sample_demo", sample_case(None), lambda: observa.demo_data_path(),
                lambda: observa.Config(interval="15m", fill_mode=observa.BAR_CLOSE)))
    return out


def run_all(outdir):
    import observa
    os.makedirs(outdir, exist_ok=False)
    tmp = os.path.join(outdir, "_inputs")
    os.makedirs(tmp)
    summary = {"observa_version": observa.__version__, "has_History": hasattr(observa, "History"),
               "cases": {}}
    for name, mk_strat, mk_data, mk_cfg in cases(tmp):
        strat = mk_strat()
        rec = {"status": None}
        try:
            observa.run(strat, mk_data(), config=mk_cfg(), output=os.path.join(outdir, name))
            rec["status"] = "completed"
        except Exception as e:  # report, never hide
            rec["status"] = "error"
            rec["error_code"] = getattr(e, "code", None)
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        rec["obs_digest"] = strat.obs.hexdigest()
        rec["sig_digest"] = strat.sig.hexdigest()
        rec["bars_seen"] = strat.n
        rec["saw_timestamp_ms"] = strat.saw_timestamp_ms
        summary["cases"][name] = rec
        print(f"{name:40s} {rec['status']}")
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, sort_keys=True)


def compare(a, b):
    sa = json.load(open(os.path.join(a, "summary.json")))
    sb = json.load(open(os.path.join(b, "summary.json")))
    print(f"A: {a} (History={sa['has_History']})\nB: {b} (History={sb['has_History']})")
    passed = failed = 0

    def chk(case, label, ok, detail=""):
        nonlocal passed, failed
        print(f"{'PASS' if ok else 'FAIL'}  {case:40s} {label:22s} {detail}")
        if ok:
            passed += 1
        else:
            failed += 1

    def read(p):
        return open(p, "rb").read() if os.path.exists(p) else None

    for case in sorted(set(sa["cases"]) | set(sb["cases"])):
        ra, rb = sa["cases"].get(case), sb["cases"].get(case)
        if ra is None or rb is None:
            chk(case, "present in both", False)
            continue
        chk(case, "status", ra["status"] == rb["status"] == "completed",
            f"{ra['status']} / {rb['status']} {ra.get('error', '')} {rb.get('error', '')}")
        for fn in ("events.jsonl", "metrics.json", "run.json"):
            fa, fb = read(os.path.join(a, case, fn)), read(os.path.join(b, case, fn))
            chk(case, fn + " identical", fa is not None and fa == fb,
                "" if fa == fb else f"sizes {len(fa or b'')} vs {len(fb or b'')}")
        chk(case, "observations", ra["obs_digest"] == rb["obs_digest"] and ra["bars_seen"] == rb["bars_seen"],
            f"bars {ra['bars_seen']}/{rb['bars_seen']}")
        chk(case, "signals", ra["sig_digest"] == rb["sig_digest"])
    # within-build: every accepted input form of the same data must give the
    # same canonical events (timestamps/prices identical after parsing).
    for root, s in ((a, sa), (b, sb)):
        ref = read(os.path.join(root, "input_plus00", "events.jsonl"))
        for case in sorted(c for c in s["cases"] if c.startswith("input_")):
            ev = read(os.path.join(root, case, "events.jsonl"))
            chk(f"{os.path.basename(root)}:{case}", "events == input_plus00",
                ev is not None and ev == ref)
    print(f"\nTOTAL: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run_all(sys.argv[2])
    elif sys.argv[1] == "compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
