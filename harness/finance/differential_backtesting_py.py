#!/usr/bin/env python
"""Differential check: Observa vs backtesting.py (independent engine).

Supporting evidence only - agreement with another engine does not prove either
is correct.  The two engines live in SEPARATE virtualenvs:

  * this script is run with the Observa interpreter (the wheel under test);
  * backtesting.py is run as a subprocess with the interpreter given by
    --bt-python (default: $DIFF_BT_PYTHON), the same script in --bt mode.

    python harness/finance/differential_backtesting_py.py --bt-python /path/to/venv-diff/bin/python

Strategy (identical decision code in both engines, see `decide`):
  SMA(5) / SMA(20) of closes including the current bar; long/flat;
  fast crosses above slow while flat -> market buy UNITS;
  fast crosses below slow while long -> market close.
  Orders execute at the NEXT bar's open in both engines
  (Observa fill_mode=NEXT_BAR_OPEN; backtesting.py trade_on_close=False).

Model reconciliation:
  * Units: Observa contract_size=1.0, size=100 lots -> 100 units;
    backtesting.py size=100 (whole units).
  * Run A (zero cost): Observa spread=slippage=commission=0;
    backtesting.py spread=0, commission=0.  Expect identical fill bars,
    fill prices and per-trade P&L.
  * Run B (commission): both engines charge flat 2.00 + 0.01 per unit on EACH
    fill (Observa commission=2.0, commission_rate_per_unit=0.01, PER_SIDE;
    backtesting.py commission=callable(size, price) -> 2.0 + 0.01*|size|, which
    it applies at entry and at exit).  Spread/slippage stay 0.
  * Spread/slippage cannot be reconciled: backtesting.py's spread is a RELATIVE
    rate applied as price*(1 +/- spread) and it has no slippage; Observa's
    spread (half per side) and slippage are ABSOLUTE price units.  No identical
    configuration exists, so no spread/slippage differential is attempted.
  * Open position at dataset end: neither engine force-closes
    (backtesting.py finalize_trades=False); only closed trades are compared
    trade-by-trade, the open-at-end state is compared separately.

Tolerances (fixed before running): price abs 1e-9, money abs 1e-6,
trade count / bar indices exact.
"""
from __future__ import annotations

import datetime
import json
import os
import random
import subprocess
import sys
import tempfile

SEED = 20261016
N_BARS = 500
UNITS = 100
FAST, SLOW = 5, 20
START_CASH = 1_000_000.0
PRICE_TOL = 1e-9
MONEY_TOL = 1e-6
COMM_FLAT = 2.0
COMM_PER_UNIT = 0.01


def generate_bars(seed=SEED, n=N_BARS):
    rng = random.Random(seed)
    out = []
    prev_close = 100.0
    for i in range(n):
        o = round(prev_close + rng.gauss(0, 0.15), 2)
        c = round(o + rng.gauss(0, 0.6), 2)
        h = round(max(o, c) + abs(rng.gauss(0, 0.3)), 2)
        l = round(min(o, c) - abs(rng.gauss(0, 0.3)), 2)
        ts = datetime.datetime(2020, 1, 1) + datetime.timedelta(days=i)
        out.append({
            "timestamp": ts.strftime("%Y-%m-%dT00:00:00Z"),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000.0,
        })
        prev_close = c
    return out


def decide(closes, is_long):
    """Shared decision rule. closes include the current bar. Returns
    'buy', 'close' or None."""
    if len(closes) < SLOW + 1:
        return None
    fast = sum(closes[-FAST:]) / FAST
    slow = sum(closes[-SLOW:]) / SLOW
    pfast = sum(closes[-FAST - 1:-1]) / FAST
    pslow = sum(closes[-SLOW - 1:-1]) / SLOW
    if not is_long and pfast <= pslow and fast > slow:
        return "buy"
    if is_long and pfast >= pslow and fast < slow:
        return "close"
    return None


# ---------------------------------------------------------------------------
# backtesting.py side (runs inside the diff venv)
# ---------------------------------------------------------------------------

def run_bt():
    import pandas as pd
    from backtesting import Backtest, Strategy

    rows = generate_bars()
    df = pd.DataFrame({
        "Open": [r["open"] for r in rows], "High": [r["high"] for r in rows],
        "Low": [r["low"] for r in rows], "Close": [r["close"] for r in rows],
        "Volume": [r["volume"] for r in rows],
    }, index=pd.to_datetime([r["timestamp"] for r in rows]))

    class Cross(Strategy):
        def init(self):
            pass

        def next(self):
            closes = [float(x) for x in self.data.Close]
            act = decide(closes, bool(self.position) and self.position.is_long)
            if act == "buy":
                self.buy(size=UNITS)
            elif act == "close":
                self.position.close()

    out = {}
    for label, commission in (("zero_cost", 0.0),
                              ("commission", lambda size, price: COMM_FLAT + COMM_PER_UNIT * abs(size))):
        bt = Backtest(df, Cross, cash=START_CASH, spread=0.0, commission=commission,
                      margin=1.0, trade_on_close=False, hedging=False,
                      exclusive_orders=False, finalize_trades=False)
        stats = bt.run()
        tr = stats._trades
        trades = []
        for _, t in tr.iterrows():
            trades.append({
                "size": float(t["Size"]),
                "entry_bar": int(t["EntryBar"]), "exit_bar": int(t["ExitBar"]),
                "entry_price": float(t["EntryPrice"]), "exit_price": float(t["ExitPrice"]),
                "pnl_net": float(t["PnL"]),
                "commission": float(t["Commission"]) if "Commission" in tr.columns else None,
            })
        pos = stats._strategy.position
        out[label] = {
            "trades": trades,
            "open_units_at_end": float(pos.size),
            "equity_final": float(stats["Equity Final [$]"]),
        }
    json.dump(out, sys.stdout)


# ---------------------------------------------------------------------------
# Observa side
# ---------------------------------------------------------------------------

def run_observa(root):
    import observa

    rows = generate_bars()

    class Cross:
        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            closes = [h["close"] for h in history] + [bar["close"]]
            longs = [p for p in portfolio["open_positions"] if p["direction"] == "Buy"]
            act = decide(closes, bool(longs))
            if act == "buy":
                return [{"direction": "buy", "size": float(UNITS), "reason": "SMA5 crossed above SMA20"}]
            if act == "close":
                return [{"direction": "close", "size": p["size"], "ticket": p["position_id"],
                         "reason": "SMA5 crossed below SMA20"} for p in longs]
            return []

        def teardown(self):
            pass

    out = {}
    for label, (flat, rate) in (("zero_cost", (0.0, 0.0)), ("commission", (COMM_FLAT, COMM_PER_UNIT))):
        cfg = observa.Config(
            starting_balance=START_CASH, currency="USD", leverage=100.0,
            symbol="XYZUSD", base_currency="XYZ", quote_currency="USD",
            contract_size=1.0, price_decimals=2, min_quantity=1.0,
            max_quantity=1000.0, quantity_step=1.0,
            fill_mode=observa.NEXT_BAR_OPEN, spread=0.0, slippage=0.0,
            commission=flat, commission_mode=observa.PER_SIDE,
            commission_rate_per_unit=rate, interval="1d")
        d = os.path.join(root, label)
        observa.run(Cross(), rows, config=cfg, output=d)
        ev = [json.loads(l) for l in open(os.path.join(d, "events.jsonl")) if l.strip()]
        opened = {e["position_id"]: e for e in ev if e["type"] == "position_opened"}
        trades = []
        for e in ev:
            if e["type"] != "position_closed":
                continue
            o = opened[e["position_id"]]
            trades.append({
                "units": e["quantity_lots"] * 1.0,
                "entry_bar": o["bar_index"], "exit_bar": e["bar_index"],
                "entry_price": e["entry_price"], "exit_price": e["exit_price"],
                "pnl_gross": e["gross_realized_pnl"], "pnl_net": e["net_realized_pnl"],
                "commission": e["total_commission"],
            })
        done = [e for e in ev if e["type"] == "run_completed"][0]
        rej = [e for e in ev if e["type"] == "order_rejected"]
        out[label] = {"trades": trades, "open_at_end": done["open_positions_remaining"],
                      "final_equity": done["final_equity"], "final_balance": done["final_balance"],
                      "rejections": len(rej), "run_dir": d}
    return out


def main(argv):
    if "--bt" in argv:
        run_bt()
        return 0
    bt_python = os.environ.get("DIFF_BT_PYTHON")
    if "--bt-python" in argv:
        bt_python = argv[argv.index("--bt-python") + 1]
    if not bt_python:
        print("SKIP: no backtesting.py interpreter (--bt-python or DIFF_BT_PYTHON)")
        return 2
    root = tempfile.mkdtemp(prefix="observa_diff_", dir=os.environ.get("GOLDEN_RUN_ROOT"))
    obs = run_observa(root)
    proc = subprocess.run([bt_python, os.path.abspath(__file__), "--bt"],
                          capture_output=True, text=True, check=True)
    bt = json.loads(proc.stdout)

    passed = failed = 0

    def check(label, exp, act, tol):
        nonlocal passed, failed
        ok = (exp == act) if tol is None else abs(exp - act) <= tol
        print(f"{'PASS' if ok else 'FAIL'}  {label:58s} observa={exp!r:<22} backtesting.py={act!r}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"dataset: seed={SEED} bars={N_BARS} units={UNITS}; observa runs under {root}")
    for label in ("zero_cost", "commission"):
        o, b = obs[label], bt[label]
        print(f"\n== {label}: observa trades={len(o['trades'])} backtesting.py trades={len(b['trades'])}")
        check(f"{label} observa order_rejected", 0, o["rejections"], None)
        check(f"{label} closed trade count", len(o["trades"]), len(b["trades"]), None)
        for k, (ot, bt_) in enumerate(zip(o["trades"], b["trades"])):
            check(f"{label} t{k} units", ot["units"], bt_["size"], MONEY_TOL)
            check(f"{label} t{k} entry_bar", ot["entry_bar"], bt_["entry_bar"], None)
            check(f"{label} t{k} exit_bar", ot["exit_bar"], bt_["exit_bar"], None)
            check(f"{label} t{k} entry_price", ot["entry_price"], bt_["entry_price"], PRICE_TOL)
            check(f"{label} t{k} exit_price", ot["exit_price"], bt_["exit_price"], PRICE_TOL)
            check(f"{label} t{k} net P&L (price x units, less commission)",
                  ot["pnl_net"], bt_["pnl_net"], MONEY_TOL)
            if bt_["commission"] is not None:
                check(f"{label} t{k} commission", ot["commission"], bt_["commission"], MONEY_TOL)
        check(f"{label} open position units at end",
              o["open_at_end"] * float(UNITS), b["open_units_at_end"], MONEY_TOL)
        check(f"{label} final equity", o["final_equity"], b["equity_final"], MONEY_TOL)
    print(f"\nTOTAL: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
