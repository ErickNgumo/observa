"""Reference solutions: a grader self-test, not an answer key for agents.

Solves each task in a copy of its workspace so that ``grade.py`` can be shown
to PASS a correct solution (and to FAIL deliberately wrong variants, see
``--mutant``). Agents never see this file.

    python reference_solutions.py WORKSPACE_ROOT [--tasks T01_sma_sl_tp ...] [--mutant]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))

SOL = {}

SOL["T01_sma_sl_tp"] = '''
class S:
    def initialize(self, params=None):
        self.c = []
    def on_bar(self, bar, portfolio, history):
        self.c.append(bar["close"])
        c = self.c
        if len(c) < 31:
            return []
        f1, s1 = sum(c[-10:]) / 10, sum(c[-30:]) / 30
        f0, s0 = sum(c[-11:-1]) / 10, sum(c[-31:-1]) / 30
        if f1 > s1 and f0 <= s0 and not portfolio["open_positions"]:
            x = bar["close"]
            return [{"direction": "buy", "size": 1.0, "sl": x - %(SL)s, "tp": x + 0.0100, "reason": "SMA10 crossed above SMA30"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

SOL["T02_close_by_ticket"] = '''
class S:
    def initialize(self, params=None):
        pass
    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if i == 10:
            return [{"direction": "buy", "size": 0.5, "reason": "scheduled buy"}]
        if i == 20:
            return [{"direction": "sell", "size": 0.3, "reason": "scheduled sell"}]
        if i == 30:
            p = [p for p in portfolio["open_positions"] if p["direction"] == "Buy"][0]
            return [{"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "close the buy"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

SOL["T03_external_join"] = '''
import csv
from datetime import datetime
def key(ts):
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
class S:
    def initialize(self, params=None):
        with open("predictions.csv") as fh:
            self.p = {key(r["timestamp"]): int(r["prediction"]) for r in csv.DictReader(fh)}
    def on_bar(self, bar, portfolio, history):
        p = self.p.get(%(KEY)s)
        op = portfolio["open_positions"]
        if p == 1 and not op:
            return [{"direction": "buy", "size": 1.0, "reason": "prediction 1"}]
        if p == 0 and op:
            return [{"direction": "close", "size": op[0]["size"], "ticket": op[0]["position_id"], "reason": "prediction 0"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

SOL["T04_intraday_100k"] = '''
class S:
    def initialize(self, params=None):
        pass
    def on_bar(self, bar, portfolio, history):
        i = len(history)
        op = portfolio["open_positions"]
        if i %% 1000 == 100 and not op:
            return [{"direction": "buy", "size": 0.1, "reason": "scheduled entry"}]
        if i %% 1000 == 600 and op:
            return [{"direction": "close", "size": op[0]["size"], "ticket": op[0]["position_id"], "reason": "scheduled exit"}]
        return []
    def teardown(self):
        pass
RUN = ("bars_1m.csv", {"interval": "1m"})
'''

SOL["T05_repair_strategy"] = '''
class S:
    def initialize(self, params=None):
        self.entry = None
    def on_bar(self, bar, portfolio, history):
        i = len(history)
        op = portfolio["open_positions"]
        if op:
            if self.entry is not None and i == self.entry + %(EXIT)s:
                return [{"direction": "close", "size": op[0]["size"], "ticket": op[0]["position_id"], "reason": "24-bar time exit"}]
            return []
        if history and bar["close"] - history[-1]["close"] > 0.0015:
            self.entry = i
            x = bar["close"]
            return [{"direction": "buy", "size": 1.0, "sl": x - 0.0030, "tp": x + 0.0060, "reason": "momentum burst"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

SOL["T06_zero_trade_diagnosis"] = None  # strategy given; only config changes (see below)

SOL["T07_intraday_sharpe"] = None  # strategy given; only bars_per_year changes

SOL["T08_limit_order"] = '''
class S:
    def initialize(self, params=None):
        pass
    def on_bar(self, bar, portfolio, history):
        if len(history) == 50:
            lim = bar["close"] - 0.0020
            return [{"direction": "buy", "order_type": "limit", "price": lim, "size": 1.0,
                     "sl": lim - 0.0040, "tp": lim + 0.0040, "reason": "resting limit"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

SOL["T10_short_breakout"] = '''
class S:
    def initialize(self, params=None):
        pass
    def on_bar(self, bar, portfolio, history):
        if len(history) < 20 or portfolio["open_positions"]:
            return []
        x = bar["close"]
        if x < min(b["close"] for b in history[-20:]):
            return [{"direction": "sell", "size": 1.0, "sl": x + 0.0040, "tp": x - 0.0080, "reason": "20-bar breakdown"}]
        return []
    def teardown(self):
        pass
RUN = ("bars.csv", {})
'''

RUNNER = '''
import json, shutil, sys, os, time
sys.path.insert(0, ".")
import observa
from strategy import S, RUN
shutil.rmtree("run", ignore_errors=True)
data, cfg = RUN
t = time.time()
r = observa.run(S(), data, config=observa.Config(**cfg), output="run", **json.loads(sys.argv[1]))
opened = [e for e in r.events if e["type"] == "position_opened"]
open("REPORT.md", "w").write("reference solution; positions %d; final equity %.2f; %.1fs; %s\\n"
                             "sharpe %r; first fill bar %s\\n" % (
    len(opened), r.final_equity, time.time() - t, sys.argv[2], r.metrics["sharpe_ratio"],
    opened[0]["bar_index"] if opened else "never filled"))
'''


def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def solve(ws, tid, py, mutant):
    extra_kw = {}
    note = ""
    if tid == "T06_zero_trade_diagnosis":
        cfg = dict(contract_size=1.0, leverage=1.0, starting_balance=100000.0, spread=10.0, slippage=0.0,
                   currency="USD", interval="1h", symbol="BTCUSD", base_currency="BTC", quote_currency="USD")
        if mutant:
            cfg["spread"] = 0.0
        src = open(os.path.join(ws, "strategy.py")).read() + "\nS = EmaCross\nRUN = ('btc_h1.csv', %r)\n" % cfg
        write(os.path.join(ws, "strategy.py"), src)
        note = "cause: every entry rejected for insufficient margin under the EURUSD defaults"
    elif tid == "T07_intraday_sharpe":
        src = open(os.path.join(ws, "strategy.py")).read() + "\nS = Revert\nRUN = ('bars_5m.csv', {'interval': '5m'})\n"
        write(os.path.join(ws, "strategy.py"), src)
        extra_kw = {"bars_per_year": 252 * (365 if mutant else 288)}
    elif tid == "T09_inspect_run":
        r = __import__("observa").inspect_run if False else None  # resolved in subprocess below
        code = textwrap.dedent('''
            import json, collections, observa
            run = observa.inspect_run("existing_run")
            rej = run.rejections()
            top = collections.Counter(e["reason"] for e in rej).most_common(1)[0][0]
            rep = {"closed_trades": len(run.trades()), "rejected_orders": len(rej) + %d,
                   "top_rejection_reason": top, "final_equity": run.meta["final_equity"],
                   "max_drawdown_pct": run.metrics["max_drawdown_pct"]}
            json.dump(rep, open("REPORT.json", "w")); open("REPORT.md", "w").write(json.dumps(rep))
        ''' % (1 if mutant else 0))
        subprocess.check_call([py, "-c", code], cwd=ws)
        return
    else:
        subst = {"SL": "0.0049" if mutant else "0.0050",
                 "KEY": "bar['timestamp']" if mutant else "key(bar['timestamp'])",
                 "EXIT": "25" if mutant else "24"}
        write(os.path.join(ws, "strategy.py"), SOL[tid] % subst)
        if tid == "T08_limit_order" and mutant:
            write(os.path.join(ws, "strategy.py"), SOL[tid].replace("0.0020", "0.0021") % subst)
        if tid == "T02_close_by_ticket" and mutant:
            write(os.path.join(ws, "strategy.py"), (SOL[tid] % subst).replace('"Buy"', '"Sell"'))
        if tid == "T10_short_breakout" and mutant:
            write(os.path.join(ws, "strategy.py"), (SOL[tid] % subst).replace("history[-20:]", "history[-19:]"))
        if tid == "T04_intraday_100k" and mutant:
            write(os.path.join(ws, "strategy.py"), (SOL[tid] % subst).replace("== 600", "== 601"))
    write(os.path.join(ws, "_ref_run.py"), RUNNER)
    subprocess.check_call([py, "_ref_run.py", json.dumps(extra_kw), note], cwd=ws)
    os.remove(os.path.join(ws, "_ref_run.py"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--mutant", action="store_true", help="solve each task slightly wrong (grader must FAIL)")
    a = ap.parse_args()
    sys.path.insert(0, HERE)
    from tasks import TASK_IDS
    for tid in a.tasks or TASK_IDS:
        solve(os.path.join(a.root, tid), tid, a.python, a.mutant)
        print("solved", tid, "(mutant)" if a.mutant else "")


if __name__ == "__main__":
    main()
