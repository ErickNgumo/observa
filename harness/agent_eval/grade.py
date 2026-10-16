"""Automatic grader for the Observa agent evaluation (see README.md).

Grades a finished task workspace from its canonical artifacts
(``run/run.json``, ``run/events.jsonl``, ``run/metrics.json``) against
expectations the grader computes **independently from the input data** and the
task rule. The grader never imports Observa except to run the official
``validate-strategy`` CLI for T05.

What the grader trusts: the Engine's own execution of fills and protective
exits (it reads *when* a position was open from canonical events). What it
checks: that the agent's decisions, protective levels, tickets, config and
reported numbers match the task rule. It therefore grades the agent, not the
Engine.

    python grade.py WORKSPACE_ROOT [--python VENV_PYTHON] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import TASK_IDS, read_csv  # noqa: E402

TOL = 1e-6


class Run:
    def __init__(self, run_dir):
        self.dir = run_dir
        self.ok = os.path.isfile(os.path.join(run_dir, "run.json"))
        self.run = {}
        self.events = []
        self.metrics = None
        if not self.ok:
            return
        with open(os.path.join(run_dir, "run.json")) as fh:
            self.run = json.load(fh)
        ev_path = os.path.join(run_dir, "events.jsonl")
        if os.path.isfile(ev_path):
            with open(ev_path) as fh:
                self.events = [json.loads(line) for line in fh if line.strip()]
        m = os.path.join(run_dir, "metrics.json")
        if os.path.isfile(m):
            with open(m) as fh:
                self.metrics = json.load(fh)

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]

    @property
    def status(self):
        return self.run.get("status")

    @property
    def bar_count(self):
        return (self.run.get("dataset") or {}).get("bar_count")

    def orders(self):
        return {e["order_seq"]: e for e in self.of("order_created")}

    def positions(self):
        """position_id -> dict(opened event, closed event or None, created_bar)."""
        orders = self.orders()
        out = {}
        for e in self.of("position_opened"):
            o = orders.get(e.get("order_seq"))
            out[e["position_id"]] = {"open": e, "close": None,
                                     "created_bar": o["created_bar"] if o else None}
        for e in self.of("position_closed"):
            if e["position_id"] in out:
                out[e["position_id"]]["close"] = e
        return out

    def open_at(self, b):
        """True when a position is open at the strategy observation of bar b
        (default NEXT_BAR_OPEN semantics: fills and closes from queued orders
        and protective exits all happen before observation)."""
        for p in self.positions().values():
            ob = p["open"]["bar_index"]
            cb = p["close"]["bar_index"] if p["close"] else math.inf
            if ob <= b < cb:
                return True
        return False


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)
    return cond


def common(ws, run, fails, bar_count=None):
    check(os.path.isfile(os.path.join(ws, "REPORT.md")), "REPORT.md missing", fails)
    if not check(run.ok, "run/run.json missing (run not persisted to ./run)", fails):
        return False
    check(run.status == "completed", "run status is %r, expected 'completed'" % run.status, fails)
    if bar_count is not None:
        check(run.bar_count == bar_count, "run covers %r bars, expected %d" % (run.bar_count, bar_count), fails)
    rej = run.of("order_rejected")
    check(not rej, "%d order_rejected events (first: %s)" % (len(rej), rej[0]["reason"] if rej else ""), fails)
    return True


def order_bars(run, side, order_type="market"):
    return sorted(o["created_bar"] for o in run.orders().values()
                  if o["side"] == side and o["order_type"] == order_type)


def levels_ok(run, closes, side, sl_off, tp_off, fails, qty=1.0):
    for pid, p in run.positions().items():
        e = p["open"]
        cb = p["created_bar"]
        if cb is None:
            fails.append("position %s has no creating order" % pid)
            continue
        c = closes[cb]
        if side == "Buy":
            exp_sl, exp_tp = c - sl_off, c + tp_off
        else:
            exp_sl, exp_tp = c + sl_off, c - tp_off
        if e.get("stop_loss") is None or abs(e["stop_loss"] - exp_sl) > TOL:
            fails.append("position at bar %d: stop_loss %r, expected %.5f" % (e["bar_index"], e.get("stop_loss"), exp_sl))
            return
        if e.get("take_profit") is None or abs(e["take_profit"] - exp_tp) > TOL:
            fails.append("position at bar %d: take_profit %r, expected %.5f" % (e["bar_index"], e.get("take_profit"), exp_tp))
            return
        if abs(e["quantity_lots"] - qty) > TOL:
            fails.append("position at bar %d: quantity %r, expected %r" % (e["bar_index"], e["quantity_lots"], qty))
            return


def report_text(ws):
    p = os.path.join(ws, "REPORT.md")
    return open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else ""


def sma(vals, i, n):
    if i + 1 < n:
        return None
    return sum(vals[i + 1 - n:i + 1]) / n


def set_diff(name, got, exp, fails):
    got, exp = sorted(got), sorted(exp)
    if got != exp:
        missing = sorted(set(exp) - set(got))[:8]
        extra = sorted(set(got) - set(exp))[:8]
        fails.append("%s mismatch: %d vs expected %d; missing %s extra %s" % (name, len(got), len(exp), missing, extra))


# ── Task graders ────────────────────────────────────────────────────────────

def g_T01(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    c = [b["close"] for b in bars]
    cross = []
    for i in range(1, len(c)):
        f0, s0, f1, s1 = sma(c, i - 1, 10), sma(c, i - 1, 30), sma(c, i, 10), sma(c, i, 30)
        if None not in (f0, s0, f1, s1) and f1 > s1 and f0 <= s0:
            cross.append(i)
    exp = [b for b in cross if not run.open_at(b)]
    check(len(exp) > 0, "grader found no expected entries (task data problem)", fails)
    set_diff("entry decision bars", order_bars(run, "Buy"), exp, fails)
    levels_ok(run, c, "Buy", 0.0050, 0.0100, fails)
    check(not order_bars(run, "Close") and not order_bars(run, "Sell"), "unexpected close/sell orders", fails)


def g_T02(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    orders = sorted(run.orders().values(), key=lambda o: o["order_seq"])
    sig = [(o["side"], o["created_bar"], round(o["quantity_lots"], 6)) for o in orders]
    check(sig == [("Buy", 10, 0.5), ("Sell", 20, 0.3), ("Close", 30, 0.5)],
          "orders were %s, expected Buy@10 0.5, Sell@20 0.3, Close@30 0.5" % sig, fails)
    pos = list(run.positions().values())
    buys = [p for p in pos if p["open"]["side"] == "Buy"]
    sells = [p for p in pos if p["open"]["side"] == "Sell"]
    if check(len(buys) == 1 and len(sells) == 1, "expected one buy and one sell position", fails):
        b, s = buys[0], sells[0]
        check(b["close"] is not None and b["close"].get("exit_reason") == "Signal" and b["close"].get("order_seq") is not None,
              "buy position was not closed by an explicit ticket close", fails)
        check(s["close"] is None, "sell position was closed; it must stay open", fails)
    done = run.of("run_completed")
    check(done and done[0]["open_positions_remaining"] == 1, "expected exactly 1 open position at end", fails)


def g_T03(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    with open(os.path.join(ws, "predictions.csv")) as fh:
        import csv
        preds = {r["timestamp"]: int(r["prediction"]) for r in csv.DictReader(fh)}
    holding, entries, exits = False, [], []
    for i, b in enumerate(bars):
        p = preds.get(b["timestamp"])
        if p == 1 and not holding:
            entries.append(i)
            holding = True
        elif p == 0 and holding:
            exits.append(i)
            holding = False
    set_diff("entry decision bars", order_bars(run, "Buy"), entries, fails)
    set_diff("exit decision bars", order_bars(run, "Close"), exits, fails)


def g_T04(ws, run, fails, py):
    if not common(ws, run, fails, 100_000):
        return
    set_diff("entry decision bars", order_bars(run, "Buy"), [i for i in range(100_000) if i % 1000 == 100], fails)
    set_diff("exit decision bars", order_bars(run, "Close"), [i for i in range(100_000) if i % 1000 == 600], fails)


def g_T05(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    c = [b["close"] for b in bars]
    exp_entries = [i for i in range(1, len(c)) if c[i] - c[i - 1] > 0.0015 and not run.open_at(i)]
    set_diff("entry decision bars", order_bars(run, "Buy"), exp_entries, fails)
    levels_ok(run, c, "Buy", 0.0030, 0.0060, fails)
    exp_exits = []
    for p in run.positions().values():
        d = p["created_bar"]
        cl = p["close"]
        if d is None or d + 24 >= len(c):
            continue
        protective_before = cl is not None and cl["exit_reason"] in ("StopLoss", "TakeProfit") and cl["bar_index"] <= d + 24
        if not protective_before:
            exp_exits.append(d + 24)
    set_diff("time-exit decision bars", order_bars(run, "Close"), exp_exits, fails)
    for e in run.of("strategy_decision"):
        if e.get("signal_count"):
            reasons = [s.get("reason", "") for s in e.get("signals", [])]
            if len(reasons) != e["signal_count"] or not all(r.strip() for r in reasons):
                fails.append("bar %d: a signal has no reason" % e["bar_index"])
                break
    cli = os.path.join(os.path.dirname(py), "observa")
    strat = os.path.join(ws, "strategy.py")
    if check(os.path.isfile(strat), "strategy.py missing", fails):
        p = subprocess.run([cli, "validate-strategy", strat, "--smoke", "--json"], capture_output=True, text=True, cwd=ws)
        check(p.returncode == 0, "validate-strategy --smoke exit %d: %s %s" % (p.returncode, p.stdout[-300:], p.stderr[-200:]), fails)


def _ema_decisions(c, run):
    ef = es = None
    entries, exits = [], []
    af, as_ = 2 / 13, 2 / 27
    for i, x in enumerate(c):
        pf, ps = ef, es
        ef = x if ef is None else af * x + (1 - af) * ef
        es = x if es is None else as_ * x + (1 - as_) * es
        if pf is None or i < 26:
            continue
        if pf <= ps and ef > es and not run.open_at(i):
            entries.append(i)
        if pf >= ps and ef < es and run.open_at(i):
            exits.append(i)
    return entries, exits


def g_T06(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "btc_h1.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    cfg = run.run.get("config", {})
    inst, acct, ex = cfg.get("instrument", {}), cfg.get("account", {}), cfg.get("execution", {})
    check(inst.get("contract_size") == 1.0, "contract_size %r, expected 1" % inst.get("contract_size"), fails)
    check(acct.get("leverage") == 1.0, "leverage %r, expected 1" % acct.get("leverage"), fails)
    check(acct.get("starting_balance") == 100000.0, "starting_balance %r" % acct.get("starting_balance"), fails)
    check(acct.get("currency") == "USD", "currency %r" % acct.get("currency"), fails)
    check(ex.get("spread") == 10.0, "spread %r, expected 10" % ex.get("spread"), fails)
    check(ex.get("slippage") == 0.0, "slippage %r, expected 0" % ex.get("slippage"), fails)
    entries, exits = _ema_decisions([b["close"] for b in bars], run)
    check(len(entries) > 0, "no entries expected (task data problem)", fails)
    set_diff("entry decision bars", order_bars(run, "Buy"), entries, fails)
    set_diff("exit decision bars", order_bars(run, "Close"), exits, fails)
    check(re.search(r"margin", report_text(ws), re.I) is not None,
          "REPORT.md does not identify the margin rejection as the cause", fails)


def _sharpe(eq, ppy, start):
    """Sharpe as defined in docs/metrics.md (metrics schema 2): per-bar
    returns from the starting balance, sample std, sqrt(bars per year)."""
    bases = [start] + eq[:-1]
    r = [e / b - 1.0 for e, b in zip(eq, bases)]
    if len(r) < 30:
        return None
    n = len(r)
    m = sum(r) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1))
    return None if sd < 1e-12 else m / sd * math.sqrt(ppy)


def g_T07(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars_5m.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    eq = [e["equity"] for e in run.of("portfolio_snapshot")]
    start = run.run.get("config", {}).get("account", {}).get("starting_balance", 10000.0)
    exp = _sharpe(eq, 252 * 288, start)
    got = (run.metrics or {}).get("sharpe_ratio")
    if check(exp is not None and got is not None, "sharpe missing (got %r, expected %r)" % (got, exp), fails):
        check(abs(got - exp) <= 1e-6 * max(1.0, abs(exp)),
              "persisted sharpe_ratio %.6f, expected %.6f (annualised with 252*288 bars/year)" % (got, exp), fails)
        nums = [float(x) for x in re.findall(r"-?\d+\.\d+", report_text(ws))]
        check(any(abs(x - exp) <= 0.01 * abs(exp) for x in nums), "REPORT.md does not state the correct Sharpe", fails)


def g_T08(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    orders = list(run.orders().values())
    check(len(orders) == 1 and orders[0]["order_type"] == "limit" and orders[0]["side"] == "Buy"
          and orders[0]["created_bar"] == 50, "expected exactly one BUY LIMIT created at bar 50, got %s" %
          [(o["side"], o["order_type"], o["created_bar"]) for o in orders], fails)
    limit = bars[50]["close"] - 0.0020
    pos = list(run.positions().values())
    text = report_text(ws)
    if pos:
        e = pos[0]["open"]
        check(e.get("stop_loss") is not None and abs(e["stop_loss"] - (limit - 0.0040)) <= TOL,
              "stop_loss %r, expected %.5f" % (e.get("stop_loss"), limit - 0.0040), fails)
        check(e.get("take_profit") is not None and abs(e["take_profit"] - (limit + 0.0040)) <= TOL,
              "take_profit %r, expected %.5f" % (e.get("take_profit"), limit + 0.0040), fails)
        check(re.search(r"(?<![\d.])%d(?![\d.])" % e["bar_index"], text) is not None,
              "REPORT.md does not state the canonical fill bar %d" % e["bar_index"], fails)
    else:
        check(re.search(r"never|not fill|unfilled|expired", text, re.I) is not None,
              "order never filled but REPORT.md does not say so", fails)


def _norm(s):
    return re.sub(r"[-+]?\d[\d.e+-]*", "#", (s or "").lower()).strip()


def g_T09(ws, run_unused, fails, py):
    run = Run(os.path.join(ws, "existing_run"))
    p = os.path.join(ws, "REPORT.json")
    if not check(os.path.isfile(p), "REPORT.json missing", fails):
        return
    try:
        rep = json.load(open(p))
    except ValueError as exc:
        fails.append("REPORT.json invalid: %s" % exc)
        return
    rej = run.of("order_rejected")
    top = Counter(_norm(e["reason"]) for e in rej).most_common(1)[0][0]
    check(rep.get("closed_trades") == len(run.of("position_closed")), "closed_trades %r, expected %d" % (rep.get("closed_trades"), len(run.of("position_closed"))), fails)
    check(rep.get("rejected_orders") == len(rej), "rejected_orders %r, expected %d" % (rep.get("rejected_orders"), len(rej)), fails)
    got = _norm(str(rep.get("top_rejection_reason", "")))
    check(bool(got) and (got in top or top in got), "top_rejection_reason %r does not match %r" % (rep.get("top_rejection_reason"), top), fails)
    fe = run.run["final_equity"]
    check(isinstance(rep.get("final_equity"), (int, float)) and abs(rep["final_equity"] - fe) <= 1e-6 * abs(fe),
          "final_equity %r, expected %r" % (rep.get("final_equity"), fe), fails)
    dd = run.metrics["max_drawdown_pct"]
    check(isinstance(rep.get("max_drawdown_pct"), (int, float)) and abs(rep["max_drawdown_pct"] - dd) <= 1e-6 * max(1.0, abs(dd)),
          "max_drawdown_pct %r, expected %r" % (rep.get("max_drawdown_pct"), dd), fails)
    check(os.path.isfile(os.path.join(ws, "REPORT.md")), "REPORT.md missing", fails)


def g_T10(ws, run, fails, py):
    bars = read_csv(os.path.join(ws, "bars.csv"))
    if not common(ws, run, fails, len(bars)):
        return
    c = [b["close"] for b in bars]
    exp = [i for i in range(20, len(c)) if c[i] < min(c[i - 20:i]) and not run.open_at(i)]
    check(len(exp) > 0, "grader found no expected entries (task data problem)", fails)
    set_diff("entry decision bars", order_bars(run, "Sell"), exp, fails)
    levels_ok(run, c, "Sell", 0.0040, 0.0080, fails)
    check(not order_bars(run, "Close") and not order_bars(run, "Buy"), "unexpected close/buy orders", fails)


GRADERS = {tid: globals()["g_" + tid.split("_")[0]] for tid in TASK_IDS}


def grade_task(ws, tid, py):
    fails = []
    try:
        GRADERS[tid](ws, Run(os.path.join(ws, "run")), fails, py)
    except Exception as exc:  # noqa: BLE001 — a grader crash is a recorded failure
        fails.append("grader error: %s: %s" % (type(exc).__name__, exc))
    return {"task": tid, "passed": not fails, "failures": fails}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="directory containing one workspace per task id")
    ap.add_argument("--python", default=sys.executable, help="venv python with observa (for T05 validation)")
    ap.add_argument("--json", help="write results here")
    ap.add_argument("--tasks", nargs="*", default=TASK_IDS)
    a = ap.parse_args()
    results = []
    for tid in a.tasks:
        ws = os.path.abspath(os.path.join(a.root, tid))
        if not os.path.isdir(ws):
            results.append({"task": tid, "passed": False, "failures": ["workspace missing"]})
            continue
        results.append(grade_task(ws, tid, a.python))
    for r in results:
        print("%-26s %s" % (r["task"], "PASS" if r["passed"] else "FAIL"))
        for f in r["failures"]:
            print("    - " + f)
    n = sum(r["passed"] for r in results)
    print("pass rate: %d/%d" % (n, len(results)))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"results": results, "passed": n, "total": len(results)}, fh, indent=2)


if __name__ == "__main__":
    main()
