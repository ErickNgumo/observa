#!/usr/bin/env python
"""Independent Finance/QA golden ledgers for the Observa engine.

Every expected number below was hand-computed from the DOCUMENTED execution
rules (docs/execution-model.md, docs/domain/EXECUTION.md, docs/domain/PORTFOLIO.md,
docs/ARCHITECTURE.md section 8, docs/DECISIONS.md ADR-006/007/008, llms-full.txt
section I) and written down BEFORE the engine was run.  Where the docs are
silent or contradictory, the assumption used is tagged ``[GAP-n]``; the gap
list lives in harness/finance/FINANCE_REVIEW.md.

Run:  python harness/finance/golden_ledgers.py
Exit: 0 when every check passes, 1 when any check fails.

Conventions used for the hand computation
-----------------------------------------
* contract_size = 100000, starting_balance = 10000, leverage = 100 unless stated.
* units = lots * contract_size.
* half_spread = spread / 2 (execution-model.md: "Spread is applied half on each
  side of the market reference (a fixed spread config is treated as a full
  spread)").  [GAP-1: docs/domain/EXECUTION.md instead says fill = open + spread
  + slippage, i.e. the full spread; execution-model.md is used.]
* Market buy  = reference + half_spread + slippage  (adverse)
  Market sell = reference - half_spread - slippage  (adverse)
  reference = next bar open (NEXT_BAR_OPEN) or this bar close (BAR_CLOSE).
* Explicit close of a long is a market sell; of a short a market buy.
* Non-gap protective SL exit = SL level -/+ slippage, no spread
  (ADR-007 / ARCHITECTURE s8: "SL exits receive slippage"; spread treatment
  for protective exits is undocumented).  [GAP-2]
* Protective TP exit = TP level exactly (ADR-007: no slippage; spread
  undocumented).  [GAP-3]
* Gap-through SL (bar opens through SL) = bar open treated as a market exit:
  open -/+ half_spread -/+ slippage ("canonical market reference with
  applicable adjustments" - adjustments undefined).  [GAP-4]
* Triggered LIMIT / STOP entry (no gap) = the order price exactly ("not
  adversarially slipped beyond their trigger semantics"; spread undocumented).
  [GAP-5]
* Gap-through STOP entry = bar open treated as market execution
  (open + half_spread + slippage for a buy stop).  [GAP-4/GAP-5]
* Unrealised P&L is marked at the bar close (mid, no spread):
  long (close - entry)*units, short (entry - close)*units.  [GAP-6]
* used_margin = units * ENTRY executed price / leverage (docs: "notional =
  units x price", which price is not stated).  [GAP-7]
* free_margin = equity - used_margin (documented).
* PER_SIDE commission is charged on each fill and deducted from balance at the
  fill; ROUND_TRIP is charged once, on the closing fill.  [GAP-8]
* Snapshots: one portfolio_snapshot per bar, taken after all of that bar's
  processing (including BAR_CLOSE fills).  [GAP-9]
* gross_realized_pnl = (exit - entry) * units (long) / (entry - exit) * units
  (short); net = gross - total_commission.

Tolerances (fixed before the engine was run):
  prices: abs 1e-9     money: abs 1e-6

Provenance note: the pre-run sheet (golden_expectations_prerun.py.txt, sha256
89abb45c...) contained a verifier arithmetic slip: pip P&L was scaled by 1e4
instead of 1e5 (e.g. 0.0036 * 100000 written as 36 instead of 360).  It was
detected on the first (schema-discovery) run and corrected by re-deriving each
number from the formulas (cross-checked with decimal.Decimal).  No gap
assumption was changed in that correction.  Explicit-close exit_reason naming
is undocumented, so "explicit" below means "not StopLoss/TakeProfit".

RESOLUTION AFTER THE FIRST RUN (see golden_run1_prerun_assumptions.txt and
FINANCE_REVIEW.md).  The first run failed only on [GAP-n]-dependent checks and
on one further verifier slip.  After consulting the code, the literals below
were updated to the code's semantics; each changed literal is tagged
"CODE:" with the source location:
  [GAP-2] non-gap SL exit is market-style: SL -/+ half_spread -/+ slippage
          (crates/observa-execution/src/semantics.rs protective_long/short ->
          market_adjust).  Pre-run assumption SL -/+ slippage was wrong.
  [GAP-5] triggered STOP entry is market-style: stop +/- half_spread +/-
          slippage (semantics.rs stop_outcome).  LIMIT is exact (assumption held).
  [GAP-7] snapshot used_margin is marked at the bar CLOSE:
          units * close / leverage (observa-portfolio portfolio.rs used_margin(
          valuation_price), engine.rs snapshot(bar.close)); the entry margin
          CHECK uses the entry price.  Pre-run assumption (entry price) was wrong.
  [GAP-8] ROUND_TRIP balance timing held (charged at close), but
          order_filled.commission_amount reports the computed amount on BOTH
          fills (7 + 7) while only 7 is booked (portfolio.rs open_position
          ignores it under ROUND_TRIP).
  Verifier slip #2: G10 entry 1.2500 + 0.0001 + 0.0001 = 1.2502 (was written
          1.2503); dependent equity/margin literals re-derived.
Scenarios G5s, G6s, G6g, G9d, G11 were added AFTER the code consultation as
regression checks; their literals were hand-derived but are not independent of
the code reading.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import observa

PRICE_TOL = 1e-9
MONEY_TOL = 1e-6

# ---------------------------------------------------------------------------
# Bars helpers
# ---------------------------------------------------------------------------

def bars(rows):
    """rows: list of (open, high, low, close); daily UTC timestamps."""
    out = []
    for i, (o, h, l, c) in enumerate(rows):
        out.append({
            "timestamp": f"2024-01-{i + 1:02d}T00:00:00Z",
            "open": o, "high": h, "low": l, "close": c, "volume": 1000.0,
        })
    return out


# ---------------------------------------------------------------------------
# SCENARIOS + EXPECTED VALUES (hand-computed, recorded before running)
# ---------------------------------------------------------------------------
# Each scenario: bars, config kwargs, script {bar_index: [actions]}, expected.
# Action forms:  ("buy"|"sell", lots, extra_signal_fields) or ("close_all",)
# Expected keys:
#   fills: list of dicts per order_filled in order (executed_price,
#          raw_reference, spread_applied, slippage_applied, commission_amount)
#   closed: list of position_closed dicts (gross, commission, net, exit_reason,
#           exit_price, bar)
#   snaps: {bar_index: (balance, equity, used_margin, free_margin)}
#   final: (final_balance, final_equity)
#   open_at_end: number of open positions at end
# Only the keys present are checked.

BASE = dict(starting_balance=10000.0, leverage=100.0, contract_size=100000.0,
            currency="USD", symbol="EURUSD", base_currency="EUR",
            quote_currency="USD", interval="1d")

SCENARIOS = {}

# G1 ---- market long, NEXT_BAR_OPEN, spread 0.0002, slippage 0.0001, comm 0
SCENARIOS["G1_long_next_bar_open"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1005),  # 0 signal buy 1 lot
        (1.1010, 1.1030, 1.1000, 1.1020),  # 1 fill buy @ open
        (1.1020, 1.1050, 1.1015, 1.1040),  # 2 signal close by ticket
        (1.1050, 1.1060, 1.1030, 1.1035),  # 3 fill close @ open
        (1.1035, 1.1040, 1.1020, 1.1030),  # 4 flat
    ]),
    config=dict(fill_mode="NEXT_BAR_OPEN", spread=0.0002, slippage=0.0001,
                commission=0.0, commission_mode="PER_SIDE",
                commission_rate_per_unit=0.0),
    script={0: [("buy", 1.0, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            # buy: 1.1010 + 0.0001 + 0.0001 = 1.1012
            dict(raw_reference=1.1010, executed_price=1.1012, commission_amount=0.0,
                 spread_applied=0.0001, slippage_applied=0.0001),
            # sell: 1.1050 - 0.0001 - 0.0001 = 1.1048
            dict(raw_reference=1.1050, executed_price=1.1048, commission_amount=0.0,
                 spread_applied=0.0001, slippage_applied=0.0001),
        ],
        closed=[
            # (1.1048 - 1.1012) * 100000 = 360.00
            dict(gross=360.0, commission=0.0, net=360.0, entry_price=1.1012,
                 exit_price=1.1048, exit_reason="explicit"),
        ],
        snaps={
            0: (10000.0, 10000.0, 0.0, 10000.0),
            # unreal (1.1020-1.1012)*1e5 = 80
            # CODE [GAP-7] margin marked at close: 1e5*1.1020/100 = 1102 (pre-run: 1101.2)
            1: (10000.0, 10080.0, 1102.0, 10080.0 - 1102.0),
            # unreal (1.1040-1.1012)*1e5 = 280 ; margin 1e5*1.1040/100 = 1104
            2: (10000.0, 10280.0, 1104.0, 10280.0 - 1104.0),
            3: (10360.0, 10360.0, 0.0, 10360.0),
            4: (10360.0, 10360.0, 0.0, 10360.0),
        },
        final=(10360.0, 10360.0),
        open_at_end=0,
    ),
)

# G2 ---- same bars and signals with BAR_CLOSE
SCENARIOS["G2_long_bar_close"] = dict(
    bars=SCENARIOS["G1_long_next_bar_open"]["bars"],
    config=dict(fill_mode="BAR_CLOSE", spread=0.0002, slippage=0.0001,
                commission=0.0, commission_mode="PER_SIDE",
                commission_rate_per_unit=0.0),
    script={0: [("buy", 1.0, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            # buy at bar0 close: 1.1005 + 0.0001 + 0.0001 = 1.1007
            dict(raw_reference=1.1005, executed_price=1.1007, commission_amount=0.0),
            # sell at bar2 close: 1.1040 - 0.0002 = 1.1038
            dict(raw_reference=1.1040, executed_price=1.1038, commission_amount=0.0),
        ],
        closed=[
            # (1.1038 - 1.1007) * 1e5 = 310.00
            dict(gross=310.0, commission=0.0, net=310.0, entry_price=1.1007,
                 exit_price=1.1038, exit_reason="explicit"),
        ],
        snaps={
            # bar0 after close fill: unreal (1.1005-1.1007)*1e5 = -20
            # CODE [GAP-7] margin 1e5*1.1005/100 = 1100.5 (pre-run: 1100.7)
            0: (10000.0, 9980.0, 1100.5, 9980.0 - 1100.5),
            # unreal (1.1020-1.1007)*1e5 = 130 ; margin 1e5*1.1020/100 = 1102
            1: (10000.0, 10130.0, 1102.0, 10130.0 - 1102.0),
            2: (10310.0, 10310.0, 0.0, 10310.0),
            3: (10310.0, 10310.0, 0.0, 10310.0),
            4: (10310.0, 10310.0, 0.0, 10310.0),
        },
        final=(10310.0, 10310.0),
        open_at_end=0,
    ),
)

# G3 ---- market short, flat commission 7, PER_SIDE vs ROUND_TRIP
G3_BARS = bars([
    (1.2000, 1.2010, 1.1990, 1.2000),  # 0 signal sell 1 lot
    (1.2000, 1.2005, 1.1960, 1.1970),  # 1 fill sell @ 1.2000 - 0.0002 = 1.1998
    (1.1970, 1.1975, 1.1940, 1.1950),  # 2 signal close
    (1.1950, 1.1960, 1.1930, 1.1940),  # 3 fill buy-to-close @ 1.1950 + 0.0002 = 1.1952
    (1.1940, 1.1950, 1.1930, 1.1945),  # 4 flat
])
# gross = (1.1998 - 1.1952) * 1e5 = 460.00 ; margin = 1e5 * 1.1998 / 100 = 1199.98
SCENARIOS["G3a_short_comm7_per_side"] = dict(
    bars=G3_BARS,
    config=dict(fill_mode="NEXT_BAR_OPEN", spread=0.0002, slippage=0.0001,
                commission=7.0, commission_mode="PER_SIDE",
                commission_rate_per_unit=0.0),
    script={0: [("sell", 1.0, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            dict(raw_reference=1.2000, executed_price=1.1998, commission_amount=7.0),
            dict(raw_reference=1.1950, executed_price=1.1952, commission_amount=7.0),
        ],
        # net = 460 - 14 = 446
        closed=[dict(gross=460.0, commission=14.0, net=446.0, entry_price=1.1998,
                     exit_price=1.1952, exit_reason="explicit")],
        snaps={
            0: (10000.0, 10000.0, 0.0, 10000.0),
            # [GAP-8] balance 10000-7 = 9993; unreal (1.1998-1.1970)*1e5 = 280
            # CODE [GAP-7] margin 1e5*1.1970/100 = 1197 (pre-run: 1199.98)
            1: (9993.0, 10273.0, 1197.0, 10273.0 - 1197.0),
            # unreal (1.1998-1.1950)*1e5 = 480 ; margin 1e5*1.1950/100 = 1195
            2: (9993.0, 10473.0, 1195.0, 10473.0 - 1195.0),
            3: (10446.0, 10446.0, 0.0, 10446.0),
        },
        final=(10446.0, 10446.0),
        open_at_end=0,
    ),
)
SCENARIOS["G3b_short_comm7_round_trip"] = dict(
    bars=G3_BARS,
    config=dict(fill_mode="NEXT_BAR_OPEN", spread=0.0002, slippage=0.0001,
                commission=7.0, commission_mode="ROUND_TRIP",
                commission_rate_per_unit=0.0),
    script={0: [("sell", 1.0, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            # [GAP-8] round trip charged on the closing fill only (balance), BUT
            # CODE: the entry order_filled event still reports commission_amount=7
            # (pre-run: 0.0).  Reported as a finding (event field semantics).
            dict(raw_reference=1.2000, executed_price=1.1998, commission_amount=7.0),
            dict(raw_reference=1.1950, executed_price=1.1952, commission_amount=7.0),
        ],
        # net = 460 - 7 = 453
        closed=[dict(gross=460.0, commission=7.0, net=453.0, entry_price=1.1998,
                     exit_price=1.1952, exit_reason="explicit")],
        snaps={
            # CODE [GAP-7] margin 1e5*1.1970/100 = 1197
            1: (10000.0, 10280.0, 1197.0, 10280.0 - 1197.0),
            3: (10453.0, 10453.0, 0.0, 10453.0),
        },
        final=(10453.0, 10453.0),
        open_at_end=0,
    ),
)

# G4 ---- commission_rate_per_unit 0.00005, 0.5 lots (50,000 units), no spread/slip
G4_BARS = bars([
    (1.3000, 1.3010, 1.2990, 1.3000),  # 0 signal buy 0.5
    (1.3000, 1.3030, 1.2995, 1.3020),  # 1 fill @ 1.3000
    (1.3020, 1.3050, 1.3010, 1.3040),  # 2 signal close
    (1.3040, 1.3060, 1.3030, 1.3050),  # 3 fill close @ 1.3040
])
# gross = (1.3040-1.3000) * 50000 = 200.00 ; margin = 50000*1.3/100 = 650
SCENARIOS["G4a_rate_per_unit"] = dict(
    bars=G4_BARS,
    config=dict(fill_mode="NEXT_BAR_OPEN", spread=0.0, slippage=0.0,
                commission=0.0, commission_mode="PER_SIDE",
                commission_rate_per_unit=0.00005),
    script={0: [("buy", 0.5, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            # 0.00005 * 50000 = 2.50 per side
            dict(raw_reference=1.3000, executed_price=1.3000, commission_amount=2.5),
            dict(raw_reference=1.3040, executed_price=1.3040, commission_amount=2.5),
        ],
        closed=[dict(gross=200.0, commission=5.0, net=195.0, entry_price=1.3000,
                     exit_price=1.3040, exit_reason="explicit")],
        snaps={
            # balance 10000 - 2.5 ; unreal (1.3020-1.3000)*50000 = 100
            # CODE [GAP-7] margin 50000*1.3020/100 = 651 (pre-run: 650)
            1: (9997.5, 10097.5, 651.0, 10097.5 - 651.0),
            3: (10195.0, 10195.0, 0.0, 10195.0),
        },
        final=(10195.0, 10195.0),
        open_at_end=0,
    ),
)
SCENARIOS["G4b_flat_plus_rate"] = dict(
    bars=G4_BARS,
    config=dict(fill_mode="NEXT_BAR_OPEN", spread=0.0, slippage=0.0,
                commission=1.0, commission_mode="PER_SIDE",
                commission_rate_per_unit=0.00005),
    script={0: [("buy", 0.5, {})], 2: [("close_all",)]},
    expected=dict(
        fills=[
            # flat 1.00 + 0.00005*50000 = 3.50 per side
            dict(executed_price=1.3000, commission_amount=3.5),
            dict(executed_price=1.3040, commission_amount=3.5),
        ],
        closed=[dict(gross=200.0, commission=7.0, net=193.0, exit_reason="explicit")],
        final=(10193.0, 10193.0),
        open_at_end=0,
    ),
)

# Common protective-test entry: buy at bar1 open 1.1000 -> 1.1000+0.0001+0.0001 = 1.1002
PROT_COST = dict(fill_mode="NEXT_BAR_OPEN", spread=0.0002, slippage=0.0001,
                 commission=0.0, commission_mode="PER_SIDE",
                 commission_rate_per_unit=0.0)

# G5 ---- SL hit intrabar, no gap
SCENARIOS["G5_sl_intrabar"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0950 tp 1.1100
        (1.1000, 1.1020, 1.0980, 1.1010),  # 1 fill 1.1002 ; low 1.0980 > SL
        (1.1010, 1.1015, 1.0940, 1.0960),  # 2 open above SL, low through SL
        (1.0960, 1.0970, 1.0950, 1.0965),  # 3
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0950, "tp": 1.1100})]},
    expected=dict(
        fills=[dict(raw_reference=1.1000, executed_price=1.1002)],
        # CODE [GAP-2] exit = 1.0950 - 0.0001 - 0.0001 = 1.0948 (pre-run 1.0949)
        # gross (1.0948-1.1002)*1e5 = -540
        closed=[dict(gross=-540.0, commission=0.0, net=-540.0, entry_price=1.1002,
                     exit_price=1.0948, exit_reason="StopLoss", bar=2)],
        # CODE [GAP-7] bar1 margin 1e5*1.1010/100 = 1101
        snaps={1: (10000.0, 10080.0, 1101.0, 10080.0 - 1101.0),
               2: (9460.0, 9460.0, 0.0, 9460.0)},
        final=(9460.0, 9460.0),
        open_at_end=0,
    ),
)

# G5b --- position opened AT BAR OPEN is eligible for same-bar SL
SCENARIOS["G5b_sl_same_bar_as_open_fill"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0950
        (1.1000, 1.1010, 1.0940, 1.0960),  # 1 fill at open 1.1002, low hits SL same bar
        (1.0960, 1.0970, 1.0950, 1.0965),  # 2
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0950, "tp": 1.1100})]},
    expected=dict(
        fills=[dict(executed_price=1.1002)],
        # CODE [GAP-2] exit 1.0948 ; gross -540
        closed=[dict(gross=-540.0, net=-540.0, exit_price=1.0948,
                     exit_reason="StopLoss", bar=1)],
        final=(9460.0, 9460.0),
        open_at_end=0,
    ),
)

# G6 ---- TP hit intrabar, no gap
SCENARIOS["G6_tp_intrabar"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0900 tp 1.1050
        (1.1000, 1.1020, 1.0990, 1.1010),  # 1 fill 1.1002
        (1.1010, 1.1070, 1.1005, 1.1060),  # 2 high through TP
        (1.1060, 1.1070, 1.1050, 1.1065),  # 3
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0900, "tp": 1.1050})]},
    expected=dict(
        fills=[dict(executed_price=1.1002)],
        # [GAP-3] exit = 1.1050 exactly ; gross (1.1050-1.1002)*1e5 = 480
        closed=[dict(gross=480.0, commission=0.0, net=480.0, exit_price=1.1050,
                     exit_reason="TakeProfit", bar=2)],
        final=(10480.0, 10480.0),
        open_at_end=0,
    ),
)

# G7 ---- next bar gaps through SL
SCENARIOS["G7_sl_gap"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0950 tp 1.1200
        (1.1000, 1.1020, 1.0990, 1.1000),  # 1 fill 1.1002
        (1.0900, 1.0920, 1.0880, 1.0910),  # 2 opens below SL (gap)
        (1.0910, 1.0930, 1.0900, 1.0920),  # 3
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0950, "tp": 1.1200})]},
    expected=dict(
        fills=[dict(executed_price=1.1002)],
        # [GAP-4] exit = 1.0900 - 0.0001 - 0.0001 = 1.0898 ; gross = -1040
        closed=[dict(gross=-1040.0, net=-1040.0, exit_price=1.0898,
                     exit_reason="StopLoss", bar=2)],
        final=(8960.0, 8960.0),
        open_at_end=0,
    ),
)

# G8 ---- SL and TP both inside one bar (open between them) -> SL first
SCENARIOS["G8_sl_and_tp_same_bar"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0950 tp 1.1050
        (1.1000, 1.1020, 1.0990, 1.1000),  # 1 fill 1.1002
        (1.1000, 1.1060, 1.0940, 1.1000),  # 2 both reachable
        (1.1000, 1.1010, 1.0990, 1.1000),  # 3
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0950, "tp": 1.1050})]},
    expected=dict(
        # SL-first ; exit as G5 = CODE [GAP-2] 1.0948 ; gross -540
        closed=[dict(gross=-540.0, net=-540.0, exit_price=1.0948,
                     exit_reason="StopLoss", bar=2)],
        final=(9460.0, 9460.0),
        open_at_end=0,
    ),
)

# G9a --- BUY LIMIT resting, filled on a later bar; no retro fill on the
#         creation bar; position opened intrabar is NOT SL-evaluated on its fill bar
SCENARIOS["G9a_buy_limit"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0940, 1.1000),  # 0 place buy limit 1.0950 (bar0 low touched it: must NOT fill)
        (1.1000, 1.1010, 1.0960, 1.0990),  # 1 low 1.0960 > 1.0950 : rests
        (1.0990, 1.1000, 1.0900, 1.0960),  # 2 trades through 1.0950 -> fill 1.0950; low 1.0900 < SL 1.0920 but not eligible
        (1.0960, 1.0980, 1.0940, 1.0970),  # 3 low 1.0940 > SL ; signal close
        (1.0980, 1.0990, 1.0970, 1.0985),  # 4 close fill 1.0980 - 0.0002 = 1.0978
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"order_type": "limit", "price": 1.0950,
                              "sl": 1.0920, "tp": 1.1200})],
            3: [("close_all",)]},
    expected=dict(
        fills=[
            # [GAP-5] limit fill = 1.0950 exactly
            dict(executed_price=1.0950),
            dict(raw_reference=1.0980, executed_price=1.0978),
        ],
        fill_bars=[2, 4],
        # gross (1.0978-1.0950)*1e5 = 280
        closed=[dict(gross=280.0, net=280.0, entry_price=1.0950, exit_price=1.0978,
                     exit_reason="explicit", bar=4)],
        snaps={
            1: (10000.0, 10000.0, 0.0, 10000.0),
            # unreal (1.0960-1.0950)*1e5 = 100
            # CODE [GAP-7] margin 1e5*1.0960/100 = 1096 (pre-run 1095)
            2: (10000.0, 10100.0, 1096.0, 10100.0 - 1096.0),
            4: (10280.0, 10280.0, 0.0, 10280.0),
        },
        final=(10280.0, 10280.0),
        open_at_end=0,
    ),
)

# G9b --- BUY STOP entry, no gap; SL not evaluated on the intrabar fill bar
SCENARIOS["G9b_buy_stop"] = dict(
    bars=bars([
        (1.1000, 1.1060, 1.0990, 1.1000),  # 0 place buy stop 1.1050 (bar0 high touched it: must NOT fill)
        (1.1000, 1.1040, 1.0990, 1.1020),  # 1 high < 1.1050 : rests
        (1.1020, 1.1080, 1.1010, 1.1070),  # 2 triggers -> fill 1.1050 ; low 1.1010 < SL 1.1015 but not eligible
        (1.1070, 1.1090, 1.1060, 1.1080),  # 3 signal close
        (1.1080, 1.1085, 1.1070, 1.1075),  # 4 close fill 1.1080 - 0.0002 = 1.1078
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"order_type": "stop", "price": 1.1050,
                              "sl": 1.1015, "tp": 1.1300})],
            3: [("close_all",)]},
    expected=dict(
        # CODE [GAP-5] triggered stop is market-style: 1.1050 + 0.0001 + 0.0001
        # = 1.1052 (pre-run 1.1050)
        fills=[dict(raw_reference=1.1050, executed_price=1.1052,
                    spread_applied=0.0001, slippage_applied=0.0001),
               dict(executed_price=1.1078)],
        fill_bars=[2, 4],
        # gross (1.1078-1.1052)*1e5 = 260
        closed=[dict(gross=260.0, net=260.0, entry_price=1.1052, exit_price=1.1078,
                     exit_reason="explicit", bar=4)],
        final=(10260.0, 10260.0),
        open_at_end=0,
    ),
)

# G9c --- BUY STOP gapped through: bar opens above the stop price
SCENARIOS["G9c_buy_stop_gap"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 place buy stop 1.1050
        (1.1100, 1.1120, 1.1090, 1.1110),  # 1 opens above stop
        (1.1110, 1.1120, 1.1100, 1.1115),  # 2
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"order_type": "stop", "price": 1.1050})]},
    expected=dict(
        # [GAP-4/5] fill = 1.1100 + 0.0001 + 0.0001 = 1.1102
        fills=[dict(executed_price=1.1102)],
        fill_bars=[1],
        # unreal at end (1.1115-1.1102)*1e5 = 130
        final=(10000.0, 10130.0),
        open_at_end=1,
    ),
)

# G10 --- open position at end: balance != equity; margin = units*price/leverage
SCENARIOS["G10_open_at_end"] = dict(
    bars=bars([
        (1.2500, 1.2510, 1.2490, 1.2500),  # 0 buy 2 lots
        (1.2500, 1.2520, 1.2495, 1.2510),  # 1 fill 1.2500+0.0002 = 1.2503
        (1.2510, 1.2540, 1.2505, 1.2530),  # 2 end
    ]),
    config=PROT_COST,
    script={0: [("buy", 2.0, {})]},
    expected=dict(
        # verifier slip #2 corrected: 1.2500 + 0.0001 + 0.0001 = 1.2502
        fills=[dict(raw_reference=1.2500, executed_price=1.2502)],
        closed=[],
        snaps={
            # units 200000 ; unreal (1.2510-1.2502)*2e5 = 160
            # CODE [GAP-7] margin 2e5*1.2510/100 = 2502
            1: (10000.0, 10160.0, 2502.0, 10160.0 - 2502.0),
            # unreal (1.2530-1.2502)*2e5 = 560 ; margin 2e5*1.2530/100 = 2506
            2: (10000.0, 10560.0, 2506.0, 10560.0 - 2506.0),
        },
        final=(10000.0, 10560.0),
        open_at_end=1,
    ),
)
# ---------------------------------------------------------------------------
# Post-review regression scenarios (added AFTER consulting semantics.rs)
# ---------------------------------------------------------------------------
# Short entry: sell at bar1 open 1.1000 -> 1.1000 - 0.0001 - 0.0001 = 1.0998

# G5s --- short SL intrabar (sign symmetry of G5)
SCENARIOS["G5s_short_sl_intrabar"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 sell sl 1.1050 tp 1.0900
        (1.1000, 1.1020, 1.0980, 1.0990),  # 1 fill 1.0998 ; high 1.1020 < SL
        (1.0990, 1.1060, 1.0985, 1.1040),  # 2 high through SL
        (1.1040, 1.1050, 1.1030, 1.1045),  # 3
    ]),
    config=PROT_COST,
    script={0: [("sell", 1.0, {"sl": 1.1050, "tp": 1.0900})]},
    expected=dict(
        fills=[dict(raw_reference=1.1000, executed_price=1.0998)],
        # exit (buy) = 1.1050 + 0.0001 + 0.0001 = 1.1052 ; gross (1.0998-1.1052)*1e5 = -540
        closed=[dict(gross=-540.0, net=-540.0, entry_price=1.0998, exit_price=1.1052,
                     exit_reason="StopLoss", bar=2)],
        # bar1 unreal (1.0998-1.0990)*1e5 = 80 ; margin 1e5*1.0990/100 = 1099
        snaps={1: (10000.0, 10080.0, 1099.0, 10080.0 - 1099.0)},
        final=(9460.0, 9460.0),
        open_at_end=0,
    ),
)

# G6s --- short TP intrabar
SCENARIOS["G6s_short_tp_intrabar"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 sell sl 1.1100 tp 1.0950
        (1.1000, 1.1020, 1.0980, 1.0990),  # 1 fill 1.0998
        (1.0990, 1.0995, 1.0940, 1.0945),  # 2 low through TP
        (1.0945, 1.0950, 1.0940, 1.0948),  # 3
    ]),
    config=PROT_COST,
    script={0: [("sell", 1.0, {"sl": 1.1100, "tp": 1.0950})]},
    expected=dict(
        # exit = TP exactly 1.0950 ; gross (1.0998-1.0950)*1e5 = 480
        closed=[dict(gross=480.0, net=480.0, exit_price=1.0950,
                     exit_reason="TakeProfit", bar=2)],
        final=(10480.0, 10480.0),
        open_at_end=0,
    ),
)

# G6g --- long TP gapped through: opens above TP -> fills at the open
SCENARIOS["G6g_tp_gap"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 buy sl 1.0900 tp 1.1050
        (1.1000, 1.1020, 1.0990, 1.1010),  # 1 fill 1.1002
        (1.1080, 1.1090, 1.1070, 1.1085),  # 2 opens above TP
        (1.1085, 1.1090, 1.1080, 1.1088),  # 3
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"sl": 1.0900, "tp": 1.1050})]},
    expected=dict(
        # exit = open 1.1080 (favourable, no spread/slip) ; gross (1.1080-1.1002)*1e5 = 780
        closed=[dict(gross=780.0, net=780.0, exit_price=1.1080,
                     exit_reason="TakeProfit", bar=2)],
        final=(10780.0, 10780.0),
        open_at_end=0,
    ),
)

# G9d --- BUY LIMIT where the next bar opens below the limit -> fill at open
SCENARIOS["G9d_buy_limit_gap"] = dict(
    bars=bars([
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0 place buy limit 1.0950
        (1.0900, 1.0920, 1.0890, 1.0910),  # 1 opens below limit -> fill 1.0900
        (1.0910, 1.0930, 1.0900, 1.0920),  # 2
    ]),
    config=PROT_COST,
    script={0: [("buy", 1.0, {"order_type": "limit", "price": 1.0950})]},
    expected=dict(
        fills=[dict(executed_price=1.0900, spread_applied=0.0, slippage_applied=0.0)],
        fill_bars=[1],
        # end unreal (1.0920-1.0900)*1e5 = 200
        final=(10000.0, 10200.0),
        open_at_end=1,
    ),
)

# G11 --- insufficient margin rejects the entry (documented in known-limitations)
SCENARIOS["G11_margin_rejection"] = dict(
    bars=SCENARIOS["G1_long_next_bar_open"]["bars"],
    config=dict(PROT_COST, starting_balance=1000.0),
    script={0: [("buy", 1.0, {})]},
    expected=dict(
        # required 1e5*1.1012/100 = 1101.2 > free 1000 -> order_rejected
        rejections=1,
        fills=[],
        closed=[],
        final=(1000.0, 1000.0),
        open_at_end=0,
    ),
)
# --- END OF EXPECTATIONS ---------------------------------------------------


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class Scripted:
    """Deterministic scripted strategy: actions keyed by bar index (= len(history))."""

    def __init__(self, script):
        self.script = script

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        out = []
        for act in self.script.get(i, []):
            if act[0] == "close_all":
                for pos in portfolio["open_positions"]:
                    out.append({"direction": "close", "size": pos["size"],
                                "ticket": pos["position_id"],
                                "reason": f"scripted close at bar {i}"})
            else:
                direction, lots, extra = act
                sig = {"direction": direction, "size": lots,
                       "reason": f"scripted {direction} at bar {i}"}
                sig.update(extra)
                out.append(sig)
        return out

    def teardown(self):
        pass


def make_config(cfg):
    kw = dict(BASE)
    for k, v in cfg.items():
        if k in ("fill_mode", "commission_mode"):
            v = getattr(observa, v)
        kw[k] = v
    return observa.Config(**kw)


def run_scenario(name, sc, root):
    out = os.path.join(root, name)
    result = observa.run(Scripted(sc["script"]), sc["bars"],
                         config=make_config(sc["config"]), output=out)
    events = [json.loads(l) for l in Path(out, "events.jsonl").read_text().splitlines() if l.strip()]
    return result, events, out


class Checker:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.rows = []

    def check(self, scen, label, expected, actual, tol):
        if isinstance(expected, str) or expected is None or isinstance(expected, bool):
            ok = expected == actual
        elif actual is None:
            ok = False
        else:
            ok = abs(float(expected) - float(actual)) <= tol
        status = "PASS" if ok else "FAIL"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        line = f"{status}  {scen:32s} {label:40s} expected={expected!r:<22} actual={actual!r}"
        self.rows.append(line)
        print(line)
        return ok


def verify(name, sc, result, events, ck):
    exp = sc["expected"]
    fills = [e for e in events if e["type"] == "order_filled"]
    closes = [e for e in events if e["type"] == "position_closed"]
    snaps = {e["bar_index"]: e for e in events if e["type"] == "portfolio_snapshot"}
    done = [e for e in events if e["type"] == "run_completed"][0]
    rejects = [e for e in events if e["type"] == "order_rejected"]

    ck.check(name, "order_rejected count", exp.get("rejections", 0), len(rejects), 0)

    if "fills" in exp:
        ck.check(name, "fill count", len(exp["fills"]), len(fills), 0)
        for k, ef in enumerate(exp["fills"]):
            af = fills[k] if k < len(fills) else {}
            for key, val in ef.items():
                tol = MONEY_TOL if key == "commission_amount" else PRICE_TOL
                ck.check(name, f"fill[{k}].{key}", val, af.get(key), tol)
    if "fill_bars" in exp:
        for k, b in enumerate(exp["fill_bars"]):
            ab = fills[k]["bar_index"] if k < len(fills) else None
            ck.check(name, f"fill[{k}].bar_index", b, ab, 0)

    if "closed" in exp:
        ck.check(name, "position_closed count", len(exp["closed"]), len(closes), 0)
        keymap = {"gross": "gross_realized_pnl", "commission": "total_commission",
                  "net": "net_realized_pnl", "entry_price": "entry_price",
                  "exit_price": "exit_price", "bar": "bar_index"}
        for k, ec in enumerate(exp["closed"]):
            ac = closes[k] if k < len(closes) else {}
            for key, val in ec.items():
                if key == "exit_reason":
                    if val == "explicit":
                        r = ac.get("exit_reason")
                        ck.check(name, f"closed[{k}].exit_reason is explicit (not SL/TP)",
                                 True, r is not None and r not in ("StopLoss", "TakeProfit"), 0)
                    else:
                        ck.check(name, f"closed[{k}].exit_reason", val, ac.get("exit_reason"), 0)
                    continue
                tol = PRICE_TOL if key in ("entry_price", "exit_price") else (0 if key == "bar" else MONEY_TOL)
                ck.check(name, f"closed[{k}].{keymap[key]}", val, ac.get(keymap[key]), tol)
            # documented identity: net = gross - total_commission
            if ac:
                ck.check(name, f"closed[{k}] net == gross - commission",
                         ac["gross_realized_pnl"] - ac["total_commission"],
                         ac["net_realized_pnl"], MONEY_TOL)

    for b, (bal, eq, um, fm) in exp.get("snaps", {}).items():
        s = snaps.get(b, {})
        ck.check(name, f"snap[{b}].balance", bal, s.get("balance"), MONEY_TOL)
        ck.check(name, f"snap[{b}].equity", eq, s.get("equity"), MONEY_TOL)
        ck.check(name, f"snap[{b}].used_margin", um, s.get("used_margin"), MONEY_TOL)
        ck.check(name, f"snap[{b}].free_margin", fm, s.get("free_margin"), MONEY_TOL)

    # documented identities on EVERY snapshot
    for b in sorted(snaps):
        s = snaps[b]
        ck.check(name, f"snap[{b}] equity == balance + unrealised",
                 s["balance"] + s["unrealised_pnl"], s["equity"], MONEY_TOL)
        ck.check(name, f"snap[{b}] free == equity - used_margin",
                 s["equity"] - s["used_margin"], s["free_margin"], MONEY_TOL)
    ck.check(name, "one snapshot per bar", len(sc["bars"]), len(snaps), 0)

    if "final" in exp:
        fb, fe = exp["final"]
        ck.check(name, "run_completed.final_balance", fb, done["final_balance"], MONEY_TOL)
        ck.check(name, "run_completed.final_equity", fe, done["final_equity"], MONEY_TOL)
        ck.check(name, "result.final_balance", fb, result.final_balance, MONEY_TOL)
        ck.check(name, "result.final_equity", fe, result.final_equity, MONEY_TOL)
    if "open_at_end" in exp:
        ck.check(name, "open_positions_remaining", exp["open_at_end"],
                 done["open_positions_remaining"], 0)


def main(argv):
    keep = "--keep" in argv
    only = [a for a in argv if not a.startswith("--")]
    root = tempfile.mkdtemp(prefix="observa_golden_", dir=os.environ.get("GOLDEN_RUN_ROOT"))
    print(f"observa {observa.__version__}  runs under {root}")
    print(f"tolerances: price {PRICE_TOL}  money {MONEY_TOL}\n")
    ck = Checker()
    for name, sc in SCENARIOS.items():
        if only and name not in only:
            continue
        result, events, _ = run_scenario(name, sc, root)
        verify(name, sc, result, events, ck)
    print(f"\nTOTAL: {ck.passed} passed, {ck.failed} failed")
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"run directories kept under {root}")
    return 1 if ck.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
