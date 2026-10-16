#!/usr/bin/env python
"""Post-run probes (written AFTER reading evaluation.rs / derive_metrics_json).

These are informational edge probes, not pre-registered golden values:
  P1 float-noise break-even trade on EURUSD-style prices
  P2 is an explicit bars_per_year recorded in run.json (provenance)?
  P3 does a break-even trade reset max_consecutive_losses?
  P4 drawdown start on an equity plateau (first or last bar at the peak?)
  P5 partial close: how many "trades"?
  P6 legacy 0.1.6 run dir readable by the new wheel (pass path as argv[1])
  P7 run_summary text for a schema-2 run (precision presentation)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics_golden as g  # noqa: E402
import observa  # noqa: E402

ROOT = tempfile.mkdtemp(prefix="metrics_probes_")


def show(label, value):
    print(f"{label}: {value!r}")


# P1 -- EURUSD 1 lot, spread 0.0002, slippage 0.0001. Buy at 1.1000 open ->
# 1.1002; close at open 1.1004 -> 1.1004-0.0002 = 1.1002. Economic P&L = 0.
fx = dict(starting_balance=10000.0, contract_size=100000.0, spread=0.0002,
          slippage=0.0001, commission=0.0, fill_mode="next_bar_open", interval="1d")
bars = g.daily_bars([(1.1000, 1.1010, 1.0990, 1.1000), (1.1000, 1.1010, 1.0990, 1.1003),
                     (1.1003, 1.1010, 1.0990, 1.1004), (1.1004, 1.1010, 1.0990, 1.1004),
                     (1.1004, 1.1010, 1.0990, 1.1004)])
r = observa.run(g.Scripted({0: [("buy", 1.0, {})], 2: [("close_all",)]}), bars,
                config=observa.Config(**fx), output=os.path.join(ROOT, "p1"))
ev = [json.loads(l) for l in Path(ROOT, "p1", "events.jsonl").read_text().splitlines()]
fills = [(e["executed_price"]) for e in ev if e["type"] == "order_filled"]
closed = [e for e in ev if e["type"] == "position_closed"]
show("P1 fills", fills)
show("P1 position_closed net", [c.get("net_realized_pnl", c) for c in closed])
show("P1 win/loss/breakeven", (r.metrics["winning_trades"], r.metrics["losing_trades"],
                                r.metrics["breakeven_trades"]))

# P2 -- explicit bars_per_year provenance
b40 = observa_bars = g.ref.make_bars("calendar_daily", g.ref.daily_path(40))
observa.run(g.bh_strategy(), b40, config=g.zero_cost(), bars_per_year=365.0,
            output=os.path.join(ROOT, "p2"))
run_json = Path(ROOT, "p2", "run.json").read_text()
metrics_json = json.loads(Path(ROOT, "p2", "metrics.json").read_text())
show("P2 'bars_per_year' in run.json", "bars_per_year" in run_json)
show("P2 metrics.assumptions.bars_per_year", metrics_json["assumptions"]["bars_per_year"])
try:
    insp = observa.inspect_run(os.path.join(ROOT, "p2"))
    txt = json.dumps(insp, default=str) if not isinstance(insp, str) else insp
    show("P2 inspect_run mentions 365", "365" in txt)
except Exception as exc:  # noqa: BLE001
    show("P2 inspect_run", f"raised {exc!r}")

# P3 -- loss, break-even, loss: streak 1 (reset) or 2?
bars3 = g.daily_bars([(100, 100, 100, 100), (100, 100, 99, 99), (99, 99, 99, 99),
                      (99, 99, 99, 99), (99, 99, 99, 99), (99, 99, 98, 98), (98, 98, 98, 98)])
r = observa.run(g.Scripted({0: [("buy", 1.0, {})], 1: [("close_all",)], 2: [("buy", 1.0, {})],
                            3: [("close_all",)], 4: [("buy", 1.0, {})], 5: [("close_all",)]}),
                bars3, config=g.zero_cost())
m = r.metrics
show("P3 trades w/l/be", (m["winning_trades"], m["losing_trades"], m["breakeven_trades"]))
show("P3 max_consecutive_losses (loss, BE, loss)", m["max_consecutive_losses"])

# P4 -- plateau at peak: E = S, 10100, 10100, 10100, 9900
bars4 = g.daily_bars([(100, 100, 100, 100), (100, 101, 100, 101), (101, 101, 101, 101),
                      (101, 101, 101, 101), (101, 101, 99, 99)])
r = observa.run(g.Scripted({0: [("buy", 1.0, {})]}), bars4, config=g.zero_cost())
m = r.metrics
show("P4 dd start (b1=first plateau bar, b3=last)", m["max_drawdown_start"])

# P5 -- partial close of 2 lots: close 1 lot, then 1 lot
bars5 = g.daily_bars([(100, 100, 100, 100), (100, 101, 100, 101), (101, 102, 101, 102),
                      (102, 103, 102, 103), (103, 104, 103, 104), (104, 104, 104, 104)])


class Partial:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if i == 0:
            return [{"direction": "buy", "size": 2.0, "reason": "entry"}]
        if i in (2, 3) and portfolio["open_positions"]:
            p = portfolio["open_positions"][0]
            return [{"direction": "close", "size": 1.0, "ticket": p["position_id"],
                     "reason": "partial"}]
        return []

    def teardown(self):
        pass


try:
    r = observa.run(Partial(), bars5, config=g.zero_cost(), output=os.path.join(ROOT, "p5"))
    ev = [json.loads(l) for l in Path(ROOT, "p5", "events.jsonl").read_text().splitlines()]
    show("P5 event types", sorted({e["type"] for e in ev}))
    show("P5 rejections", [e.get("reason") or e for e in ev if e["type"] == "order_rejected"])
    show("P5 total_trades / net_profit / avg_holding",
         (r.metrics["total_trades"], r.metrics["net_profit"], r.metrics["avg_holding_bars"]))
except Exception as exc:  # noqa: BLE001
    show("P5", f"raised {exc!r}")

# P6 -- legacy schema-1 run directory produced by 0.1.6
if len(sys.argv) > 1:
    try:
        insp = observa.inspect_run(sys.argv[1])
        show("P6 inspect_run(legacy) ok, type", type(insp).__name__)
        txt = json.dumps(insp, default=str)
        show("P6 legacy mention", [w for w in ("legacy", "schema") if w in txt.lower()])
    except Exception as exc:  # noqa: BLE001
        show("P6 inspect_run(legacy)", f"raised {exc!r}")

# P7 -- summary text for the 2-year daily run
closes = g.ref.daily_path(504)
r = observa.run(g.bh_strategy(), g.ref.make_bars("business_daily", closes), config=g.zero_cost())
try:
    print("P7 result.summary():\n" + str(r.summary()))
except Exception as exc:  # noqa: BLE001
    show("P7 summary", f"raised {exc!r}")
