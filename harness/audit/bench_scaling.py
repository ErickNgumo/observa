"""Scaling benchmark for per-bar overhead (issue #6).

Measures wall-clock and peak RSS of complete runs for a no-op strategy and a
strategy that reads ``history[-20:]`` every bar, at several bar counts. Each
point is repeated and the median reported. Output: one JSON line per point.

    python harness/audit/bench_scaling.py --sizes 1000 4000 10000 --repeat 3
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone


def make_bars(n):
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    p = 1.1
    for i in range(n):
        step = 0.0002 if (i * 7919) % 13 < 7 else -0.0002
        c = p + step
        out.append({"timestamp": (t0 + timedelta(minutes=i)).isoformat(),
                    "open": p, "high": max(p, c) + 0.0001, "low": min(p, c) - 0.0001,
                    "close": c})
        p = c
    return out


CHILD = r"""
import json, sys, time, resource
import observa
sys.path.insert(0, {here!r})
from bench_scaling import make_bars
n, kind = int(sys.argv[1]), sys.argv[2]

class Noop:
    def initialize(self, params=None): pass
    def on_bar(self, bar, portfolio, history): return []
    def teardown(self): pass

class Reads:
    def initialize(self, params=None): pass
    def on_bar(self, bar, portfolio, history):
        if len(history) >= 20:
            s = sum(b["close"] for b in history[-20:]) / 20.0
        return []
    def teardown(self): pass

bars = make_bars(n)
t = time.perf_counter()
observa.run(Noop() if kind == "noop" else Reads(), bars, config=observa.Config(interval="1m"))
dt = time.perf_counter() - t
print(json.dumps({{"seconds": dt, "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}))
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 4000, 10000])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--kinds", nargs="+", default=["noop", "reads"])
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    import observa
    env = {"observa": observa.__version__, "python": sys.version.split()[0],
           "platform": platform.platform(), "machine": platform.machine()}
    for kind in args.kinds:
        for n in args.sizes:
            times, rss = [], []
            timed_out = False
            for _ in range(args.repeat):
                try:
                    p = subprocess.run([sys.executable, "-c", CHILD.format(here=here), str(n), kind],
                                       capture_output=True, text=True, timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    break
                if p.returncode != 0:
                    print(json.dumps({"kind": kind, "n": n, "error": p.stderr[-400:]}))
                    break
                r = json.loads(p.stdout.strip().splitlines()[-1])
                times.append(r["seconds"])
                rss.append(r["max_rss_kb"])
            rec = {"kind": kind, "n": n, "repeat": len(times), **env}
            if times:
                rec.update(median_s=statistics.median(times), min_s=min(times), max_s=max(times),
                           us_per_bar=1e6 * statistics.median(times) / n,
                           max_rss_mb=max(rss) / 1024.0)
            if timed_out:
                rec["timed_out_after_s"] = args.timeout
            print(json.dumps(rec))
            sys.stdout.flush()
            if timed_out:
                break


if __name__ == "__main__":
    main()
