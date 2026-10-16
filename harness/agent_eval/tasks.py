"""Fixed task definitions for the Observa agent evaluation.

Every task is defined here *before* any attempt is run: the prompt the agent
receives (``TASK.md``), the deterministic input files it starts from, and the
grading rule (see ``grade.py``). The task set and graders are frozen for a
baseline/final comparison; changing either invalidates the comparison.

Data is synthetic and generated deterministically from fixed seeds with only
the standard library, so a workspace is byte-identical on every machine.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone

TASK_IDS = [
    "T01_sma_sl_tp",
    "T02_close_by_ticket",
    "T03_external_join",
    "T04_intraday_100k",
    "T05_repair_strategy",
    "T06_zero_trade_diagnosis",
    "T07_intraday_sharpe",
    "T08_limit_order",
    "T09_inspect_run",
    "T10_short_breakout",
]

COMMON_RULES = """
## Rules for this task

* Work only inside this directory. Use the Python interpreter given to you; the
  `observa` package is already installed in it (do not install anything).
* Read `AGENTS.md` in this directory first; it is the official instruction set.
* Do not read or modify anything outside this directory (in particular, not the
  Observa source code).
* Leave your final strategy in `strategy.py` (unless the task says otherwise)
  and persist the final run to `./run` with `observa.run(..., output="run")`.
  If `./run` already exists from an earlier attempt, delete it before the final
  run.
* Finish by writing `REPORT.md`: what you did, any assumptions, and the
  requested numbers. If you could not complete the task, say so plainly and why.
"""


def _ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def random_walk(n, seed, start=1.1000, sigma=0.0009, minutes=60,
                t0=datetime(2025, 3, 3, tzinfo=timezone.utc), skip_weekends=False):
    rng = random.Random(seed)
    rows = []
    p = start
    t = t0
    for _ in range(n):
        if skip_weekends:
            while t.weekday() >= 5:
                t += timedelta(minutes=minutes)
        o = p
        c = max(o + rng.gauss(0.0, sigma), start * 0.2)
        wick_hi = abs(rng.gauss(0.0, sigma * 0.6))
        wick_lo = abs(rng.gauss(0.0, sigma * 0.6))
        rows.append({"timestamp": _ts(t), "open": round(o, 5), "high": round(max(o, c) + wick_hi, 5),
                     "low": round(min(o, c) - wick_lo, 5), "close": round(c, 5),
                     "volume": rng.randint(50, 500)})
        p = round(c, 5)
        t += timedelta(minutes=minutes)
    return rows


def write_csv(path, rows, fields=("timestamp", "open", "high", "low", "close", "volume")):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields))
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})


def read_csv(path):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("open", "high", "low", "close"):
            r[k] = float(r[k])
    return rows


# ── Task-specific data ──────────────────────────────────────────────────────

def data_T01():
    return random_walk(2000, seed=101)


def data_T02():
    return random_walk(60, seed=202)


def data_T03():
    bars = random_walk(1500, seed=303)
    rng = random.Random(3031)
    preds = []
    # Predictions exist for roughly 60% of bars, keyed by the *same* timestamp
    # strings as the bar file (RFC 3339 with a trailing 'Z').
    state = 0
    for b in bars:
        if rng.random() < 0.6:
            if rng.random() < 0.15:
                state = 1 - state
            preds.append({"timestamp": b["timestamp"], "prediction": state})
    return bars, preds


def data_T04():
    return random_walk(100_000, seed=404, sigma=0.00015, minutes=1)


def data_T05():
    return random_walk(1200, seed=505)


def data_T06():
    return random_walk(1500, seed=606, start=60000.0, sigma=180.0)


def data_T07():
    return random_walk(6000, seed=707, sigma=0.00025, minutes=5, skip_weekends=True)


def data_T08():
    return random_walk(200, seed=808)


def data_T10():
    return random_walk(2500, seed=1010)


# ── Prompts ─────────────────────────────────────────────────────────────────

PROMPTS = {
"T01_sma_sl_tp": """# Task T01 — SMA crossover with stop loss and take profit

Data: `bars.csv` (hourly EUR/USD-like bars). Use the default Observa config
(`observa.Config()`), except nothing else needs changing.

Implement this rule exactly:

* SMA_fast = simple moving average of the last 10 closes **including the
  current bar's close**; SMA_slow = same with 30 closes.
* A bullish cross happens on a bar when SMA_fast > SMA_slow on that bar and
  SMA_fast <= SMA_slow on the previous bar (both SMAs must be computable on
  both bars).
* On a bullish cross, **if no position is open**, buy 1.0 lot (market) with a
  stop loss 0.0050 below that bar's close and a take profit 0.0100 above that
  bar's close.
* No other exits: positions leave only by their stop loss or take profit.

Report the number of positions opened and the final equity.
""",
"T02_close_by_ticket": """# Task T02 — Two positions, close one by ticket

Data: `bars.csv`. Default config.

Bar index i means the strategy is processing the bar with exactly i prior bars
in `history` (the first bar is index 0).

* At bar index 10, buy 0.5 lots (market).
* At bar index 20, sell 0.3 lots (market).
* At bar index 30, close **only the buy position**, using its ticket. The sell
  position must stay open until the end of the data.

Report the realised P&L of the closed buy position and the final equity.
""",
"T03_external_join": """# Task T03 — Trade precomputed model predictions

Data: `bars.csv` (hourly bars) and `predictions.csv` (columns `timestamp`,
`prediction`). Predictions exist for only some bars; their `timestamp` values
identify the bar they belong to. Default config.

Rule, evaluated on each bar:

* If the bar has a prediction of 1 and no position is open: buy 1.0 lot.
* If the bar has a prediction of 0 and a position is open: close it (by ticket).
* If the bar has no prediction: do nothing.

Report how many positions were opened and the final equity.
""",
"T04_intraday_100k": """# Task T04 — 100,000 one-minute bars

Data: `bars_1m.csv` — 100,000 one-minute bars. Config: default, but with
`interval="1m"`.

* At every bar index i with i % 1000 == 100, buy 0.1 lots if no position is
  open.
* At every bar index i with i % 1000 == 600, close the open position by its
  ticket.

The backtest must run over the **whole file in a single run**. A run that has
not finished within 20 minutes of wall-clock time counts as a failure; if that
happens, say so in REPORT.md and report what you measured.

Report the number of positions opened, the final equity, and how long the
backtest took.
""",
"T05_repair_strategy": """# Task T05 — Repair a broken strategy

`broken_strategy.py` was written by someone else. It runs without crashing but
does not do what it is supposed to. Fix it (write the result to
`strategy.py`) so it implements exactly this intended behaviour on `bars.csv`
with the default config:

* Entry: when the current close is more than 0.0015 above the previous bar's
  close and no position is open, buy 1.0 lot with a stop loss 0.0030 below the
  current close and a take profit 0.0060 above the current close.
* Time exit: if the position is still open on the bar whose index is exactly
  24 bars after the entry *decision* bar, close it by its ticket.
* Every signal must have a meaningful `reason`.

Your `strategy.py` must pass `observa validate-strategy strategy.py --smoke`
(exit code 0).

Report the number of positions opened and how many were closed by stop loss,
take profit, and the time exit.
""",
"T06_zero_trade_diagnosis": """# Task T06 — "My backtest produces zero trades"

A user sends you `strategy.py`, `btc_h1.csv` and `run_it.py`, and says:

> The backtest runs fine and finishes without errors, but it never makes a
> single trade. The EMA cross obviously happens many times in this data. What
> is wrong?

Find the actual cause, explain it in REPORT.md, and fix the setup so the
backtest trades BTC/USD correctly with: 1 lot = 1 BTC, $100,000 starting
balance, no leverage (leverage 1), a spread of $10 per BTC, zero slippage,
account currency USD. Keep the strategy logic itself unchanged (you may
change config and the run script). Persist the fixed run to `./run`.
""",
"T07_intraday_sharpe": """# Task T07 — Annualised Sharpe on 5-minute data

Data: `bars_5m.csv` — 5-minute bars for a market that trades 24 hours a day
on weekdays. Use `strategy.py` as given (do not change its logic) and the
default config, with `interval="5m"`.

Report the strategy's **annualised** Sharpe ratio as computed by Observa,
annualised correctly for 5-minute bars assuming 252 trading days per year of
24 hours each. The persisted run's metrics must reflect that annualisation.
""",
"T08_limit_order": """# Task T08 — Resting limit order

Data: `bars.csv`. Default config.

* At bar index 50, place a BUY LIMIT order for 1.0 lot at a limit price
  0.0020 below bar 50's close, with a stop loss 0.0040 below the limit price
  and a take profit 0.0040 above the limit price.
* Do nothing else.

Report the bar index at which the order filled (or that it never filled), the
executed price, and how the position ended.
""",
"T09_inspect_run": """# Task T09 — Inspect an existing run

`existing_run/` is a persisted Observa run produced by someone else. Do not
re-run anything. Using Observa's own inspection tools, find:

* the number of closed trades,
* the number of rejected orders, and the most common rejection reason,
* the final equity,
* the maximum drawdown in percent.

Write these to `REPORT.json` as
`{"closed_trades": int, "rejected_orders": int, "top_rejection_reason": str,
"final_equity": float, "max_drawdown_pct": float}` and also summarise them in
REPORT.md. (No `strategy.py` or `./run` is needed for this task.)
""",
"T10_short_breakout": """# Task T10 — Short breakdown with protective levels

Data: `bars.csv`. Default config.

* When the current close is strictly below the lowest close of the previous
  20 bars (the 20 bars before the current one), and no position is open,
  SELL 1.0 lot (market) with a stop loss 0.0040 above the current close and a
  take profit 0.0080 below the current close.
* No other exits.

Report the number of positions opened and the final equity.
""",
}

# ── Supporting files ────────────────────────────────────────────────────────

T05_BROKEN = '''"""Momentum strategy (contains bugs - see TASK.md)."""


class Momentum:
    def initialize(self, params=None):
        self.entry_bar = None

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if not history:
            return
        prev = history[-1]["close"]
        if portfolio["open_positions"]:
            pos = portfolio["open_positions"][0]
            if self.entry_bar is not None and i - self.entry_bar >= 24:
                return {"direction": "close", "quantity": pos["size"]}
            return
        if bar["close"] - prev > 0.0015:
            self.entry_bar = i
            return {
                "direction": "buy",
                "size": 1.0,
                "stop_loss": bar["close"] - 0.0030,
                "take_profit": bar["close"] + 0.0060,
            }

    def teardown(self):
        pass
'''

T06_STRATEGY = '''"""EMA cross, long only."""


class EmaCross:
    def initialize(self, params=None):
        self.fast, self.slow = 12, 26
        self.ef = self.es = None

    def on_bar(self, bar, portfolio, history):
        c = bar["close"]
        af, as_ = 2 / (self.fast + 1), 2 / (self.slow + 1)
        pf, ps = self.ef, self.es
        self.ef = c if self.ef is None else af * c + (1 - af) * self.ef
        self.es = c if self.es is None else as_ * c + (1 - as_) * self.es
        if pf is None or len(history) < self.slow:
            return []
        if pf <= ps and self.ef > self.es and not portfolio["open_positions"]:
            return [{"direction": "buy", "size": 0.1, "reason": "EMA12 crossed above EMA26"}]
        if pf >= ps and self.ef < self.es and portfolio["open_positions"]:
            p = portfolio["open_positions"][0]
            return [{"direction": "close", "size": p["size"], "ticket": p["position_id"],
                     "reason": "EMA12 crossed below EMA26"}]
        return []

    def teardown(self):
        pass
'''

T06_RUN = '''import observa
from strategy import EmaCross

result = observa.run(EmaCross(), "btc_h1.csv", config=observa.Config(interval="1h"))
print(result.summary())
'''

T07_STRATEGY = '''"""Mean reversion on 5-minute bars."""


class Revert:
    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        if len(history) < 48:
            return []
        mean = sum(b["close"] for b in history[-48:]) / 48
        if not portfolio["open_positions"] and bar["close"] < mean - 0.0015:
            return [{"direction": "buy", "size": 1.0, "reason": "close 15 pips under 4h mean"}]
        if portfolio["open_positions"] and bar["close"] > mean:
            p = portfolio["open_positions"][0]
            return [{"direction": "close", "size": p["size"], "ticket": p["position_id"],
                     "reason": "back at the 4h mean"}]
        return []

    def teardown(self):
        pass
'''

T09_STRATEGY = '''
class Busy:
    """Produces trades plus some deliberate rejections (for T09 inspection)."""

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        out = []
        if i % 40 == 5 and not portfolio["open_positions"]:
            out.append({"direction": "buy", "size": 1.0, "reason": "periodic entry"})
        if i % 40 == 25 and portfolio["open_positions"]:
            p = portfolio["open_positions"][0]
            out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"],
                        "reason": "periodic exit"})
        if i % 50 == 7:
            out.append({"direction": "buy", "size": 500.0, "reason": "oversized on purpose"})
        if i % 90 == 11:
            out.append({"direction": "sell", "size": 1.0, "sl": bar["close"] - 0.01,
                        "reason": "wrong-side stop on purpose"})
        return out

    def teardown(self):
        pass
'''
