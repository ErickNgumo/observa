"""No-lookahead perturbation and determinism checks (installed wheel).

    python python/tests/test_causality.py

No lookahead. For a cut bar ``t``, the canonical history of bars ``0..t`` may
depend only on bars ``0..t``. We run a strategy on a dataset, then on copies
whose bars *after* ``t`` are changed (re-priced, truncated, or extended), and
require byte-identical canonical events up to and including the
``portfolio_snapshot`` of bar ``t``. Everything the Engine does for bar ``t``
(protective exits, resting-order fills, the strategy decision, BAR_CLOSE fills,
the end-of-bar snapshot) happens before that snapshot. Fills of orders decided
on bar ``t`` under NEXT_BAR_OPEN belong to bar ``t+1`` and are correctly
excluded. We also require the strategy's own observations (the bar dicts and
history it saw) for bars ``0..t`` to be identical.

What this does not establish: it cannot detect lookahead that is invisible in
canonical events (it compares events, not internal state), and a strategy that
reads external files can still leak future information — that is a property
of trusted user code, not of the Engine.

Determinism. Identical inputs must produce byte-identical ``events.jsonl``,
``run.json`` and ``metrics.json``.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import observa
from hypothesis import HealthCheck, given, settings, strategies as st

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def walk(n, seed):
    rng = random.Random(seed)
    out, p = [], 1.1
    for i in range(n):
        c = round(max(0.5, p + rng.gauss(0, 0.0012)), 5)
        out.append({"timestamp": (T0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": p, "high": round(max(p, c) + abs(rng.gauss(0, 0.0006)), 5),
                    "low": round(min(p, c) - abs(rng.gauss(0, 0.0006)), 5), "close": c})
        p = c
    return out


class Busy:
    """Exercises markets, limits, stops, SL/TP and explicit closes, using only
    the current bar and history; records what it observed."""

    def initialize(self, params=None):
        self.obs = []

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        last = [(h["timestamp"], h["close"]) for h in history[-3:]]
        self.obs.append((i, bar["timestamp"], bar["close"], len(history), last))
        if i < 10:
            return []
        m = sum(h["close"] for h in history[-10:]) / 10.0
        c = bar["close"]
        out = []
        ops = portfolio["open_positions"]
        if i % 7 == 0 and len(ops) < 3:
            out.append({"direction": "buy" if c < m else "sell", "size": 0.5, "reason": "mean",
                        "sl": c - 0.004 if c < m else c + 0.004, "tp": c + 0.004 if c < m else c - 0.004})
        if i % 11 == 0:
            out.append({"direction": "buy", "order_type": "limit", "price": round(c - 0.001, 5), "size": 0.2,
                        "reason": "dip"})
        if i % 13 == 0:
            out.append({"direction": "sell", "order_type": "stop", "price": round(c - 0.0015, 5), "size": 0.2,
                        "reason": "break"})
        if i % 17 == 0 and ops:
            p = ops[0]
            out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "time"})
        return out

    def teardown(self):
        pass


def run_events(bars, fill_mode):
    s = Busy()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "r")
        observa.run(s, bars, config=observa.Config(fill_mode=fill_mode, interval="1h"), output=out)
        with open(os.path.join(out, "events.jsonl"), "rb") as fh:
            lines = fh.read().splitlines()
    return lines, s.obs


def prefix_through(lines, t):
    for k, raw in enumerate(lines):
        e = json.loads(raw)
        if e.get("type") == "portfolio_snapshot" and e.get("bar_index") == t:
            return lines[:k + 1]
    raise AssertionError("no snapshot for bar %d" % t)


def perturb(bars, t, how, rng):
    head = [dict(b) for b in bars[:t + 1]]
    if how == "truncate":
        return head
    tail = [dict(b) for b in bars[t + 1:]]
    if how == "reprice":
        k = rng.choice([0.9, 0.97, 1.05, 1.2])
        for b in tail:
            for f in ("open", "high", "low", "close"):
                b[f] = round(b[f] * k, 5)
    elif how == "shock":
        if tail:
            b = tail[0]
            b["open"] = round(b["open"] * 0.95, 5)
            b["low"] = min(b["low"], b["open"])
            b["close"] = max(b["low"], min(b["close"], b["high"]))
    elif how == "extend":
        last = datetime.fromisoformat(bars[-1]["timestamp"].replace("Z", "+00:00"))
        extra = walk(50, rng.randint(0, 10**6))
        for j, b in enumerate(extra):
            b["timestamp"] = (last + timedelta(hours=j + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tail += extra
    return head + tail


BASE = walk(240, 11)
BASE_RUNS = {fm: run_events(BASE, fm) for fm in ("next_bar_open", "bar_close")}
n_closed = sum(b'"position_closed"' in l for l in BASE_RUNS["next_bar_open"][0])
check("perturbation base scenario trades (>=10 closed positions)", n_closed >= 10, n_closed)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(t=st.integers(min_value=12, max_value=200), how=st.sampled_from(["truncate", "reprice", "shock", "extend"]),
       fm=st.sampled_from(["next_bar_open", "bar_close"]), seed=st.integers(0, 10**6))
def prop_no_lookahead(t, how, fm, seed):
    base_lines, base_obs = BASE_RUNS[fm]
    lines, obs = run_events(perturb(BASE, t, how, random.Random(seed)), fm)
    assert prefix_through(lines, t) == prefix_through(base_lines, t), (t, how, fm)
    assert obs[:t + 1] == base_obs[:t + 1], (t, how, fm, "strategy observations differ")


try:
    prop_no_lookahead()
    check("property: changing bars after t never changes canonical events or observations through bar t", True)
except AssertionError as e:
    check("property: changing bars after t never changes canonical events or observations through bar t", False, e)

# The perturbation must be able to detect a leak: a deliberately leaky
# strategy (peeks at the dataset through a closure) must fail the same check.
LEAK_SOURCE = {}


class Leaky(Busy):
    def on_bar(self, bar, portfolio, history):
        i = len(history)
        nxt = LEAK_SOURCE["bars"][i + 1]["close"] if i + 1 < len(LEAK_SOURCE["bars"]) else None
        if nxt is not None and i % 5 == 0:
            # The peeked value reaches the canonical record through the reason.
            return [{"direction": "buy", "size": 0.01, "reason": "peek %r" % nxt}]
        return []


def leaky_lines(bars):
    LEAK_SOURCE["bars"] = bars
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "r")
        observa.run(Leaky(), bars, config=observa.Config(interval="1h"), output=out)
        return open(os.path.join(out, "events.jsonl"), "rb").read().splitlines()


a = leaky_lines(BASE)
c = leaky_lines([dict(x, close=x["close"]) for x in BASE[:101]] +
                [dict(x, open=round(x["open"] * 0.8, 5), high=round(x["high"] * 0.8, 5), low=round(x["low"] * 0.8, 5),
                      close=round(x["close"] * 0.8, 5)) for x in BASE[101:]])
check("perturbation check detects a deliberate future-peeking strategy",
      prefix_through(a, 100) != prefix_through(c, 100), "leak not detected")

# ── Determinism ─────────────────────────────────────────────────────────────

def digests(bars, fm):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "r")
        observa.run(Busy(), bars, config=observa.Config(fill_mode=fm, interval="1h", dataset_source="fixture"),
                    output=out)
        return {f: hashlib.sha256(open(os.path.join(out, f), "rb").read()).hexdigest()
                for f in ("events.jsonl", "run.json", "metrics.json")}


for fm in ("next_bar_open", "bar_close"):
    runs = [digests(BASE, fm) for _ in range(3)]
    check("determinism (%s): 3 identical runs give byte-identical events/run/metrics" % fm,
          all(r == runs[0] for r in runs), runs)
    if "--print-digests" in sys.argv:
        print("DIGESTS", fm, json.dumps(runs[0], sort_keys=True))


def main():
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
