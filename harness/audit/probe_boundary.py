"""Boundary probes: what happens to plausible-but-wrong strategy/data/config input?

Each probe runs a tiny backtest and records the *observed* outcome so the audit
taxonomy rests on reproduced behaviour, not on code reading alone. Probes never
assert; they print one JSON line per probe. Run with any installed observa:

    python harness/audit/probe_boundary.py > probes.jsonl
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from datetime import datetime, timedelta, timezone

import observa


def bars(n=40, start=1.1000, step=0.0010, ts_fmt="z", minutes=60):
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    p = start
    for i in range(n):
        t = t0 + timedelta(minutes=minutes * i)
        if ts_fmt == "z":
            ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif ts_fmt == "offset":
            ts = t.isoformat()
        elif ts_fmt == "epoch_s":
            ts = int(t.timestamp())
        elif ts_fmt == "epoch_ms":
            ts = int(t.timestamp() * 1000)
        else:
            ts = ts_fmt(t)
        o = p
        c = p + (step if i % 6 < 3 else -step)
        out.append({"timestamp": ts, "open": o, "high": max(o, c) + 0.0005,
                    "low": min(o, c) - 0.0005, "close": c, "volume": 100.0})
        p = c
    return out


class Once:
    """Emits `payload` on bar `at`, otherwise []."""

    def __init__(self, payload, at=5, ret=None):
        self.payload, self.at, self.ret = payload, at, ret
        self.seen = []

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        self.seen.append(bar["timestamp"])
        if len(history) == self.at:
            return self.payload
        return [] if self.ret is None else self.ret

    def teardown(self):
        pass


def outcome(strategy, data, config=None, **kw):
    try:
        r = observa.run(strategy, data, config=config, **kw)
    except Exception as exc:  # noqa: BLE001 — probes classify every outcome
        return {"raised": type(exc).__name__, "code": getattr(exc, "code", None),
                "message": str(exc)[:240]}
    ev = r.events
    kinds = {}
    for e in ev:
        k = e.get("type") or e.get("payload", {}).get("type") or next(iter(e.get("payload", {})), "?")
        kinds[k] = kinds.get(k, 0) + 1
    rejections = [e for e in ev if "rejected" in json.dumps(e).lower() and "order_rejected" in json.dumps(e)]
    opened = [e for e in ev if "position_opened" in json.dumps(e)]
    sl_tp = []
    for e in opened:
        s = json.dumps(e)
        sl_tp.append(s[:400])
    return {"raised": None, "trades": len(r.trades), "orders": len(r.orders),
            "rejections": len(rejections),
            "rejection_msgs": [json.dumps(x)[-260:] for x in rejections[:2]],
            "positions_opened": len(opened), "opened_sample": sl_tp[:1],
            "final_equity": r.final_equity, "summary_keys": sorted(r.summary().keys()),
            "metrics_sharpe": r.metrics.get("sharpe_ratio"),
            "ann_ret": r.metrics.get("annualised_return_pct")}


def probe(name, fn):
    try:
        res = fn()
    except Exception:  # noqa: BLE001
        res = {"probe_crashed": traceback.format_exc()[-400:]}
    print(json.dumps({"probe": name, **res}, default=str))
    sys.stdout.flush()


BUY = {"direction": "buy", "size": 0.1, "reason": "probe"}

# ── Signals ────────────────────────────────────────────────────────────────
probe("S01_sl_key_typo_stop_loss", lambda: outcome(
    Once([{**BUY, "stop_loss": 1.0, "take_profit": 2.0}]), bars()))
probe("S01b_sl_canonical", lambda: outcome(
    Once([{**BUY, "sl": 1.0, "tp": 2.0}]), bars()))
probe("S02_bare_signal_dict", lambda: outcome(Once(dict(BUY)), bars()))
probe("S03_return_none_every_bar", lambda: outcome(Once(None, ret=None), bars()))
probe("S04_dict_typo_signal_key", lambda: outcome(Once({"signal": [BUY]}), bars()))
probe("S05_size_nan", lambda: outcome(Once([{**BUY, "size": float("nan")}]), bars()))
probe("S06_sl_nan", lambda: outcome(Once([{**BUY, "sl": float("nan")}]), bars()))
probe("S07_limit_without_price", lambda: outcome(
    Once([{**BUY, "order_type": "limit"}]), bars()))
probe("S08_size_key_typo_quantity", lambda: outcome(
    Once([{"direction": "buy", "quantity": 0.1}]), bars()))
probe("S09_tuple_of_signals", lambda: outcome(Once((BUY,)), bars()))
probe("S10_sl_wrong_side", lambda: outcome(Once([{**BUY, "sl": 5.0}]), bars()))
probe("S11_size_inf", lambda: outcome(Once([{**BUY, "size": float("inf")}]), bars()))
probe("S12_numpy_like_float_subclass_size", lambda: outcome(
    Once([{**BUY, "size": type("F", (float,), {})(0.1)}]), bars()))

# ── Bars / timestamps ─────────────────────────────────────────────────────
def ts_roundtrip(fmt):
    data = bars(ts_fmt=fmt)
    s = Once([])
    o = outcome(s, data)
    o["input_ts0"] = data[0]["timestamp"]
    o["seen_ts0"] = s.seen[0] if s.seen else None
    o["string_equal"] = (str(data[0]["timestamp"]) == (s.seen[0] if s.seen else None))
    return o


probe("B01_ts_Z_roundtrip", lambda: ts_roundtrip("z"))
probe("B02_ts_offset_roundtrip", lambda: ts_roundtrip("offset"))
probe("B03_ts_epoch_seconds", lambda: ts_roundtrip("epoch_s"))
probe("B04_ts_epoch_millis", lambda: ts_roundtrip("epoch_ms"))
probe("B05_ts_naive_space", lambda: ts_roundtrip(lambda t: t.strftime("%Y-%m-%d %H:%M:%S")))
probe("B06_ts_naive_T", lambda: ts_roundtrip(lambda t: t.strftime("%Y-%m-%dT%H:%M:%S")))
probe("B07_ts_fractional", lambda: ts_roundtrip(lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.250Z")))
probe("B07b_ts_datetime_obj", lambda: ts_roundtrip(lambda t: t))


def with_bar(mut, idx=10):
    data = bars()
    mut(data[idx])
    return outcome(Once([BUY]), data)


probe("B08_close_nan", lambda: with_bar(lambda b: b.__setitem__("close", float("nan"))))
probe("B09_high_below_low", lambda: with_bar(lambda b: b.update(high=1.0, low=2.0)))
probe("B10_close_above_high", lambda: with_bar(lambda b: b.update(close=b["high"] + 1)))
probe("B11_negative_price", lambda: with_bar(lambda b: b.update(open=-1.0, low=-1.0)))
probe("B12_volume_nan", lambda: with_bar(lambda b: b.__setitem__("volume", float("nan"))))
probe("B13_extra_field_dropped", lambda: (lambda s: {**outcome(s, [{**b, "feature": 7} for b in bars()]),
                                                       "bar_keys_seen": None})(Once([])))
probe("B14_duplicate_ts", lambda: (lambda d: outcome(Once([]), d[:10] + d[9:]))(bars()))
probe("B15_unsorted", lambda: (lambda d: outcome(Once([]), list(reversed(d))))(bars()))
probe("B16_capitalized_columns", lambda: outcome(Once([]), [
    {k.capitalize() if k != "timestamp" else k: v for k, v in b.items()} for b in bars()]))


def bar_keys():
    seen = {}

    class K(Once):
        def on_bar(self, bar, portfolio, history):
            seen.setdefault("keys", sorted(bar.keys()))
            return []

    outcome(K([]), [{**b, "feature": 7} for b in bars()])
    return seen


probe("B17_bar_keys_with_extra_field", bar_keys)


def history_mutation():
    lens = []

    class M(Once):
        def on_bar(self, bar, portfolio, history):
            lens.append(len(history))
            if history:
                history[0]["close"] = -999.0
                history.append({"fake": True})
                if len(history) > 2 and history[1].get("close") == -999.0:
                    lens.append("LEAK")
            return []

    o = outcome(M([]), bars(n=8))
    o["history_lens"] = lens
    return o


probe("B18_history_mutation_isolation", history_mutation)

# ── Config ─────────────────────────────────────────────────────────────────
probe("C01_config_dict_typo_spread", lambda: outcome(
    Once([BUY]), bars(), config={"spred": 0.0, "slipage": 0.0}))
probe("C02_config_dataclass_typo", lambda: (lambda: observa.Config(spred=0.0))() and {})
probe("C03_btc_prices_default_config", lambda: outcome(
    Once([{**BUY, "size": 0.01}]), bars(start=60000.0, step=50.0)))
probe("C04_interval_1m_bars_per_year_default", lambda: outcome(
    Once([BUY]), bars(minutes=1), config={"interval": "1m"}))
probe("C05_interval_1m_bars_per_year_explicit", lambda: outcome(
    Once([BUY]), bars(minutes=1), config={"interval": "1m"}, bars_per_year=252 * 24 * 60))
probe("C06_interval_mismatch_data_hourly_config_daily", lambda: outcome(
    Once([BUY]), bars(minutes=60), config={"interval": "1d"}))
probe("C07_negative_spread", lambda: outcome(Once([BUY]), bars(), config={"spread": -0.01}))
probe("C08_currency_usdt", lambda: outcome(Once([BUY]), bars(),
                                           config={"currency": "USDT", "quote_currency": "USDT"}))
probe("C09_unknown_fill_mode_typo_key", lambda: outcome(
    Once([BUY]), bars(), config={"fillmode": "bar_close"}))

# ── Close / rejections visibility ─────────────────────────────────────────
def close_mismatch():
    class C(Once):
        def on_bar(self, bar, portfolio, history):
            if len(history) == 3:
                return [dict(BUY)]
            if len(history) == 8 and portfolio["open_positions"]:
                p = portfolio["open_positions"][0]
                return [{"direction": "close", "size": 1.0, "ticket": p["position_id"], "reason": "x"}]
            return []

    return outcome(C([]), bars())


probe("R01_close_size_mismatch", close_mismatch)


def close_without_ticket():
    class C(Once):
        def on_bar(self, bar, portfolio, history):
            if len(history) == 3:
                return [dict(BUY)]
            if len(history) == 8:
                return [{"direction": "close", "size": 0.1, "reason": "x"}]
            return []

    return outcome(C([]), bars())


probe("R02_close_without_ticket", close_without_ticket)
