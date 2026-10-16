#!/usr/bin/env python
"""Finance/QA golden checks for Observa metrics schema 2.

Expected values come from metrics_expectations_prerun.md (sha256 e973a6da...),
which was written from docs/metrics.md and the documented execution model
before any scenario was run and before the metrics implementation was read.
Ratio scenarios use metrics_reference.py (written from the spec only).

Run:  <python with the observa wheel> harness/finance/metrics/metrics_golden.py
Exit: 0 when every PASS-level check passes, 1 otherwise.
Ambiguity probes (A-n) are reported as INFO and do not affect the exit code.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics_reference as ref  # noqa: E402

import observa  # noqa: E402

MONEY_ABS = 1e-6
REL = 1e-9
ABS_SMALL = 1e-12

MONEY_KEYS = {
    "net_profit", "max_drawdown_amount", "avg_win", "avg_loss", "expectancy",
    "largest_win", "largest_loss", "commission_cost", "spread_cost",
    "slippage_cost", "total_costs", "unrealised_pnl_end", "final_balance",
    "final_equity",
}
DD_TS = ("max_drawdown_start", "max_drawdown_end", "max_drawdown_recovered_at")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def daily_bars(rows):
    return [dict(timestamp=f"2024-01-{i + 1:02d}T00:00:00Z", open=o, high=h,
                 low=l, close=c, volume=1000.0)
            for i, (o, h, l, c) in enumerate(rows)]


class Scripted:
    """Actions keyed by bar index (= len(history))."""

    def __init__(self, script):
        self.script = script

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        out = []
        for act in self.script.get(i, []):
            kind = act[0]
            if kind in ("close_all", "close_long", "close_short"):
                for pos in portfolio["open_positions"]:
                    d = pos["direction"].lower()
                    if kind == "close_long" and d != "buy":
                        continue
                    if kind == "close_short" and d != "sell":
                        continue
                    out.append({"direction": "close", "size": pos["size"],
                                "ticket": pos["position_id"],
                                "reason": f"{kind} at bar {i}"})
            else:
                direction, lots, extra = act
                sig = {"direction": direction, "size": lots,
                       "reason": f"{direction} at bar {i}"}
                sig.update(extra)
                out.append(sig)
        return out

    def teardown(self):
        pass


BASE = dict(starting_balance=10000.0, leverage=100.0, contract_size=100.0,
            currency="USD", fill_mode="next_bar_open", interval="1d")


def cfg(**kw):
    d = dict(BASE)
    d.update(kw)
    return observa.Config(**d)


class Checker:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.rows = []

    def _ok(self, key, exp, act):
        if exp is None or isinstance(exp, (str, bool, list, dict)):
            return exp == act
        if act is None or isinstance(act, (str, bool)):
            return False
        if not math.isfinite(act):
            return False
        if isinstance(exp, int) and key not in MONEY_KEYS and not isinstance(exp, float):
            return act == exp
        tol = max(MONEY_ABS if key in MONEY_KEYS else ABS_SMALL, REL * abs(exp))
        return abs(act - exp) <= tol

    def check(self, scen, key, exp, act):
        ok = self._ok(key, exp, act)
        self.passed += ok
        self.failed += not ok
        self.rows.append((scen, key, exp, act, "PASS" if ok else "FAIL"))
        if not ok:
            print(f"  FAIL {scen}.{key}: expected {exp!r} got {act!r}")
        return ok

    def info(self, scen, key, note, act):
        self.rows.append((scen, key, note, act, "INFO"))
        print(f"  INFO {scen}.{key}: {note} -> {act!r}")


ROOT = tempfile.mkdtemp(prefix="metrics_golden_")


def run(name, strategy, bars, config, **kw):
    out = os.path.join(ROOT, name)
    res = observa.run(strategy, bars, config=config, output=out, **kw)
    events = [json.loads(l) for l in Path(out, "events.jsonl").read_text().splitlines() if l.strip()]
    persisted = json.loads(Path(out, "metrics.json").read_text())
    return res, events, persisted, out


def generic_checks(ck, name, m, persisted):
    # persisted metrics.json equals the in-memory object
    ck.check(name, "persisted==result.metrics", True, persisted == m)
    # every null metric has a reason; no non-finite numbers anywhere
    unavailable = m.get("unavailable", {})
    missing = [k for k, v in m.items() if v is None and k not in DD_TS and k not in unavailable]
    ck.check(name, "null_metrics_have_reason", [], missing)
    bad = []

    def walk(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}", v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(f"{prefix}[{i}]", v)
        elif isinstance(obj, float) and not math.isfinite(obj):
            bad.append(prefix)
    walk("", m)
    ck.check(name, "no_nonfinite_values", [], bad)
    stray = [k for k in unavailable if m.get(k) is not None]
    ck.check(name, "no_reason_for_defined_metric", [], stray)


def compare(ck, name, m, bars, expected):
    for key, exp in expected.items():
        if key.startswith("sample."):
            ck.check(name, key, exp, m["sample"].get(key.split(".", 1)[1]))
        elif key.startswith("assumptions."):
            ck.check(name, key, exp, m["assumptions"].get(key.split(".", 1)[1]))
        elif key in DD_TS:
            exp_ts = None if exp is None else bars[exp]["timestamp"]
            ck.check(name, key, exp_ts, m.get(key))
        else:
            ck.check(name, key, exp, m.get(key))


def snapshot_equity(events):
    return [e["equity"] for e in events if e["type"] == "portfolio_snapshot"]


def risk_keys(r):
    keys = ["net_profit", "total_return_pct", "annualised_return_pct",
            "annualised_volatility_pct", "sharpe_ratio", "sortino_ratio",
            "max_drawdown_pct", "max_drawdown_amount", "longest_drawdown_bars",
            "current_drawdown_pct", "calmar_ratio"]
    out = {k: r[k] for k in keys}
    out["max_drawdown_start"] = 0 if r["_dd_peak_idx"] == -1 else r["_dd_peak_idx"]
    out["max_drawdown_end"] = r["_dd_trough_idx"]
    out["max_drawdown_recovered_at"] = r["_dd_recovered_idx"]
    out["sample.return_periods"] = r["_return_periods"]
    if r["_years"] is not None:
        out["sample.years"] = r["_years"]
    return out


# ---------------------------------------------------------------------------
# Hand scenarios S1..S7 (values copied from metrics_expectations_prerun.md)
# ---------------------------------------------------------------------------

S1_BARS = daily_bars([
    (100, 101, 99, 100), (100, 102, 99.5, 101), (101, 103, 100.5, 102),
    (102, 102.5, 101, 101.5), (101.5, 102, 100, 100.5), (100.5, 101, 99, 101),
    (101, 101.5, 100.5, 101.2), (101.2, 101.4, 100, 100.2),
    (101, 101.2, 100.5, 100.9), (100.9, 101, 100.8, 100.9),
])
S1_SCRIPT = {0: [("buy", 1.0, {})], 2: [("close_all",)], 3: [("sell", 1.0, {})],
             5: [("close_all",)], 6: [("buy", 1.0, {})], 7: [("close_all",)]}

HAND = {}
HAND["S1_profit_per_side"] = dict(
    bars=S1_BARS, script=S1_SCRIPT,
    config=dict(spread=0.2, slippage=0.1, commission=2.0, commission_mode="per_side"),
    expected={
        "net_profit": 98.0, "total_return_pct": 0.98,
        "annualised_return_pct": None, "annualised_volatility_pct": None,
        "sharpe_ratio": None, "sortino_ratio": None,
        "max_drawdown_pct": 194 / 10234 * 100, "max_drawdown_amount": 194.0,
        "max_drawdown_start": 4, "max_drawdown_end": 7, "max_drawdown_recovered_at": None,
        "longest_drawdown_bars": 5, "current_drawdown_pct": 136 / 10234 * 100,
        "calmar_ratio": None,
        "total_trades": 3, "winning_trades": 2, "losing_trades": 1, "breakeven_trades": 0,
        "win_rate_pct": 200 / 3, "avg_win": 81.0, "avg_loss": 64.0,
        "payoff_ratio": 1.265625, "profit_factor": 2.53125, "expectancy": 98 / 3,
        "largest_win": 156.0, "largest_loss": 64.0, "max_consecutive_losses": 1,
        "avg_holding_bars": 5 / 3, "time_in_market_pct": 50.0,
        "max_gross_leverage": 10100 / 10078,
        "commission_cost": 12.0, "spread_cost": 60.0, "slippage_cost": 60.0,
        "total_costs": 132.0, "total_costs_pct_of_starting_balance": 1.32,
        "unrealised_pnl_end": 0.0,
        "sample.bars": 10, "sample.return_periods": 10, "sample.closed_trades": 3,
        "assumptions.bars_per_year": 252.0,
        "assumptions.bars_per_year_source": "interval_default",
    })
HAND["S1b_profit_round_trip"] = dict(
    bars=S1_BARS, script=S1_SCRIPT,
    config=dict(spread=0.2, slippage=0.1, commission=2.0, commission_mode="round_trip"),
    expected={
        "net_profit": 104.0, "total_return_pct": 1.04,
        "max_drawdown_pct": 192 / 10238 * 100, "max_drawdown_amount": 192.0,
        "max_drawdown_start": 4, "max_drawdown_end": 7,
        "current_drawdown_pct": 134 / 10238 * 100, "longest_drawdown_bars": 5,
        "avg_win": 83.0, "avg_loss": 62.0, "payoff_ratio": 83 / 62,
        "profit_factor": 166 / 62, "expectancy": 104 / 3,
        "largest_win": 158.0, "largest_loss": 62.0,
        "max_gross_leverage": 10100 / 10080,
        "commission_cost": 6.0, "spread_cost": 60.0, "slippage_cost": 60.0,
        "total_costs": 126.0, "total_costs_pct_of_starting_balance": 1.26,
    })
HAND["S2_losing_open_at_end"] = dict(
    bars=daily_bars([(100, 100, 99, 99.5), (99.5, 99.8, 98, 98.5), (98.5, 99, 97, 97.5),
                     (97.5, 98, 96, 97), (97, 97.5, 95, 96), (96, 97, 95.5, 96.5)]),
    script={0: [("buy", 1.0, {})], 2: [("close_all",)], 3: [("buy", 2.0, {})]},
    config=dict(spread=0.2, slippage=0.0, commission=0.0),
    expected={
        "net_profit": -340.0, "total_return_pct": -3.4, "unrealised_pnl_end": -120.0,
        "final_balance": 9780.0, "final_equity": 9660.0,
        "max_drawdown_pct": 4.4, "max_drawdown_amount": 440.0,
        "max_drawdown_start": 0, "max_drawdown_end": 4, "max_drawdown_recovered_at": None,
        "longest_drawdown_bars": 5, "current_drawdown_pct": 3.4,
        "total_trades": 1, "winning_trades": 0, "losing_trades": 1, "breakeven_trades": 0,
        "win_rate_pct": 0.0, "avg_win": None, "payoff_ratio": None, "largest_win": None,
        "avg_loss": 220.0, "largest_loss": 220.0, "profit_factor": 0.0,
        "expectancy": -220.0, "max_consecutive_losses": 1, "avg_holding_bars": 2.0,
        "time_in_market_pct": 400 / 6, "max_gross_leverage": 19200 / 9560,
        "spread_cost": 40.0, "slippage_cost": 0.0, "commission_cost": 0.0,
        "total_costs": 40.0, "total_costs_pct_of_starting_balance": 0.4,
        "sample.closed_trades": 1, "open_positions_remaining": 1,
    })
HAND["S3_equity_below_zero"] = dict(
    bars=daily_bars([(100, 100, 100, 100), (100, 100, 95, 95), (95, 95, 90, 90),
                     (90, 90, 88, 88), (88, 92, 88, 92), (92, 92, 92, 92)]),
    script={0: [("buy", 10.0, {})], 4: [("close_all",)]},
    config=dict(spread=0.0, slippage=0.0, commission=0.0),
    expected={
        "net_profit": -8000.0, "total_return_pct": -80.0,
        "annualised_return_pct": None, "annualised_volatility_pct": None,
        "sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None,
        "max_drawdown_pct": 120.0, "max_drawdown_amount": 12000.0,
        "max_drawdown_start": 0, "max_drawdown_end": 3, "max_drawdown_recovered_at": None,
        "longest_drawdown_bars": 5, "current_drawdown_pct": 80.0,
        "total_trades": 1, "losing_trades": 1, "profit_factor": 0.0,
        "avg_loss": 8000.0, "avg_holding_bars": 4.0, "time_in_market_pct": 400 / 6,
    })
HAND["S4_only_winners"] = dict(
    bars=daily_bars([(100, 100, 100, 100), (100, 101, 100, 101), (102, 102, 101, 101),
                     (101, 103, 101, 103), (103, 104, 103, 104)]),
    script={0: [("buy", 1.0, {})], 1: [("close_all",)], 2: [("buy", 1.0, {})],
            3: [("close_all",)]},
    config=dict(spread=0.0, slippage=0.0, commission=1.0, commission_mode="per_side"),
    expected={
        "net_profit": 396.0, "total_return_pct": 3.96,
        "total_trades": 2, "winning_trades": 2, "losing_trades": 0, "breakeven_trades": 0,
        "win_rate_pct": 100.0, "avg_win": 198.0, "avg_loss": None, "payoff_ratio": None,
        "profit_factor": None, "expectancy": 198.0, "largest_win": 198.0,
        "largest_loss": None, "max_consecutive_losses": 0, "avg_holding_bars": 1.0,
        "max_drawdown_pct": 1 / 10397 * 100, "max_drawdown_amount": 1.0,
        "max_drawdown_start": 3, "max_drawdown_end": 4, "max_drawdown_recovered_at": None,
        "longest_drawdown_bars": 1, "time_in_market_pct": 40.0,
        "max_gross_leverage": 10100 / 10099,
        "commission_cost": 4.0, "spread_cost": 0.0, "slippage_cost": 0.0,
        "total_costs": 4.0, "total_costs_pct_of_starting_balance": 0.04,
    })
HAND["S5_no_trades"] = dict(
    bars=daily_bars([(100, 100, 100, 100)] * 31)  # placeholder, replaced below
    , script={}, config=dict(spread=0.0, slippage=0.0),
    expected={
        "net_profit": 0.0, "total_return_pct": 0.0, "annualised_return_pct": None,
        "annualised_volatility_pct": 0.0, "sharpe_ratio": None, "sortino_ratio": None,
        "max_drawdown_pct": 0.0, "max_drawdown_amount": 0.0,
        "max_drawdown_start": None, "max_drawdown_end": None,
        "max_drawdown_recovered_at": None, "longest_drawdown_bars": 0,
        "current_drawdown_pct": 0.0, "calmar_ratio": None,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "breakeven_trades": 0,
        "max_consecutive_losses": 0, "win_rate_pct": None, "avg_win": None,
        "avg_loss": None, "payoff_ratio": None, "profit_factor": None,
        "expectancy": None, "largest_win": None, "largest_loss": None,
        "avg_holding_bars": None, "time_in_market_pct": 0.0, "max_gross_leverage": None,
        "commission_cost": 0.0, "spread_cost": 0.0, "slippage_cost": 0.0, "total_costs": 0.0,
        "sample.bars": 40, "sample.return_periods": 40, "sample.closed_trades": 0,
    })
# 40 flat daily bars on consecutive calendar days (Jan 1 .. Feb 9)
HAND["S5_no_trades"]["bars"] = [
    dict(timestamp=t, open=100.0, high=100.0, low=100.0, close=100.0, volume=1000.0)
    for t in ref.stamps("calendar_daily", 40)]
HAND["S6_hedged"] = dict(
    bars=daily_bars([(100, 100, 100, 100), (100, 101, 99, 100.5), (101, 102, 100.5, 102),
                     (102, 103, 101, 102.5), (102, 102, 101, 101), (101, 101, 101, 101)]),
    script={0: [("buy", 1.0, {}), ("sell", 1.0, {})], 2: [("close_long",)],
            3: [("close_short",)]},
    config=dict(spread=0.2, slippage=0.1, commission=0.0),
    expected={
        "net_profit": -80.0, "total_return_pct": -0.8,
        "max_drawdown_pct": 1.1, "max_drawdown_amount": 110.0,
        "max_drawdown_start": 0, "max_drawdown_end": 3, "longest_drawdown_bars": 5,
        "current_drawdown_pct": 0.8,
        "total_trades": 2, "winning_trades": 1, "losing_trades": 1, "win_rate_pct": 50.0,
        "avg_win": 160.0, "avg_loss": 240.0, "payoff_ratio": 160 / 240,
        "profit_factor": 160 / 240, "expectancy": -40.0, "largest_win": 160.0,
        "largest_loss": 240.0, "max_consecutive_losses": 1, "avg_holding_bars": 2.5,
        "time_in_market_pct": 50.0, "max_gross_leverage": 20400 / 9960,
        "spread_cost": 40.0, "slippage_cost": 40.0, "commission_cost": 0.0,
        "total_costs": 80.0, "total_costs_pct_of_starting_balance": 0.8,
    })
HAND["S7_sl_tp_costs"] = dict(
    bars=daily_bars([(100, 100.5, 99.5, 100), (100, 100.5, 99, 99.5), (99.5, 99.6, 97.5, 98),
                     (98, 99, 97.8, 99), (99, 101, 98.9, 100.5), (100.5, 100.6, 100.4, 100.5)]),
    script={0: [("buy", 1.0, {"sl": 98.0, "tp": 105.0})],
            2: [("buy", 1.0, {"sl": 95.0, "tp": 100.0})]},
    config=dict(spread=0.2, slippage=0.1, commission=1.0, commission_mode="per_side"),
    expected={
        "net_profit": -64.0, "total_return_pct": -0.64,
        "total_trades": 2, "winning_trades": 1, "losing_trades": 1, "win_rate_pct": 50.0,
        "avg_win": 178.0, "avg_loss": 242.0, "payoff_ratio": 178 / 242,
        "profit_factor": 178 / 242, "expectancy": -32.0, "largest_win": 178.0,
        "largest_loss": 242.0, "max_consecutive_losses": 1, "avg_holding_bars": 1.0,
        "max_drawdown_pct": 2.42, "max_drawdown_amount": 242.0,
        "max_drawdown_start": 0, "max_drawdown_end": 2, "longest_drawdown_bars": 5,
        "current_drawdown_pct": 0.64, "time_in_market_pct": 100 / 3,
        "max_gross_leverage": 9900 / 9837,
        "commission_cost": 4.0, "spread_cost": 30.0, "slippage_cost": 30.0,
        "total_costs": 64.0, "total_costs_pct_of_starting_balance": 0.64,
    })


# ---------------------------------------------------------------------------
# Ratio / annualisation scenarios
# ---------------------------------------------------------------------------

def bh_strategy():
    return Scripted({0: [("buy", 1.0, {})]})


def zero_cost(**kw):
    return cfg(spread=0.0, slippage=0.0, commission=0.0, **kw)


def ratio_scenarios():
    S = ref.S
    out = []
    closes = ref.daily_path(504)
    bars = ref.make_bars("business_daily", closes)
    E = ref.buy_hold_equity(S, closes, ref.UNITS)
    out.append(("S8_daily_2y", bars, zero_cost(), {},
                dict(risk_keys(ref.risk_metrics(S, E, 252.0)),
                     **{"assumptions.bars_per_year": 252.0,
                        "assumptions.bars_per_year_source": "interval_default",
                        "total_trades": 0, "unrealised_pnl_end": E[-1] - S})))
    out.append(("S8x_daily_2y_explicit260", bars, zero_cost(), {"bars_per_year": 260.0},
                dict(risk_keys(ref.risk_metrics(S, E, 260.0)),
                     **{"assumptions.bars_per_year": 260.0,
                        "assumptions.bars_per_year_source": "explicit"})))
    hc = ref.hourly_path(40)
    hE = ref.buy_hold_equity(S, hc, ref.UNITS)
    hb = ref.make_bars("hourly", hc)
    out.append(("S9a_hourly_no_bpy", hb, zero_cost(interval="1h"), {},
                dict(risk_keys(ref.risk_metrics(S, hE, None)),
                     **{"assumptions.bars_per_year": None})))
    out.append(("S9b_hourly_bpy8760", hb, zero_cost(interval="1h"), {"bars_per_year": 8760.0},
                dict(risk_keys(ref.risk_metrics(S, hE, 8760.0)),
                     **{"assumptions.bars_per_year": 8760.0,
                        "assumptions.bars_per_year_source": "explicit"})))
    out.append(("S9c_hourly_interval_1d", hb, zero_cost(), {},
                dict(risk_keys(ref.risk_metrics(S, hE, None)),
                     **{"assumptions.bars_per_year": None})))
    out.append(("S9c2_hourly_interval_1d_bpy", hb, zero_cost(), {"bars_per_year": 8760.0},
                dict(risk_keys(ref.risk_metrics(S, hE, 8760.0)),
                     **{"assumptions.bars_per_year_source": "explicit"})))
    wc = ref.daily_path(60)
    wE = ref.buy_hold_equity(S, wc, ref.UNITS)
    out.append(("S9d_weekly_1w", ref.make_bars("weekly", wc), zero_cost(interval="1w"), {},
                dict(risk_keys(ref.risk_metrics(S, wE, 52.0)),
                     **{"assumptions.bars_per_year": 52.0,
                        "assumptions.bars_per_year_source": "interval_default"})))
    w40 = ref.daily_path(40)
    out.append(("S9e_weekly_spaced_interval_1d", ref.make_bars("weekly", w40), zero_cost(), {},
                dict(risk_keys(ref.risk_metrics(S, ref.buy_hold_equity(S, w40, ref.UNITS), None)),
                     **{"assumptions.bars_per_year": None})))
    # CHANGED in re-review (2026-10-16): pre-run expectation was B = 252 under
    # the original spec (finding A6 flagged it as a weakness). The revised
    # docs/metrics.md derives the daily default from observed calendar density
    # over spans >= 28 days: 40 consecutive calendar days (span 39 d) is ~365
    # bars per calendar year -> B = 365. Expected values recomputed with the
    # unchanged spec-only reference at B = 365.
    out.append(("S9i_calendar_daily_40", ref.make_bars("calendar_daily", w40), zero_cost(), {},
                dict(risk_keys(ref.risk_metrics(S, ref.buy_hold_equity(S, w40, ref.UNITS), 365.0)),
                     **{"assumptions.bars_per_year": 365.0,
                        "assumptions.bars_per_year_source": "interval_default"})))
    return out


# ---------------------------------------------------------------------------
# Re-review checks for the fixes (written AFTER the coordinator's change list
# and the revised docs/metrics.md; expectations derived from that spec text).
# ---------------------------------------------------------------------------

def _stamp_list(dates):
    return [d.strftime("%Y-%m-%dT%H:%M:%SZ") for d in dates]


def bars_at(stamps, closes):
    rows = ref._ohlc(closes, closes[0])
    return [dict(timestamp=t, open=o, high=h, low=l, close=c, volume=1000.0)
            for t, (o, h, l, c) in zip(stamps, rows)]


def stamps_custom(n, step_days=None, weekdays=None):
    from datetime import datetime, timedelta, timezone
    d = datetime(2020, 1, 1, tzinfo=timezone.utc)
    out = []
    while len(out) < n:
        if weekdays is None or d.weekday() in weekdays:
            out.append(d)
        d += timedelta(days=step_days or 1)
    return _stamp_list(out)


def bpy_of(bars, interval="1d", **kw):
    m = observa.run(bh_strategy(), bars, config=zero_cost(interval=interval), **kw).metrics
    return m["assumptions"]["bars_per_year"], m


def fix_checks(ck):
    S = ref.S
    print("== FIX-C1 leverage once equity <= 0")
    sc = HAND["S3_equity_below_zero"]
    m = observa.run(Scripted(sc["script"]), sc["bars"], config=cfg(**sc["config"])).metrics
    ck.check("FIX-C1", "S3 max_gross_leverage null", None, m["max_gross_leverage"])
    ck.check("FIX-C1", "S3 reason mentions zero/unbounded", True,
             "unbounded" in (m["unavailable"].get("max_gross_leverage") or ""))
    ck.check("FIX-C1", "S3 warning about non-positive equity / margin call", True,
             any("zero" in w and "margin" in w for w in m["warnings"]))
    # S3b: equity goes negative only AFTER the position is closed (gap through
    # the close fill). E: 10000, 5000 (C95), 2000 (C92), close at b3 open 85 ->
    # B = E = 10000 - 15000 = -5000, flat. Leverage defined over open bars:
    # b1 95000/5000 = 19, b2 92000/2000 = 46 -> 46; ratios null (E <= 0).
    b3b = daily_bars([(100, 100, 100, 100), (100, 100, 95, 95), (95, 95, 92, 92),
                      (85, 85, 85, 85), (85, 85, 85, 85)])
    m = observa.run(Scripted({0: [("buy", 10.0, {})], 2: [("close_all",)]}), b3b,
                    config=cfg(spread=0.0, slippage=0.0, commission=0.0)).metrics
    ck.check("FIX-C1", "S3b final_equity", -5000.0, m["final_equity"])
    ck.check("FIX-C1", "S3b max_gross_leverage (E<=0 only when flat)", 46.0, m["max_gross_leverage"])
    ck.check("FIX-C1", "S3b sharpe null", None, m["sharpe_ratio"])
    ck.check("FIX-C1", "S3b non-positive-equity warning", True,
             any("zero" in w for w in m["warnings"]))

    print("== FIX-C2 annualisation defaults")
    ck.check("FIX-C2", "S5 40 calendar days -> 365", 365.0,
             observa.run(Scripted({}), HAND["S5_no_trades"]["bars"],
                         config=cfg(spread=0.0, slippage=0.0)).metrics["assumptions"]["bars_per_year"])
    ck.check("FIX-C2", "S1 10 bars (span < 28 d) -> 252", 252.0, bpy_of(S1_BARS)[0])
    ck.check("FIX-C2", "20 calendar days (span < 28 d) -> 252", 252.0,
             bpy_of(bars_at(stamps_custom(20), ref.daily_path(20)))[0])
    ck.check("FIX-C2", "Mon-Sat 60 bars (~313/yr) -> unavailable", None,
             bpy_of(bars_at(stamps_custom(60, weekdays={0, 1, 2, 3, 4, 5}), ref.daily_path(60)))[0])
    ck.check("FIX-C2", "Mon-Fri 60 bars -> 252", 252.0,
             bpy_of(bars_at(stamps_custom(60, weekdays={0, 1, 2, 3, 4}), ref.daily_path(60)))[0])
    ck.check("FIX-C2", "2-day spacing '1d' -> unavailable (was 252)", None,
             bpy_of(ref.make_bars("two_daily", ref.daily_path(40)))[0])
    ck.check("FIX-C2", "weekly spacing 10 d with '1w' -> unavailable", None,
             bpy_of(bars_at(stamps_custom(40, step_days=10), ref.daily_path(40)), "1w")[0])
    ck.check("FIX-C2", "weekly spacing 5 d with '1w' -> 52", 52.0,
             bpy_of(bars_at(stamps_custom(40, step_days=5), ref.daily_path(40)), "1w")[0])
    for iv, kind, exp in (("d", "business_daily", 252.0), ("day", "business_daily", 252.0),
                          ("1D", "business_daily", 252.0), ("week", "weekly", 52.0),
                          ("w", "weekly", 52.0)):
        try:
            got = bpy_of(ref.make_bars(kind, ref.daily_path(60)), iv)[0]
        except Exception as exc:  # noqa: BLE001
            got = f"raised {exc}"
        ck.check("FIX-C2", f"interval spelling '{iv}'", exp, got)
    # 400 consecutive calendar days (crypto-like): B = 365, years = 400/365 >= 1
    c400 = ref.daily_path(400)
    b400 = ref.make_bars("calendar_daily", c400)
    _, m = bpy_of(b400)
    exp = risk_keys(ref.risk_metrics(S, ref.buy_hold_equity(S, c400, ref.UNITS), 365.0))
    for k in ("annualised_return_pct", "annualised_volatility_pct", "sharpe_ratio",
              "sortino_ratio", "calmar_ratio", "sample.years"):
        act = m["sample"]["years"] if k == "sample.years" else m[k]
        ck.check("FIX-C2 calendar400", k, exp[k], act)
    ck.check("FIX-C2 calendar400", "warnings empty (>= 1 year)", [], m["warnings"])
    # explicit bounds 1 .. 31,622,400
    b40 = ref.make_bars("calendar_daily", ref.daily_path(40))
    for v in (1.0, 31_622_400.0):
        try:
            got = bpy_of(b40, bars_per_year=v)[0]
        except Exception as exc:  # noqa: BLE001
            got = f"raised {exc}"
        ck.check("FIX-C2", f"explicit bpy {v} accepted", v, got)
    for v in (0.999, 31_622_401.0):
        expect_error(ck, f"FIX-C2 explicit bpy {v} rejected",
                     lambda v=v: observa.run(bh_strategy(), b40, config=zero_cost(), bars_per_year=v))

    print("== FIX-C3 cost scope")
    m = observa.run(Scripted(S1_SCRIPT), S1_BARS, config=cfg(spread=0.2, slippage=0.1)).metrics
    cs = (m["assumptions"].get("cost_scope") or "").lower()
    ck.check("FIX-C3", "cost_scope states financing/swap not modelled", True,
             "financ" in cs and "swap" in cs and "not" in cs)

    print("== FIX-C6 warnings")
    expect_w = {  # scenario -> predicate description, predicate
        "S8_daily_2y": ("[]", lambda w: w == []),
        "S8x_daily_2y_explicit260": ("[]", lambda w: w == []),
        "S9d_weekly_1w": ("[] (1.15 years)", lambda w: w == []),
        "S9a_hourly_no_bpy": ("not-annualised warning", lambda w: any(x.startswith("Not annualised") for x in w)),
        "S9c_hourly_interval_1d": ("not-annualised warning", lambda w: any(x.startswith("Not annualised") for x in w)),
        "S9e_weekly_spaced_interval_1d": ("not-annualised warning", lambda w: any(x.startswith("Not annualised") for x in w)),
        "S9b_hourly_bpy8760": ("short-sample warning", lambda w: any("uncertain" in x for x in w)),
        "S9c2_hourly_interval_1d_bpy": ("short-sample warning", lambda w: any("uncertain" in x for x in w)),
        "S9i_calendar_daily_40": ("short-sample warning", lambda w: any("uncertain" in x for x in w)),
    }
    for name, bars, config, kw, _ in ratio_scenarios():
        w = observa.run(bh_strategy(), bars, config=config, **kw).metrics["warnings"]
        desc, pred = expect_w[name]
        ck.check("FIX-C6", f"{name} warnings = {desc}", True, pred(w))
    for name, sc in HAND.items():
        m = observa.run(Scripted(sc["script"]), sc["bars"], config=cfg(**sc["config"])).metrics
        ck.check("FIX-C6", f"{name} warnings is a list", True, isinstance(m.get("warnings"), list))
        if name != "S3_equity_below_zero":
            # < 30 returns or no annualisable sample: no ratios computed, B known
            ck.check("FIX-C6", f"{name} no spurious warning", [], m["warnings"])

    print("== FIX-C8 break-even tolerance")
    # 1 unit (0.01 lot x contract 100), entry 100.1, exit 100.3, flat commission
    # 0.1/side: gross = (100.3-100.1)*1 = 0.20000000000000284 (float), net ~ 2.8e-15.
    b8 = daily_bars([(100.1, 100.1, 100.1, 100.1), (100.1, 100.2, 100.1, 100.2),
                     (100.2, 100.2, 100.2, 100.2), (100.3, 100.3, 100.3, 100.3),
                     (100.3, 100.3, 100.3, 100.3)])
    out = os.path.join(ROOT, "FIX-C8")
    m = observa.run(Scripted({0: [("buy", 0.01, {})], 2: [("close_all",)]}), b8,
                    config=cfg(spread=0.0, slippage=0.0, commission=0.1), output=out).metrics
    ev = [json.loads(l) for l in Path(out, "events.jsonl").read_text().splitlines()]
    nets = [e.get("net_realized_pnl") for e in ev if e["type"] == "position_closed"]
    ck.info("FIX-C8", "position_closed net_realized_pnl", "tiny non-zero float noise", nets)
    ck.check("FIX-C8", "probe exercises tolerance (0 < |net| < 1e-9)", True,
             bool(nets) and nets[0] is not None and 0 < abs(nets[0]) < 1e-9)
    ck.check("FIX-C8", "breakeven_trades", 1, m["breakeven_trades"])
    ck.check("FIX-C8", "winning_trades", 0, m["winning_trades"])
    ck.check("FIX-C8", "avg_win null", None, m["avg_win"])


def expect_error(ck, name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        ck.check(name, "raises", True, True)
        print(f"  ok   {name} raised {type(exc).__name__}: {str(exc)[:120]}")
        return
    ck.check(name, "raises", True, False)


def main():
    ck = Checker()
    print(f"observa {getattr(observa, '__version__', '?')} at {observa.__file__}")
    print(f"run dirs under {ROOT}")

    for name, sc in HAND.items():
        print(f"== {name}")
        res, events, persisted, _ = run(name, Scripted(sc["script"]), sc["bars"], cfg(**sc["config"]))
        m = res.metrics
        generic_checks(ck, name, m, persisted)
        compare(ck, name, m, sc["bars"], sc["expected"])
        # secondary: risk metrics recomputed from engine snapshots
        E = snapshot_equity(events)
        B = m["assumptions"].get("bars_per_year")
        if all(e > 0 for e in E):
            r = risk_keys(ref.risk_metrics(10000.0, E, B))
            for k in ("max_drawdown_pct", "max_drawdown_amount", "longest_drawdown_bars",
                      "current_drawdown_pct", "annualised_volatility_pct"):
                ck.check(name, f"snap:{k}", r[k], m.get(k))
        if name == "S3_equity_below_zero":
            lev = m.get("max_gross_leverage")
            acceptable = (lev is None and "max_gross_leverage" in m["unavailable"]) or (
                isinstance(lev, float) and math.isfinite(lev) and lev > 0)
            ck.info(name, "A1 max_gross_leverage (E<=0 bars)",
                    "null-with-reason or positive finite (46 if E<=0 bars skipped)",
                    (lev, m["unavailable"].get("max_gross_leverage")))
            ck.check(name, "A1 max_gross_leverage acceptable(not neg/inf/nan)", True, acceptable)
            ck.info(name, "A2 sample.return_periods", "undefined after E=0",
                    m["sample"].get("return_periods"))
            ck.info(name, "A2 unavailable[sharpe_ratio]", "reason text",
                    m["unavailable"].get("sharpe_ratio"))

    for name, bars, config, kw, expected in ratio_scenarios():
        print(f"== {name}")
        res, events, persisted, _ = run(name, bh_strategy(), bars, config, **kw)
        m = res.metrics
        generic_checks(ck, name, m, persisted)
        compare(ck, name, m, bars, expected)
        E = snapshot_equity(events)
        B = m["assumptions"].get("bars_per_year")
        r = risk_keys(ref.risk_metrics(10000.0, E, B))
        for k in ("annualised_return_pct", "annualised_volatility_pct", "sharpe_ratio",
                  "sortino_ratio", "max_drawdown_pct", "calmar_ratio"):
            ck.check(name, f"snap:{k}", r[k], m.get(k))
        for k in ("annualised_return_pct", "annualised_volatility_pct", "sharpe_ratio",
                  "sortino_ratio", "calmar_ratio"):
            if m.get(k) is None:
                ck.info(name, f"reason[{k}]", "", m["unavailable"].get(k))
        ck.info(name, "assumptions.annualisation_note", "", m["assumptions"].get("annualisation_note"))

    print("== S9f/S9g/S9h bars_per_year validation")
    b40 = ref.make_bars("calendar_daily", ref.daily_path(40))
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        expect_error(ck, f"S9f_run_bpy_{bad}",
                     lambda bad=bad: observa.run(bh_strategy(), b40, config=zero_cost(), bars_per_year=bad))
        expect_error(ck, f"S9f_config_bpy_{bad}",
                     lambda bad=bad: observa.run(bh_strategy(), b40, config=zero_cost(bars_per_year=bad)))
    expect_error(ck, "S9g_conflicting_bpy",
                 lambda: observa.run(bh_strategy(), b40, config=zero_cost(bars_per_year=252.0),
                                     bars_per_year=260.0))
    try:
        r = observa.run(bh_strategy(), b40, config=zero_cost(bars_per_year=252.0), bars_per_year=252.0)
        ck.check("S9h_same_bpy_twice", "assumptions.bars_per_year_source", "explicit",
                 r.metrics["assumptions"]["bars_per_year_source"])
    except Exception as exc:  # noqa: BLE001
        ck.check("S9h_same_bpy_twice", "accepted", True, f"raised {exc!r}")

    # A4 informational: exactly 2-day spacing with interval 1d
    r = observa.run(bh_strategy(), ref.make_bars("two_daily", ref.daily_path(40)), config=zero_cost())
    ck.info("A4_two_day_spacing", "bars_per_year", "boundary of 'within a factor of two'",
            (r.metrics["assumptions"].get("bars_per_year"), r.metrics["assumptions"].get("annualisation_note")))
    # A3 informational: weekly spellings
    for iv in ("1w", "1W", "1wk", "W", "weekly"):
        try:
            r = observa.run(bh_strategy(), ref.make_bars("weekly", ref.daily_path(40)), config=zero_cost(interval=iv))
            ck.info("A3_weekly_spelling", iv, "", (r.metrics["assumptions"].get("bars_per_year"),
                                                   r.metrics["assumptions"].get("bars_per_year_source")))
        except Exception as exc:  # noqa: BLE001
            ck.info("A3_weekly_spelling", iv, "", f"raised {type(exc).__name__}: {str(exc)[:80]}")

    fix_checks(ck)

    print(f"\nPASS {ck.passed}  FAIL {ck.failed}  INFO {sum(1 for r in ck.rows if r[4] == 'INFO')}")
    Path(ROOT, "results.json").write_text(json.dumps(ck.rows, default=str, indent=0))
    print(f"results table: {ROOT}/results.json")
    return 0 if ck.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
