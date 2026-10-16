#!/usr/bin/env python
"""Independent reference for Observa schema-2 metrics.

Written ONLY from docs/metrics.md (and the documented execution model used in
harness/finance/golden_ledgers.py), BEFORE reading
crates/observa-metrics/src/evaluation.rs or persistence.rs::derive_metrics_json.

Provides:
  * bar generators for the ratio scenarios (S8, S9*)
  * a hand model of the end-of-bar equity for a buy-and-hold of `units`
    entered at bar 1 open with zero costs (E_0 = S; E_t = S + (C_t - C_0)*units)
  * `risk_metrics(S, E, B)` implementing the Returns/Risk tables of the spec

Running this file prints the pre-run expected values that are recorded in
metrics_expectations_prerun.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

MIN_RETURNS = 30


# ---------------------------------------------------------------------------
# Bar generators
# ---------------------------------------------------------------------------

def _ohlc(closes, first_open):
    out = []
    prev = first_open
    for c in closes:
        o = prev
        out.append((o, max(o, c) + 0.5, min(o, c) - 0.5, c))
        prev = c
    return out


def daily_path(n):
    """S8: trending + oscillating closes (rounded to 4 dp)."""
    return [round(100.0 + 0.02 * t + 3.0 * math.sin(t / 15.0), 4) for t in range(n)]


def hourly_path(n):
    """S9: oscillating closes for short intraday samples."""
    return [round(100.0 + 0.01 * t + 2.0 * math.sin(t / 5.0), 4) for t in range(n)]


def business_days(start, n):
    d = start
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def stamps(kind, n):
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)  # Wednesday
    if kind == "business_daily":
        ds = business_days(base, n)
    elif kind == "calendar_daily":
        ds = [base + timedelta(days=i) for i in range(n)]
    elif kind == "hourly":
        ds = [base + timedelta(hours=i) for i in range(n)]
    elif kind == "weekly":
        ds = [base + timedelta(weeks=i) for i in range(n)]
    elif kind == "two_daily":
        ds = [base + timedelta(days=2 * i) for i in range(n)]
    else:
        raise ValueError(kind)
    return [d.strftime("%Y-%m-%dT%H:%M:%SZ") for d in ds]


def make_bars(kind, closes):
    rows = _ohlc(closes, closes[0])
    ts = stamps(kind, len(rows))
    return [dict(timestamp=t, open=o, high=h, low=l, close=c, volume=1000.0)
            for t, (o, h, l, c) in zip(ts, rows)]


def buy_hold_equity(S, closes, units):
    """Signal at bar 0, market fill at bar 1 open (= close_0, zero costs)."""
    entry = closes[0]
    return [S] + [S + (c - entry) * units for c in closes[1:]]


# ---------------------------------------------------------------------------
# Spec formulas
# ---------------------------------------------------------------------------

def risk_metrics(S, E, B):
    n = len(E)
    out = {}
    out["net_profit"] = E[-1] - S
    out["total_return_pct"] = (E[-1] / S - 1.0) * 100.0
    years = n / B if B else None
    if B and years >= 1 and E[-1] > 0:
        out["annualised_return_pct"] = ((E[-1] / S) ** (1.0 / years) - 1.0) * 100.0
    else:
        out["annualised_return_pct"] = None
    prev = S
    rets = []
    for e in E:
        rets.append(e / prev - 1.0)
        prev = e
    ok = B and n >= MIN_RETURNS and all(e > 0 for e in E)
    if ok:
        mean = sum(rets) / n
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        sd = math.sqrt(var)
        out["annualised_volatility_pct"] = sd * math.sqrt(B) * 100.0
        out["sharpe_ratio"] = mean / sd * math.sqrt(B) if sd > 0 else None
        neg = [min(r, 0.0) for r in rets]
        dd = math.sqrt(sum(x * x for x in neg) / n)
        out["sortino_ratio"] = mean / dd * math.sqrt(B) if any(r < 0 for r in rets) else None
    else:
        out["annualised_volatility_pct"] = None
        out["sharpe_ratio"] = None
        out["sortino_ratio"] = None
    peak = S
    best = (0.0, 0.0, None, None)  # pct, amount, peak_idx(-1 => S), trough_idx
    peak_idx = -1
    run = longest = 0
    for i, e in enumerate(E):
        if e > peak:
            peak, peak_idx = e, i
        if e < peak:
            run += 1
            longest = max(longest, run)
            pct = (peak - e) / peak * 100.0
            if pct > best[0]:
                best = (pct, peak - e, peak_idx, i)
        else:
            run = 0
    out["max_drawdown_pct"] = best[0]
    out["max_drawdown_amount"] = best[1]
    out["_dd_peak_idx"] = best[2]
    out["_dd_trough_idx"] = best[3]
    rec = None
    if best[3] is not None:
        pk = S if best[2] == -1 else E[best[2]]
        for j in range(best[3] + 1, n):
            if E[j] >= pk:
                rec = j
                break
    out["_dd_recovered_idx"] = rec
    out["longest_drawdown_bars"] = longest
    out["current_drawdown_pct"] = (peak - E[-1]) / peak * 100.0
    if out["annualised_return_pct"] is not None and best[0] > 0:
        out["calmar_ratio"] = out["annualised_return_pct"] / best[0]
    else:
        out["calmar_ratio"] = None
    out["_return_periods"] = n
    out["_years"] = years
    return out


S = 10000.0
UNITS = 100.0  # 1 lot, contract_size 100


def scenario_s8():
    closes = daily_path(504)
    return closes, risk_metrics(S, buy_hold_equity(S, closes, UNITS), 252.0)


def scenario_s8_explicit():
    closes = daily_path(504)
    return closes, risk_metrics(S, buy_hold_equity(S, closes, UNITS), 260.0)


def scenario_s9_hourly(B):
    closes = hourly_path(40)
    return closes, risk_metrics(S, buy_hold_equity(S, closes, UNITS), B)


def scenario_s9_weekly():
    closes = daily_path(60)
    return closes, risk_metrics(S, buy_hold_equity(S, closes, UNITS), 52.0)


if __name__ == "__main__":
    for name, (closes, m) in [
        ("S8 daily 504 B=252", scenario_s8()),
        ("S8x daily 504 B=260 explicit", scenario_s8_explicit()),
        ("S9b hourly 40 B=8760", scenario_s9_hourly(8760.0)),
        ("S9a hourly 40 B=None", scenario_s9_hourly(None)),
        ("S9d weekly 60 B=52", scenario_s9_weekly()),
    ]:
        print(f"== {name}: C0={closes[0]} Clast={closes[-1]}")
        for k, v in m.items():
            print(f"   {k:28s} {v!r}")
