"""Strategy ``history`` contract and per-bar scaling (OBS-TRUST-03, issue #6).

    python python/tests/test_history_contract.py

``history`` used to be rebuilt as a fresh list of fresh dicts on every bar,
which made a run O(N^2) in bar count. It is now a read-only, list-like view
over the strictly prior bars. This test pins:

* semantics — ``len``, indexing (incl. negative), slicing (returns a list),
  iteration, ``reversed``, ``==`` with a list, ``+`` with a list, ``in``,
  ``index``/``count``, ``list(history)`` and ``isinstance(..., Sequence)``;
* causality — only strictly prior bars; a view retained from an earlier bar
  never grows (no future bars leak through a stored reference);
* isolation — the view cannot be mutated, and mutating a dict obtained from it
  never changes what later bars observe;
* economics — a history-reading strategy produces byte-identical canonical
  events to the golden digest recorded with the 0.1.6 release wheel;
* scaling — per-bar cost does not grow with the number of prior bars (ratio
  test, robust to slow CI runners).
"""
from __future__ import annotations

import collections.abc
import hashlib
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import observa

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_bars(n, minutes=60):
    out, p = [], 1.1
    for i in range(n):
        step = 0.0007 if (i * 7919) % 13 < 7 else -0.0006
        c = round(p + step, 5)
        out.append({"timestamp": (T0 + timedelta(minutes=minutes * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": p, "high": round(max(p, c) + 0.0003, 5), "low": round(min(p, c) - 0.0003, 5),
                    "close": c, "volume": float(i)})
        p = c
    return out


BARS = make_bars(60)


class Probe:
    def initialize(self, params=None):
        self.errors = []
        self.kept = []

    def fail(self, msg):
        self.errors.append(msg)

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        try:
            if not isinstance(history, collections.abc.Sequence):
                self.fail("bar %d: history is not a Sequence (%s)" % (i, type(history)))
            if i and history[-1]["close"] != BARS[i - 1]["close"]:
                self.fail("bar %d: history[-1] is not the previous bar" % i)
            if i and history[0]["timestamp"] != BARS_SEEN_TS[0]:
                self.fail("bar %d: history[0] timestamp %r" % (i, history[0]["timestamp"]))
            if any(h["close"] == bar["close"] and h["timestamp"] == bar["timestamp"] for h in history):
                self.fail("bar %d: current bar present in history" % i)
            sl = history[-5:]
            if not isinstance(sl, list) or len(sl) != min(5, i):
                self.fail("bar %d: history[-5:] is %r" % (i, type(sl)))
            if [h["close"] for h in history] != [b["close"] for b in BARS[:i]]:
                self.fail("bar %d: iteration does not match prior bars" % i)
            if [h["close"] for h in reversed(history)] != [b["close"] for b in BARS[:i]][::-1]:
                self.fail("bar %d: reversed() mismatch" % i)
            as_list = list(history)
            if history != as_list or not (history == as_list):
                self.fail("bar %d: history != list(history)" % i)
            if len(history + [bar]) != i + 1 or len([bar] + history) != i + 1:
                self.fail("bar %d: concatenation with a list" % i)
            if i:
                if history[0] not in history or history.index(history[0]) != 0 or history.count(history[0]) != 1:
                    self.fail("bar %d: in/index/count" % i)
                if history[-1].get("timestamp_ms") is None:
                    self.fail("bar %d: history bars carry no timestamp_ms" % i)
                try:
                    history[i]
                    self.fail("bar %d: history[len] did not raise IndexError" % i)
                except IndexError:
                    pass
            if i and history == tuple(as_list):
                self.fail("bar %d: history == tuple returned True (a list never equals a tuple)" % i)
            try:
                history[10 ** 30]
                self.fail("bar %d: huge index did not raise" % i)
            except IndexError:
                pass
            for attempt in ("append", "pop", "clear", "insert", "sort", "reverse", "extend", "remove"):
                if hasattr(history, attempt):
                    self.fail("bar %d: history exposes mutator %s" % (i, attempt))
            for mut in (lambda: history.__setitem__(0, {}), lambda: history.__delitem__(0)):
                try:
                    mut()
                    self.fail("bar %d: item assignment/deletion succeeded" % i)
                except (TypeError, AttributeError, IndexError):
                    pass
            if i:
                # Same semantics as the old per-bar list: identity-stable within
                # the bar, so an in-place edit is visible for the rest of THIS
                # bar (never silently lost), and never leaks into later bars.
                if history[0] is not history[0] or history[-1] is not history[i - 1]:
                    self.fail("bar %d: history items are not identity-stable within the bar" % i)
                history[0]["close"] = -999.0
                if history[0]["close"] != -999.0 or list(history)[0]["close"] != -999.0:
                    self.fail("bar %d: an in-place edit was silently lost within the bar" % i)
                import copy as _copy
                import pickle as _pickle
                for name, made in (("copy.copy", _copy.copy(history)), ("copy.deepcopy", _copy.deepcopy(history)),
                                   ("pickle", _pickle.loads(_pickle.dumps(history))), ("copy()", history.copy())):
                    if not isinstance(made, list) or len(made) != i:
                        self.fail("bar %d: %s did not produce a list of %d bars" % (i, name, i))
            self.kept.append(history)
            for j, old in enumerate(self.kept):
                if len(old) != j:
                    self.fail("bar %d: view retained at bar %d now has len %d (future leak)" % (i, j, len(old)))
                    break
        except Exception as exc:  # noqa: BLE001
            self.fail("bar %d: %s: %s" % (i, type(exc).__name__, exc))
        return []

    def teardown(self):
        pass


BARS_SEEN_TS = []


class TsProbe:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        BARS_SEEN_TS.append(bar["timestamp"])
        return []

    def teardown(self):
        pass


observa.run(TsProbe(), BARS)
p = Probe()
observa.run(p, BARS)
check("history behaves as a read-only list-like view of strictly prior bars", not p.errors, p.errors[:5])

# ── Garbage collection: a reference cycle through a view is collected ──────
import gc
import weakref


class Sentinel:
    pass


CYCLE_PROBE = []


class CycleMaker:
    """Builds view -> cached dict -> view (and dict -> iterator -> view) cycles
    whose only other member is a sentinel; the sentinel must be freed."""

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        if len(history) == 5:
            d = history[0]
            d["self"] = history
            d["it"] = iter(history)
            sentinel = Sentinel()
            d["sentinel"] = sentinel
            CYCLE_PROBE.append(weakref.ref(sentinel))
        return []

    def teardown(self):
        pass


observa.run(CycleMaker(), BARS[:10])
gc.collect()
gc.collect()
check("a reference cycle through a history view/iterator is garbage-collected",
      len(CYCLE_PROBE) == 1 and CYCLE_PROBE[0]() is None, [r() for r in CYCLE_PROBE])

# ── Economics unchanged (golden digest from the 0.1.6 release wheel) ────────

class HistoryEma:
    """Reads history every bar (SMA of the prior 20 closes) and trades crosses."""

    def initialize(self, params=None):
        self.prev = None

    def on_bar(self, bar, portfolio, history):
        if len(history) < 20:
            return []
        m = sum(h["close"] for h in history[-20:]) / 20.0
        above = bar["close"] > m
        out = []
        if self.prev is not None and above != self.prev:
            for pos in portfolio["open_positions"]:
                out.append({"direction": "close", "size": pos["size"], "ticket": pos["position_id"],
                            "reason": "flip"})
            out.append({"direction": "buy" if above else "sell", "size": 1.0, "reason": "cross of prior-20 SMA",
                        "sl": bar["close"] - 0.0008 if above else bar["close"] + 0.0008})
        self.prev = above
        return out

    def teardown(self):
        pass


# sha256 of events.jsonl for HistoryEma over make_bars(400), recorded with the
# released observa-0.1.6 wheel (before the history change). Regenerate only if
# canonical event serialization intentionally changes.
GOLDEN_EVENTS_SHA256 = "a2c8a3f0551ffb5c4ef14dff1b7c47f3dbc5b1104437f9962b913ccd3bf364a7"

with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "run")
    observa.run(HistoryEma(), make_bars(400), config=observa.Config(interval="1h"), output=out)
    raw = open(os.path.join(out, "events.jsonl"), "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    closed = raw.count(b'"type":"position_closed"')
    stops = raw.count(b'"exit_reason":"StopLoss"')
    print("golden scenario: %d positions closed (%d by stop loss)" % (closed, stops))
    check("golden scenario exercises trading (>=10 closes, >=1 stop-loss exit)", closed >= 10 and stops >= 1,
          (closed, stops))
    if "--print-golden" in sys.argv:
        print("GOLDEN", digest)
    check("history-reading strategy: events.jsonl byte-identical to the 0.1.6 golden digest",
          digest == GOLDEN_EVENTS_SHA256, digest)

# ── Scaling (issue #6 acceptance: linear in N) ──────────────────────────────

class Noop:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        return []

    def teardown(self):
        pass


def timed(n):
    data = make_bars(n, minutes=1)
    best = None
    for _ in range(2):
        t = time.perf_counter()
        observa.run(Noop(), data, config=observa.Config(interval="1m"))
        dt = time.perf_counter() - t
        best = dt if best is None else min(best, dt)
    return best


if "--skip-scaling" not in sys.argv:
    t10, t40 = timed(10_000), timed(40_000)
    ratio = t40 / t10
    # Linear scaling gives ~4x; the O(N^2) history gave ~16x. 7x leaves room
    # for noisy shared runners while still failing on any super-linear cost.
    print("scaling: 10k bars %.2fs, 40k bars %.2fs, ratio %.2f" % (t10, t40, ratio))
    check("no-op strategy runtime scales linearly (40k/10k ratio < 7)", ratio < 7.0, "ratio %.2f" % ratio)


def main():
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
