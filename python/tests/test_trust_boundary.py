"""Trust-boundary contract (OBS-TRUST-01 / OBS-TRUST-02), installed wheel.

    python python/tests/test_trust_boundary.py

Two failure classes found by the 2026-10 trust audit
(docs/audit/2026-10-trust-audit.md):

* FC-1 — silent loss of strategy/config intent at the Python boundary. A
  misspelled signal key (``stop_loss`` for ``sl``), a bare signal dict, a
  ``None`` return or a misspelled envelope key used to complete "successfully"
  with the intent dropped. They must now fail loudly with a stable code.
* FC-2 — market data accepted or reinterpreted silently. NaN/inf prices,
  inconsistent OHLC on the Python list path, epoch milliseconds read as
  seconds, timezone-less timestamps, and an undocumented strategy-facing
  timestamp format (issue #8).

Property-based checks use Hypothesis (a test-only dependency).
"""
from __future__ import annotations

import math
import os
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


def bars(n=30, ts=None):
    out, p = [], 1.1
    for i in range(n):
        c = p + (0.001 if i % 6 < 3 else -0.001)
        t = T0 + timedelta(hours=i)
        out.append({"timestamp": ts(t) if ts else t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": p, "high": max(p, c) + 0.0005, "low": min(p, c) - 0.0005,
                    "close": c, "volume": 10.0})
        p = c
    return out


class Emit:
    """Returns ``payload`` from on_bar at bar ``at`` and [] otherwise."""

    def __init__(self, payload, at=5):
        self.payload, self.at = payload, at
        self.seen = []

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        self.seen.append(dict(bar))
        return self.payload if len(history) == self.at else []

    def teardown(self):
        pass


def outcome(strategy, data=None, config=None, **kw):
    try:
        r = observa.run(strategy, bars() if data is None else data, config=config, **kw)
        return None, r
    except Exception as exc:  # noqa: BLE001
        return exc, None


def expect_code(label, code, strategy=None, data=None, config=None, details=None):
    exc, _ = outcome(strategy if strategy is not None else Emit([]), data, config)
    got = getattr(exc, "code", None) if exc else None
    ok = got == code
    if ok and details:
        d = getattr(exc, "details", {}) or {}
        for k, v in details.items():
            if d.get(k) != v:
                ok = False
                got = "%s details[%s]=%r (want %r)" % (got, k, d.get(k), v)
    check(label, ok, "raised %r: %s" % (got, exc))
    return exc


BUY = {"direction": "buy", "size": 0.1, "reason": "test"}

# ── FC-1: signal keys ───────────────────────────────────────────────────────
for bad, hint in [("stop_loss", "sl"), ("take_profit", "tp"), ("quantity", "size"), ("qty", "size"),
                  ("sl_price", "sl"), ("limit_price", "price"), ("side", "direction"), ("type", "order_type")]:
    sig = dict(BUY)
    sig[bad] = 1.0 if bad not in ("side", "type") else "buy"
    expect_code("signal key %r is rejected (SIGNAL_FIELD_UNKNOWN, suggests %r)" % (bad, hint),
                "SIGNAL_FIELD_UNKNOWN", Emit([sig]),
                details={"field": bad, "suggestion": hint, "bar_index": 5, "signal_index": 0})

exc, r = outcome(Emit([{**BUY, "sl": 1.0, "tp": 2.0, "order_type": "market", "price": None,
                        "ticket": None}]))
check("all canonical signal keys are accepted", exc is None, exc)

exc = expect_code("unknown key error names the allowed keys", "SIGNAL_FIELD_UNKNOWN", Emit([{**BUY, "stopp": 1}]))
allowed = (getattr(exc, "details", {}) or {}).get("allowed") or []
check("allowed list is the canonical eight keys",
      sorted(allowed) == sorted(["direction", "size", "order_type", "price", "sl", "tp", "reason", "ticket"]), allowed)

# ── FC-1: on_bar return shapes ──────────────────────────────────────────────
expect_code("bare signal dict is rejected", "STRATEGY_RETURN_INVALID", Emit(dict(BUY)))
expect_code("None return is rejected", "STRATEGY_RETURN_INVALID", Emit(None, at=0))
expect_code("misspelled envelope key {'signal': [...]} is rejected", "STRATEGY_RETURN_INVALID", Emit({"signal": [BUY]}))
expect_code("envelope with signals=None is rejected", "STRATEGY_RETURN_INVALID", Emit({"signals": None}))
expect_code("tuple return is rejected", "STRATEGY_RETURN_INVALID", Emit((BUY,)))
# The documented contract: "a dict containing a 'signals' list".
expect_code("drawings-only envelope (no 'signals') is rejected", "STRATEGY_RETURN_INVALID", Emit({"drawings": []}))
for label, payload in [("[] (no action)", []), ("list of signals", [BUY]),
                       ("envelope with signals", {"signals": [BUY]}),
                       ("envelope with signals and drawings", {"signals": [BUY], "drawings": []}),
                       ("envelope with empty signals and drawings", {"signals": [], "drawings": []})]:
    exc, _ = outcome(Emit(payload))
    check("valid return accepted: " + label, exc is None, exc)

# A None return on a bar where nothing happens is the classic "forgot return".
class ForgotReturn:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        if len(history) == 3:
            return [BUY]

    def teardown(self):
        pass


exc = expect_code("implicit None on a no-action bar fails at that bar", "STRATEGY_RETURN_INVALID", ForgotReturn())
check("failure reports bar_index 0", (getattr(exc, "details", {}) or {}).get("bar_index") == 0,
      getattr(exc, "details", None))

# ── FC-1: config dict keys ──────────────────────────────────────────────────
expect_code("config dict typo 'spred' is rejected", "CONFIG_INVALID", config={"spred": 0.0},
            details={"field": "spred", "suggestion": "spread"})
expect_code("config dict typo 'fillmode' is rejected", "CONFIG_INVALID", config={"fillmode": "bar_close"},
            details={"field": "fillmode", "suggestion": "fill_mode"})
expect_code("order_model typo is rejected", "CONFIG_INVALID", config={"order_model": {"limt": False}},
            details={"field": "order_model.limt", "suggestion": "order_model.limit"})
expect_code("strategy_name of the wrong type is rejected", "CONFIG_INVALID", config={"strategy_name": 5})
full = observa.Config(params={"a": 1}).to_dict()
full.update(tick_size=0.00001, pip_size=0.0001, strategy_params=None)
exc, _ = outcome(Emit([]), config=full)
check("every documented config key is still accepted", exc is None, exc)

# ── FC-1: property — unknown keys are always loud, canonical keys never are ─
CANON = ["direction", "size", "order_type", "price", "sl", "tp", "reason", "ticket"]
extra_keys = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12).filter(lambda k: k not in CANON)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(extras=st.lists(extra_keys, max_size=3, unique=True))
def prop_unknown_keys(extras):
    sig = dict(BUY)
    for k in extras:
        sig[k] = 1.0
    exc, _ = outcome(Emit([sig]), bars(10))
    if extras:
        assert getattr(exc, "code", None) == "SIGNAL_FIELD_UNKNOWN", (extras, exc)
        assert (exc.details or {}).get("field") in extras
    else:
        assert exc is None, exc


try:
    prop_unknown_keys()
    check("property: any non-canonical signal key fails loudly; canonical keys never do", True)
except AssertionError as e:  # noqa: PERF203
    check("property: any non-canonical signal key fails loudly; canonical keys never do", False, e)

# ── FC-1: validator agrees with the engine ──────────────────────────────────
src = '''
class S:
    def initialize(self, params=None):
        pass
    def on_bar(self, bar, portfolio, history):
        return [{"direction": "buy", "size": 0.1, "stop_loss": bar["close"] - 0.01, "reason": "x"}]
    def teardown(self):
        pass
'''
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "s.py")
    open(p, "w").write(src)
    rep = observa.validate_strategy(p, smoke=True)
    codes = [e["code"] for e in rep["errors"]] if isinstance(rep, dict) else [e["code"] for e in rep.errors]
    valid = rep["valid"] if isinstance(rep, dict) else rep.valid
    check("validate-strategy --smoke treats an unknown signal key as an error", (not valid) and "SIGNAL_FIELD_UNKNOWN" in codes,
          (valid, codes))

# ── FC-2: numeric bar values ────────────────────────────────────────────────
for field in ("open", "high", "low", "close"):
    for val in (float("nan"), float("inf"), float("-inf")):
        data = bars()
        data[7][field] = val
        expect_code("list path: %s=%r rejected" % (field, val), "DATA_INVALID", data=data, details={"row": 7})
for label, mut in [("high below low", dict(high=1.0, low=2.0)),
                   ("close above high", dict(close=9.0)),
                   ("negative prices", dict(open=-1.0, low=-1.0)),
                   ("infinite volume", dict(volume=float("inf"))),
                   ("negative volume", dict(volume=-5.0))]:
    data = bars()
    data[4].update(mut)
    expect_code("list path: %s rejected" % label, "DATA_INVALID", data=data, details={"row": 4})

# NaN volume is pandas' missing-value marker: treated as missing (volume has no
# economic role), exactly like None / an empty CSV cell.
data = bars()
data[4]["volume"] = float("nan")
s = Emit([])
exc, _ = outcome(s, data)
check("list path: NaN volume is accepted as missing (volume None)",
      exc is None and s.seen[4]["volume"] is None, (exc, s.seen[4:5]))

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "nanvol.csv")
    with open(p, "w") as fh:
        fh.write("timestamp,open,high,low,close,volume\n"
                 "2025-01-01T00:00:00Z,1.1,1.2,1.0,1.1,nan\n"
                 "2025-01-01T01:00:00Z,1.1,1.2,1.0,1.1,\n")
    s = Emit([])
    exc, _ = outcome(s, p)
    check("CSV path: NaN volume and empty volume are both missing",
          exc is None and [b["volume"] for b in s.seen] == [None, None], (exc, s.seen))
    for val in ("nan", "inf"):
        p = os.path.join(d, "x_%s.csv" % val)
        with open(p, "w") as fh:
            fh.write("timestamp,open,high,low,close,volume\n"
                     "2025-01-01T00:00:00Z,1.1,1.2,1.0,1.1,1\n"
                     "2025-01-01T01:00:00Z,1.1,1.2,1.0,%s,1\n" % val)
        expect_code("CSV path: close=%s rejected with zero-based data row 1" % val,
                    "DATA_INVALID", data=p, details={"row": 1})

# ── FC-2: timestamps ────────────────────────────────────────────────────────
expect_code("epoch milliseconds are rejected (not read as seconds)", "DATA_INVALID",
            data=bars(ts=lambda t: int(t.timestamp() * 1000)))
expect_code("timezone-less ISO string rejected", "DATA_INVALID",
            data=bars(ts=lambda t: t.strftime("%Y-%m-%dT%H:%M:%S")))
expect_code("timezone-less 'YYYY-MM-DD HH:MM:SS' string rejected (as on the CSV path)", "DATA_INVALID",
            data=bars(ts=lambda t: t.strftime("%Y-%m-%d %H:%M:%S")))
expect_code("bool timestamp rejected", "DATA_INVALID", data=bars(ts=lambda t: True))
expect_code("naive datetime object rejected", "DATA_INVALID", data=bars(ts=lambda t: t.replace(tzinfo=None)))

TZ2 = timezone(timedelta(hours=2))
variants = {
    "Z string": lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "+00:00 string": lambda t: t.isoformat(),
    "+02:00 string": lambda t: t.astimezone(TZ2).isoformat(),
    "epoch seconds int": lambda t: int(t.timestamp()),
    "epoch seconds float": lambda t: float(t.timestamp()),
    "aware datetime": lambda t: t,
    "aware datetime +02:00": lambda t: t.astimezone(TZ2),
}
seen = {}
for name, fn in variants.items():
    s = Emit([])
    exc, _ = outcome(s, bars(ts=fn))
    check("timestamp input accepted: " + name, exc is None, exc)
    if exc is None:
        seen[name] = [(b["timestamp"], b.get("timestamp_ms")) for b in s.seen]

ref = seen.get("Z string")
check("every equivalent timestamp input yields the identical strategy-facing timestamp",
      ref is not None and all(v == ref for v in seen.values()), {k: v[:1] for k, v in seen.items()})
if ref:
    ts0, ms0 = ref[0]
    check("strategy-facing timestamp format is canonical 'YYYY-MM-DDTHH:MM:SS+00:00' (issue #8)",
          ts0 == "2025-01-01T00:00:00+00:00", ts0)
    check("bar['timestamp_ms'] is the integer epoch milliseconds", ms0 == int(T0.timestamp() * 1000) and isinstance(ms0, int), ms0)

s = Emit([])
outcome(s, bars(ts=lambda t: (t + timedelta(milliseconds=250)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"))
check("sub-second timestamps keep their milliseconds",
      s.seen and s.seen[0].get("timestamp_ms") == int(T0.timestamp() * 1000) + 250 and s.seen[0]["timestamp"] == "2025-01-01T00:00:00.250+00:00",
      s.seen[:1])
s = Emit([])
outcome(s, bars(ts=lambda t: t.timestamp() + 0.5))
check("fractional epoch seconds are not floored",
      s.seen and s.seen[0].get("timestamp_ms") == int(T0.timestamp() * 1000) + 500, s.seen[:1])

# ── FC-2: property — invalid bars are always rejected with the right row ────
finite = st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)
poison = st.sampled_from([float("nan"), float("inf"), -1.0, 0.0])


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(row=st.integers(min_value=0, max_value=11), field=st.sampled_from(["open", "high", "low", "close"]),
       bad=poison, ok=finite)
def prop_bad_bar(row, field, bad, ok):
    data = bars(12)
    data[row][field] = bad
    exc, _ = outcome(Emit([]), data)
    assert getattr(exc, "code", None) == "DATA_INVALID", (row, field, bad, exc)
    assert (exc.details or {}).get("row") == row, (row, exc.details)


try:
    prop_bad_bar()
    check("property: a non-finite/non-positive price anywhere is rejected at its row", True)
except AssertionError as e:
    check("property: a non-finite/non-positive price anywhere is rejected at its row", False, e)


def main():
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
