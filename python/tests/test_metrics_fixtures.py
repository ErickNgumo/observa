"""Metrics schema 2: independently calculated fixtures (installed wheel).

    python python/tests/test_metrics_fixtures.py

Two kinds of evidence that the Rust metrics are right:

1. A hand-computed fixture: a five-bar run whose every metric is worked out by
   hand below (the arithmetic is in the comments), compared with literals.
2. An independent re-implementation of every definition in docs/metrics.md,
   written in plain Python from the canonical artifacts only (portfolio
   snapshots, position events and fills) — not from the Rust code — and
   compared metric by metric over several scenarios: intraday with an explicit
   bars_per_year, multi-year daily data, a mis-declared interval, no trades,
   costs with SL/TP and limit orders, and equity falling below zero.

It also pins the rules: annualised metrics are never computed from a guessed
intraday factor, samples shorter than one year are not annualised, every
undefined metric carries a reason, and older schema-1 runs still load.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import observa

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PASSED, FAILED = [], []
REL = 1e-9


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


def close(a, b, rel=REL):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= rel * max(1.0, abs(a), abs(b))
    return a == b


# ── 1. Hand-computed fixture ────────────────────────────────────────────────
# contract_size 1, no costs, BAR_CLOSE fills, starting balance 1000.
# closes: 100, 110, 99, 99, 120. Buy 1 unit at bar 0's close (100), close it at
# bar 3's close (99).
# End-of-bar equity: bar0 1000 (bought at the close), bar1 1010, bar2 999,
# bar3 999 (realised -1), bar4 999 (flat).
#   net_profit            = 999 - 1000                     = -1
#   total_return_pct      = (999/1000 - 1) * 100            = -0.1
#   max drawdown          : peak 1010 (bar1) -> trough 999 (bar2)
#     max_drawdown_pct    = 11/1010 * 100                   = 1.0891089108910892
#     max_drawdown_amount = 11
#     not recovered (999 < 1010)  -> recovered_at None
#     longest_drawdown_bars = bars 2,3,4 below the peak     = 3
#   current_drawdown_pct  = 11/1010 * 100
#   trades: one loss of -1 (net = gross, no commission)
#     win_rate_pct 0, avg_loss 1, profit_factor 0/1 = 0, expectancy -1,
#     largest_loss 1, max_consecutive_losses 1, avg_holding_bars 3 - 0 = 3
#     avg_win / payoff_ratio / largest_win: unavailable (no winning trades)
#   time_in_market_pct    : open at the close of bars 0,1,2 = 3/5 * 100 = 60
#   max_gross_leverage    : units*close/equity: 100/1000, 110/1010, 99/999
#                           -> 110/1010 = 0.10891089108910891
#   costs                 : all 0
#   annualised / volatility / Sharpe / Sortino / Calmar: unavailable
#     (5 daily bars < 30 returns, < 1 year)
HAND = {
    "net_profit": -1.0, "total_return_pct": -0.1,
    "max_drawdown_pct": 11 / 1010 * 100, "max_drawdown_amount": 11.0,
    "max_drawdown_recovered_at": None, "longest_drawdown_bars": 3,
    "current_drawdown_pct": 11 / 1010 * 100,
    "total_trades": 1, "winning_trades": 0, "losing_trades": 1, "breakeven_trades": 0,
    "win_rate_pct": 0.0, "avg_loss": 1.0, "profit_factor": 0.0, "expectancy": -1.0,
    "largest_loss": 1.0, "max_consecutive_losses": 1, "avg_holding_bars": 3.0,
    "avg_win": None, "payoff_ratio": None, "largest_win": None,
    "time_in_market_pct": 60.0, "max_gross_leverage": 110 / 1010,
    "commission_cost": 0.0, "spread_cost": 0.0, "slippage_cost": 0.0, "total_costs": 0.0,
    "annualised_return_pct": None, "annualised_volatility_pct": None, "sharpe_ratio": None,
    "sortino_ratio": None, "calmar_ratio": None,
}
T0 = datetime(2025, 1, 6, tzinfo=timezone.utc)


class HandStrategy:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if i == 0:
            return [{"direction": "buy", "size": 1.0, "reason": "hand fixture entry"}]
        if i == 3:
            p = portfolio["open_positions"][0]
            return [{"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "exit"}]
        return []

    def teardown(self):
        pass


hand_bars = [{"timestamp": (T0 + timedelta(days=i)).isoformat(), "open": c, "high": c, "low": c, "close": c}
             for i, c in enumerate([100.0, 110.0, 99.0, 99.0, 120.0])]
hand_cfg = observa.Config(starting_balance=1000.0, contract_size=1.0, spread=0.0, slippage=0.0,
                          fill_mode="bar_close", symbol="TEST", base_currency="TST", quote_currency="USD",
                          price_decimals=2)
hm = observa.run(HandStrategy(), hand_bars, config=hand_cfg).metrics
for k, v in HAND.items():
    check("hand fixture: %s == %r" % (k, v), close(v, hm.get(k)), hm.get(k))
for k in ("avg_win", "payoff_ratio", "largest_win", "annualised_return_pct", "sharpe_ratio"):
    check("hand fixture: %s has an unavailable reason" % k, bool((hm.get("unavailable") or {}).get(k)), hm.get("unavailable"))
check("hand fixture: daily interval resolves to 252 bars/year",
      hm["assumptions"]["bars_per_year"] == 252.0 and hm["assumptions"]["bars_per_year_source"] == "interval_default",
      hm["assumptions"])
check("hand fixture: sample block", hm["sample"]["bars"] == 5 and hm["sample"]["return_periods"] == 5
      and hm["sample"]["closed_trades"] == 1, hm["sample"])


# ── 2. Independent implementation (from docs/metrics.md) ───────────────────

def independent(result, cfg, bpy):
    """Recomputes schema-2 metrics from canonical artifacts only."""
    ev = result.events
    snaps = [e for e in ev if e["type"] == "portfolio_snapshot"]
    S = cfg["starting_balance"]
    eq = [e["equity"] for e in snaps]
    n = len(eq)
    end = eq[-1]
    out = {"net_profit": end - S, "total_return_pct": (end / S - 1) * 100}
    bases = [S] + eq[:-1]
    rets = [e / b - 1 for e, b in zip(eq, bases)]
    positive = all(e > 0 for e in eq)
    years = n / bpy if bpy else None
    out["annualised_return_pct"] = (((end / S) ** (1 / years) - 1) * 100
                                    if bpy and years >= 1 and end > 0 else None)
    ok = bpy and positive and len(rets) >= 30
    if ok:
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        dd = math.sqrt(sum(min(r, 0) ** 2 for r in rets) / len(rets))
        out["annualised_volatility_pct"] = sd * math.sqrt(bpy) * 100
        out["sharpe_ratio"] = m / sd * math.sqrt(bpy) if sd > 1e-12 else None
        out["sortino_ratio"] = m / dd * math.sqrt(bpy) if dd > 1e-12 else None
    else:
        out["annualised_volatility_pct"] = out["sharpe_ratio"] = out["sortino_ratio"] = None
    # drawdowns
    peak, mdd, amt, under, longest = S, 0.0, 0.0, 0, 0
    for e in eq:
        if e >= peak:
            peak, under = e, 0
            continue
        under += 1
        longest = max(longest, under)
        d = (peak - e) / peak * 100
        if d > mdd:
            mdd, amt = d, peak - e
    out.update(max_drawdown_pct=mdd, max_drawdown_amount=amt, longest_drawdown_bars=longest,
               current_drawdown_pct=(peak - end) / peak * 100 if end < peak else 0.0)
    out["calmar_ratio"] = (out["annualised_return_pct"] / mdd
                           if out["annualised_return_pct"] is not None and mdd > 0 else None)
    # trades
    closed = [e for e in ev if e["type"] == "position_closed"]
    opened = {e["position_id"]: e["bar_index"] for e in ev if e["type"] == "position_opened"}
    pnl = [e["net_realized_pnl"] for e in closed]
    tol = 1e-9  # documented break-even tolerance
    wins = [p for p in pnl if p > tol]
    losses = [-p for p in pnl if p < -tol]
    out.update(total_trades=len(pnl), winning_trades=len(wins), losing_trades=len(losses),
               breakeven_trades=len(pnl) - len(wins) - len(losses))
    out["win_rate_pct"] = len(wins) / len(pnl) * 100 if pnl else None
    out["avg_win"] = sum(wins) / len(wins) if wins else None
    out["avg_loss"] = sum(losses) / len(losses) if losses else None
    out["payoff_ratio"] = out["avg_win"] / out["avg_loss"] if wins and losses else None
    out["profit_factor"] = sum(wins) / sum(losses) if pnl and losses else None
    out["expectancy"] = sum(pnl) / len(pnl) if pnl else None
    out["largest_win"] = max(wins) if wins else None
    out["largest_loss"] = max(losses) if losses else None
    streak = best = 0
    for p in pnl:
        streak = streak + 1 if p < -tol else 0
        best = max(best, streak)
    out["max_consecutive_losses"] = best
    holds = [e["bar_index"] - opened[e["position_id"]] for e in closed if e["position_id"] in opened]
    out["avg_holding_bars"] = sum(holds) / len(holds) if holds else None
    # exposure
    out["time_in_market_pct"] = sum(1 for s in snaps if s["open_positions"] > 0) / n * 100
    levs = [s["used_margin"] * cfg["leverage"] / s["equity"] for s in snaps
            if s["open_positions"] > 0 and s["equity"] > 0]
    blown = any(s["open_positions"] > 0 and s["equity"] <= 0 for s in snaps)
    out["max_gross_leverage"] = max(levs) if levs and not blown else None
    # costs (runtime fills include protective SL/TP executions)
    units = lambda f: abs(f["quantity_lots"]) * cfg["contract_size"]  # noqa: E731
    out["spread_cost"] = sum(abs(f["spread_applied"]) * units(f) for f in result.fills)
    out["slippage_cost"] = sum(abs(f["slippage_applied"]) * units(f) for f in result.fills)
    out["commission_cost"] = snaps[-1]["commissions_paid"]
    out["total_costs"] = out["spread_cost"] + out["slippage_cost"] + out["commission_cost"]
    out["unrealised_pnl_end"] = result.final_equity - result.final_balance
    return out


def compare(name, result, cfg, bpy):
    exp = independent(result, cfg, bpy)
    got = result.metrics
    bad = [(k, v, got.get(k)) for k, v in exp.items() if not close(v, got.get(k))]
    check("%s: all %d metrics match the independent calculation" % (name, len(exp)), not bad, bad[:4])
    missing_reason = [k for k, v in got.items() if v is None and k not in (got.get("unavailable") or {})
                      and not k.startswith("max_drawdown_")]
    check("%s: every null metric has an unavailable reason" % name, not missing_reason, missing_reason)
    return got


def walk(n, seed, minutes, sigma=0.0012, skip_weekends=False):
    rng = random.Random(seed)
    out, p, t = [], 1.1, datetime(2020, 1, 6, tzinfo=timezone.utc)
    while len(out) < n:
        if skip_weekends and t.weekday() >= 5:
            t += timedelta(minutes=minutes)
            continue
        c = round(max(0.3, p + rng.gauss(0, sigma)), 5)
        out.append({"timestamp": t.isoformat(), "open": p, "high": round(max(p, c) + abs(rng.gauss(0, sigma / 2)), 5),
                    "low": round(min(p, c) - abs(rng.gauss(0, sigma / 2)), 5), "close": c})
        p = c
        t += timedelta(minutes=minutes)
    return out


class Mixed:
    """Markets, limits, SL/TP, shorts and explicit closes."""

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if i < 20:
            return []
        m = sum(h["close"] for h in history[-20:]) / 20
        c = bar["close"]
        ops = portfolio["open_positions"]
        out = []
        if i % 9 == 0 and len(ops) < 2:
            long = c < m
            out.append({"direction": "buy" if long else "sell", "size": 0.5, "reason": "mean",
                        "sl": c - 0.006 if long else c + 0.006, "tp": c + 0.004 if long else c - 0.004})
        if i % 23 == 0:
            out.append({"direction": "buy", "order_type": "limit", "price": round(c - 0.001, 5), "size": 0.2,
                        "reason": "dip"})
        if i % 31 == 0 and ops:
            out.append({"direction": "close", "size": ops[0]["size"], "ticket": ops[0]["position_id"], "reason": "time"})
        return out

    def teardown(self):
        pass


def run(strategy, bars, bpy=None, **cfg):
    c = observa.Config(**cfg)
    return observa.run(strategy, bars, config=c, bars_per_year=bpy), c.to_dict()


# A. The canonical 15-minute fixture with an explicit factor (252 x 96).
sys.path.insert(0, HERE)
import test_canonical_baseline as tb  # noqa: E402

from observa.samples.sample_strategy import SampleEma  # noqa: E402

res = observa.run(SampleEma(), tb.FIXTURE, config=observa.Config(dataset_source=tb.FIXTURE, **tb.CANONICAL),
                  bars_per_year=24192)
gA = compare("A canonical 15m, bars_per_year=24192", res, observa.Config(**tb.CANONICAL).to_dict(), 24192)
check("A: sample shorter than one year is not annualised; Sharpe/Sortino/volatility are",
      gA["annualised_return_pct"] is None and gA["sharpe_ratio"] is not None
      and "one year" in gA["unavailable"]["annualised_return_pct"], gA["unavailable"])
check("A: explicit factor recorded", gA["assumptions"]["bars_per_year"] == 24192
      and gA["assumptions"]["bars_per_year_source"] == "explicit", gA["assumptions"])

# B. Three years of daily weekday bars, default interval -> 252.
r, c = run(Mixed(), walk(780, 11, 1440, sigma=0.006, skip_weekends=True), spread=0.0003, commission=3.0)
gB = compare("B daily 3y, default 252", r, c, 252)
check("B: weekday daily bars resolve to the 252-day calendar",
      gB["assumptions"]["bars_per_year"] == 252 and "trading-day" in gB["assumptions"]["annualisation_note"],
      gB["assumptions"])
r, c = run(Mixed(), walk(500, 21, 1440, sigma=0.006))
gB2 = compare("B2 daily bars on every calendar day", r, c, 365)
check("B2: 7-day daily bars resolve to 365", gB2["assumptions"]["bars_per_year"] == 365, gB2["assumptions"])
r, c = run(Mixed(), walk(300, 22, 2880, sigma=0.006))
gB3 = compare("B3 bars two days apart labelled daily", r, c, None)
check("B3: annualisation refused", gB3["assumptions"]["bars_per_year"] is None, gB3["assumptions"])
check("A: short-sample warning shown next to annualised ratios",
      any("highly uncertain" in w for w in gA["warnings"]), gA["warnings"])
check("B: annualised return and Calmar available over >1 year",
      gB["annualised_return_pct"] is not None and gB["calmar_ratio"] is not None, gB["unavailable"])

# C. Hourly bars with interval left at the default '1d' -> no silent 252.
r, c = run(Mixed(), walk(400, 12, 60))
gC = compare("C hourly data, interval left at 1d", r, c, None)
check("C: annualisation refused with a spacing explanation",
      gC["assumptions"]["bars_per_year"] is None and "1 hour" in gC["unavailable"]["sharpe_ratio"],
      gC["unavailable"].get("sharpe_ratio"))

# D. Intraday interval declared, no factor.
r, c = run(Mixed(), walk(400, 13, 15), interval="15m")
gD = compare("D 15m without bars_per_year", r, c, None)
check("D: intraday never guessed", gD["sharpe_ratio"] is None and "intraday" in gD["unavailable"]["sharpe_ratio"],
      gD["unavailable"].get("sharpe_ratio"))


class Never:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        return []

    def teardown(self):
        pass


# E. No trades at all.
r, c = run(Never(), walk(300, 14, 1440, skip_weekends=True))
gE = compare("E no trades", r, c, 252)
check("E: trade metrics unavailable, risk ratios explain zero volatility",
      gE["total_trades"] == 0 and gE["win_rate_pct"] is None and gE["sharpe_ratio"] is None
      and "zero" in gE["unavailable"]["sharpe_ratio"], gE["unavailable"])


class AllIn:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        return [{"direction": "buy", "size": 5.0, "reason": "all in"}] if len(history) == 0 else []

    def teardown(self):
        pass


# F. Equity falls below zero (no margin calls are modelled).
falling = [{"timestamp": (T0 + timedelta(days=i)).isoformat(), "open": 1.2 - 0.004 * i,
            "high": 1.2 - 0.004 * i + 0.001, "low": 1.2 - 0.004 * (i + 1) - 0.001, "close": 1.2 - 0.004 * (i + 1)}
           for i in range(60)]
r, c = run(AllIn(), falling, bpy=252)
gF = compare("F equity below zero", r, c, 252)
check("F: leverage refused and a margin-call warning given once equity is not positive",
      gF["max_gross_leverage"] is None and any("margin call" in w for w in gF["warnings"]), gF["warnings"])
check("F: return ratios refused once equity is not positive",
      gF["sharpe_ratio"] is None and "zero" in gF["unavailable"]["sharpe_ratio"], gF["unavailable"].get("sharpe_ratio"))

# G. Invalid factors are rejected; conflicting factors are rejected.
for bad in (0, -5, float("nan"), float("inf")):
    try:
        observa.run(Never(), walk(40, 1, 1440), bars_per_year=bad)
        check("G: bars_per_year=%r rejected" % bad, False, "no error")
    except Exception as exc:  # noqa: BLE001
        check("G: bars_per_year=%r rejected" % bad, getattr(exc, "code", None) == "CONFIG_INVALID", exc)
try:
    observa.run(Never(), walk(40, 1, 1440), config=observa.Config(bars_per_year=252), bars_per_year=365)
    check("G: conflicting bars_per_year rejected", False, "no error")
except Exception as exc:  # noqa: BLE001
    check("G: conflicting bars_per_year rejected", getattr(exc, "code", None) == "CONFIG_INVALID", exc)

# I. An explicit factor that contradicts the data is flagged (not silently used).
r, c = run(Never(), walk(300, 31, 1440, skip_weekends=True), bpy=8760)
gI = r.metrics
check("I: bars_per_year=8760 on daily data triggers a mismatch warning",
      any("check the factor" in w for w in gI["warnings"]), gI["warnings"])

# H. Persisted metrics.json == RunResult.metrics; schema-1 runs still load.
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "run")
    r = observa.run(Mixed(), walk(300, 15, 1440, skip_weekends=True), output=out)
    on_disk = json.load(open(os.path.join(out, "metrics.json")))
    check("H: metrics.json equals RunResult.metrics", on_disk == json.loads(json.dumps(r.metrics)),
          sorted(set(on_disk) ^ set(r.metrics)))
# Produced by the released observa-0.1.6 wheel (metrics schema 1), committed.
legacy = os.path.join(HERE, "fixtures", "legacy_run_0_1_6")
pr = observa.inspect_run(legacy)
payload = observa._observa.replay_payload(legacy)
check("H: a schema-1 run (0.1.6) still loads in inspect_run and replay",
      pr.metrics.get("metrics_schema_version") == 1 and payload.get("metrics", {}).get("metrics_schema_version") == 1
      and len(payload.get("events", [])) > 0, list(pr.metrics)[:3])
summ = observa.run_summary(legacy)
check("H: run_summary works on a schema-1 run", summ["status"] == "completed" and summ["trades"] is not None, summ)


def main():
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
