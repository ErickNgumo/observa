#!/usr/bin/env python
"""Edge-case probes for OBS-TRUST-01..03, run under each build and compared.

    <released-python> trust_edge_probes.py run OUT_REL.json [--extra-site DIR]
    <fixed-python>    trust_edge_probes.py run OUT_FIX.json [--extra-site DIR]
    python            trust_edge_probes.py compare OUT_REL.json OUT_FIX.json

--extra-site appends a site-packages dir (pandas/numpy) to sys.path at the END,
so the Observa package under test always wins; nothing is installed.

Each probe records: accepted|error (+code, message head) and, when accepted, an
economics digest (fills, closes, final balance/equity) plus probe-specific
observations.
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import json
import math
import os
import pickle
import sys
import tempfile

UTC = dt.timezone.utc


def base_rows(n=40):
    rows = []
    p = 1.1000
    for i in range(n):
        o = round(p, 5)
        c = round(o + (0.0010 if (i // 5) % 2 == 0 else -0.0010), 5)
        rows.append({"timestamp": (dt.datetime(2024, 1, 1, tzinfo=UTC) + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": round(max(o, c) + 0.0005, 5), "low": round(min(o, c) - 0.0005, 5),
                     "close": c, "volume": 100.0})
        p = c
    return rows


class Trader:
    """Deterministic: buy every 6th bar with SL/TP, close after 3 bars."""

    def initialize(self, params=None):
        self.notes = {}

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        out = []
        if i % 6 == 1:
            out.append({"direction": "buy", "size": 1.0, "sl": round(bar["close"] - 0.0030, 5),
                        "tp": round(bar["close"] + 0.0030, 5), "reason": "probe entry"})
        for p in portfolio["open_positions"]:
            if i % 6 == 4:
                out.append({"direction": "close", "size": p["size"], "ticket": p["position_id"],
                            "reason": "probe exit"})
        return out

    def teardown(self):
        pass


def econ(res_dir):
    ev = [json.loads(l) for l in open(os.path.join(res_dir, "events.jsonl"))]
    fills = [(e["bar_index"], e["side"], e["executed_price"]) for e in ev if e["type"] == "order_filled"]
    closes = [(e["bar_index"], e["exit_reason"], round(e["net_realized_pnl"], 6)) for e in ev if e["type"] == "position_closed"]
    done = [e for e in ev if e["type"] in ("run_completed", "run_failed")][-1]
    ts = [e["timestamp"] for e in ev if e["type"] == "bar_processed"][:3]
    rj = json.load(open(os.path.join(res_dir, "run.json")))
    return {"n_fills": len(fills), "fills_head": fills[:4], "closes": closes[:6],
            "final": [round(done.get("final_balance", float("nan")), 6), round(done.get("final_equity", float("nan")), 6)],
            "first_ts": ts, "dataset_sha": rj["dataset"]["sha256"], "strategy_block": rj["strategy"],
            "run_started": [e for e in ev if e["type"] == "run_started"][0]}


def attempt(observa, root, name, strat, data, cfg=None, extra=None):
    out_dir = os.path.join(root, name)
    rec = {}
    try:
        observa.run(strat, data, config=cfg or observa.Config(interval="1h"), output=out_dir)
        rec["result"] = "accepted"
        rec["econ"] = econ(out_dir)
    except Exception as e:
        rec["result"] = "error"
        rec["code"] = getattr(e, "code", None)
        rec["msg"] = f"{type(e).__name__}: {str(e)[:220]}"
        if os.path.exists(os.path.join(out_dir, "events.jsonl")):
            try:
                rec["econ_partial"] = econ(out_dir)
            except Exception:
                pass
    if extra:
        rec.update(extra())
    return rec


# ---------------------------------------------------------------------------
# data probes
# ---------------------------------------------------------------------------

def data_probes(observa, root, pd):
    R = {}
    rows = base_rows()

    def mod(fn):
        r = [dict(x) for x in rows]
        fn(r)
        return r

    R["D00_baseline"] = attempt(observa, root, "D00", Trader(), rows)
    R["D01_zero_volume_all"] = attempt(observa, root, "D01", Trader(), mod(lambda r: [x.update(volume=0.0) for x in r]))

    def flat(r):
        for x in r[10:20]:
            v = x["open"]
            x.update(high=v, low=v, close=v)
        for i in range(10, 21):
            r[i]["open"] = r[i - 1]["close"] if i > 10 else r[i]["open"]
            r[i]["high"] = max(r[i]["high"], r[i]["open"], r[i]["close"])
            r[i]["low"] = min(r[i]["low"], r[i]["open"], r[i]["close"])
    R["D02_flat_bars_OHLC_equal"] = attempt(observa, root, "D02", Trader(), mod(flat))
    R["D03_volume_nan_one_bar"] = attempt(observa, root, "D03", Trader(), mod(lambda r: r[7].update(volume=float("nan"))))
    R["D04_close_nan_one_bar"] = attempt(observa, root, "D04", Trader(), mod(lambda r: r[7].update(close=float("nan"))))
    R["D05_high_inf"] = attempt(observa, root, "D05", Trader(), mod(lambda r: r[7].update(high=float("inf"))))
    R["D06_high_below_low"] = attempt(observa, root, "D06", Trader(), mod(lambda r: r[7].update(high=r[7]["low"] - 0.001)))
    R["D07_close_above_high_by_1e-12"] = attempt(observa, root, "D07", Trader(), mod(lambda r: r[7].update(close=r[7]["high"] + 1e-12)))
    R["D08_negative_prices"] = attempt(observa, root, "D08", Trader(), mod(lambda r: r[7].update(low=-0.5)))
    R["D09_zero_low"] = attempt(observa, root, "D09", Trader(), mod(lambda r: r[7].update(low=0.0)))
    R["D10_naive_space_string"] = attempt(observa, root, "D10", Trader(), mod(lambda r: [x.update(timestamp=x["timestamp"].replace("T", " ").rstrip("Z")) for x in r]))
    R["D11_naive_T_string"] = attempt(observa, root, "D11", Trader(), mod(lambda r: [x.update(timestamp=x["timestamp"].rstrip("Z")) for x in r]))
    R["D12_plus03_offset_string"] = attempt(observa, root, "D12", Trader(), mod(lambda r: [x.update(timestamp=(dt.datetime.strptime(x["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(dt.timezone(dt.timedelta(hours=3)))).isoformat()) for x in r]))
    epoch = lambda x: dt.datetime.strptime(x["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    R["D13_epoch_ms_int"] = attempt(observa, root, "D13", Trader(), mod(lambda r: [x.update(timestamp=int(epoch(x) * 1000)) for x in r]))
    R["D14_epoch_float_half_second"] = attempt(observa, root, "D14", Trader(), mod(lambda r: [x.update(timestamp=epoch(x) + 0.5) for x in r]))
    R["D15_epoch_float_floor_collision"] = attempt(observa, root, "D15", Trader(), mod(lambda r: [x.update(timestamp=1_700_000_000 + i * 0.4) for i, x in enumerate(r)]))
    R["D16_aware_datetime"] = attempt(observa, root, "D16", Trader(), mod(lambda r: [x.update(timestamp=dt.datetime.strptime(x["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)) for x in r]))
    R["D17_naive_datetime"] = attempt(observa, root, "D17", Trader(), mod(lambda r: [x.update(timestamp=dt.datetime.strptime(x["timestamp"], "%Y-%m-%dT%H:%M:%SZ")) for x in r]))
    R["D18_subsecond_string"] = attempt(observa, root, "D18", Trader(), mod(lambda r: [x.update(timestamp=x["timestamp"].replace("Z", ".250Z")) for x in r]))
    R["D19_duplicate_timestamp"] = attempt(observa, root, "D19", Trader(), mod(lambda r: r[8].update(timestamp=r[7]["timestamp"])))
    R["D20_volume_int"] = attempt(observa, root, "D20", Trader(), mod(lambda r: [x.update(volume=int(x["volume"])) for x in r]))

    # CSV path
    def csv_case(name, fn):
        r = mod(fn)
        p = os.path.join(root, name + ".csv")
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for x in r:
                w.writerow([x["timestamp"], x["open"], x["high"], x["low"], x["close"], x["volume"]])
        return attempt(observa, root, name, Trader(), p)
    R["C00_csv_baseline"] = csv_case("C00", lambda r: None)
    R["C01_csv_nan_close"] = csv_case("C01", lambda r: r[7].update(close="NaN"))
    R["C02_csv_empty_volume"] = csv_case("C02", lambda r: r[7].update(volume=""))
    R["C03_csv_nan_volume"] = csv_case("C03", lambda r: r[7].update(volume="nan"))
    R["C04_csv_zero_volume"] = csv_case("C04", lambda r: [x.update(volume=0) for x in r])

    if pd is not None:
        def df_from(r, tsconv):
            d = pd.DataFrame(r)
            d["timestamp"] = tsconv(d["timestamp"])
            return d
        R["P00_df_string_ts"] = attempt(observa, root, "P00", Trader(), pd.DataFrame(rows))
        R["P01_df_tz_aware"] = attempt(observa, root, "P01", Trader(), df_from(rows, lambda s: pd.to_datetime(s, utc=True)))
        R["P02_df_naive_datetime64"] = attempt(observa, root, "P02", Trader(), df_from(rows, lambda s: pd.to_datetime(s, utc=True).dt.tz_localize(None)))
        dfv = pd.DataFrame(rows)
        dfv.loc[7, "volume"] = float("nan")
        R["P03_df_missing_volume_nan"] = attempt(observa, root, "P03", Trader(), dfv)
        dfi = pd.DataFrame(rows)
        dfi["volume"] = dfi["volume"].astype("int64")
        R["P04_df_int64_volume"] = attempt(observa, root, "P04", Trader(), dfi)
    return R


# ---------------------------------------------------------------------------
# return-shape / signal / config probes
# ---------------------------------------------------------------------------

class Returns:
    def __init__(self, mode):
        self.mode = mode
        self.__class__ = type("Ret_" + mode, (Returns,), {})

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        sig = {"direction": "buy", "size": 1.0, "reason": "r"}
        m = self.mode
        if i != 3:
            return {"signals": [], "drawings": []} if m.startswith("env") else []
        return {
            "drawings_only": {"drawings": []},
            "empty_dict": {},
            "signals_none": {"signals": None},
            "bare_dict": sig,
            "none": None,
            "tuple": (sig,),
            "stop_loss_key": [dict(sig, stop_loss=1.0)],
            "quantity_key": [{"direction": "buy", "quantity": 1.0}],
            "upper_SL_key": [dict(sig, SL=1.0)],
            "invalid_second_signal": [sig, {"direction": "hold", "size": 1.0}],
            "invalid_first_signal": [{"direction": "hold", "size": 1.0}, sig],
            "env_extra_key": {"signals": [sig], "meta": 1},
            "env_ok": {"signals": [sig], "drawings": []},
        }[m]

    def teardown(self):
        pass


def return_probes(observa, root):
    R = {}
    for m in ("drawings_only", "empty_dict", "signals_none", "bare_dict", "none", "tuple",
              "stop_loss_key", "quantity_key", "upper_SL_key", "invalid_second_signal",
              "invalid_first_signal", "env_extra_key", "env_ok"):
        R[f"R_{m}"] = attempt(observa, root, f"R_{m}", Returns(m), base_rows(8))
    return R


def config_probes(observa, root):
    R = {}
    rows = base_rows()
    R["K00_no_strategy_name"] = attempt(observa, root, "K00", Trader(), rows, observa.Config(interval="1h"))
    R["K01_strategy_name_set"] = attempt(observa, root, "K01", Trader(), rows, observa.Config(interval="1h", strategy_name="MyLabel"))

    class Other(Trader):
        pass
    R["K02_other_class_same_label"] = attempt(observa, root, "K02", Other(), rows, observa.Config(interval="1h", strategy_name="MyLabel"))
    d = observa.Config(interval="1h")
    try:
        from dataclasses import asdict
        dd = asdict(d)
    except Exception:
        dd = dict(d.__dict__)
    dd = {k: v for k, v in dd.items() if v is not None}
    typo = dict(dd, spred=0.01)
    out_dir = os.path.join(root, "K03")
    try:
        observa.run(Trader(), rows, config=typo, output=out_dir)
        R["K03_dict_typo_spred"] = {"result": "accepted", "econ": econ(out_dir)}
    except Exception as e:
        R["K03_dict_typo_spred"] = {"result": "error", "code": getattr(e, "code", None), "msg": str(e)[:200]}
    # tick/pip size: dict path on both builds, Config path where supported
    out_dir = os.path.join(root, "K04")
    try:
        observa.run(Trader(), rows, config=dict(dd, tick_size=0.00001, pip_size=0.0001), output=out_dir)
        R["K04_dict_tick_pip"] = {"result": "accepted", "econ": econ(out_dir)}
    except Exception as e:
        R["K04_dict_tick_pip"] = {"result": "error", "code": getattr(e, "code", None), "msg": str(e)[:200]}
    try:
        cfg = observa.Config(interval="1h", tick_size=0.00001, pip_size=0.0001)
        R["K05_Config_tick_pip"] = attempt(observa, root, "K05", Trader(), rows, cfg)
    except TypeError as e:
        R["K05_Config_tick_pip"] = {"result": "error", "msg": f"TypeError: {e}"[:200]}
    return R


# ---------------------------------------------------------------------------
# history compatibility probes
# ---------------------------------------------------------------------------

class HistProbe:
    def __init__(self, pd, np):
        self.pd, self.np = pd, np
        self.res = {}
        self.kept = None

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = len(history)
        if i == 0:
            self.res["eq_empty_list_bar0"] = repr(history == [])
            self.res["bool_bar0"] = repr(bool(history))
        if i == 3:
            self.kept = history
        if i == 6:
            def t(name, f):
                try:
                    v = f()
                    self.res[name] = repr(v)[:160]
                except Exception as e:
                    self.res[name] = f"EXC {type(e).__name__}"
            t("type_name", lambda: type(history).__name__)
            t("isinstance_list", lambda: isinstance(history, list))
            t("bar_keys", lambda: sorted(bar))
            t("hist_keys", lambda: sorted(history[-1]))
            t("json_dumps_len", lambda: len(json.dumps(history)))
            t("deepcopy_len", lambda: len(copy.deepcopy(history)))
            t("pickle_len", lambda: len(pickle.loads(pickle.dumps(history))))
            t("plus_list", lambda: len(history + [bar]))
            t("list_plus", lambda: len([bar] + history))
            t("sorted_first_close", lambda: sorted(history, key=lambda h: h["close"])[0]["close"])
            t("reverse_slice_first", lambda: history[::-1][0]["timestamp"])
            t("neg_index", lambda: history[-6]["timestamp"])
            t("copy_type", lambda: type(history.copy()).__name__)
            t("kept_view_len", lambda: len(self.kept))
            t("eq_list_copy", lambda: history == list(history))
            t("max_by", lambda: max(history, key=lambda h: h["high"])["high"])
            t("sum_values_last", lambda: sum(v for v in history[-1].values() if isinstance(v, (int, float)) and v is not None))
            t("len_bar", lambda: len(bar))
            if self.pd is not None:
                t("pd_df_columns", lambda: list(self.pd.DataFrame(history).columns))
                t("pd_df_shape", lambda: self.pd.DataFrame(history).shape)
                t("pd_df_numeric_mean_cols", lambda: list(self.pd.DataFrame(history).select_dtypes("number").columns))
            if self.np is not None:
                t("np_array_shape", lambda: self.np.array(history).shape)
                t("np_closes_mean", lambda: float(self.np.mean([h["close"] for h in history])))
                t("np_array_len", lambda: len(self.np.array(history)))
            # mutating probes LAST (they alter the released build's list)
            t("mutate_then_reread", lambda: (history[-1].__setitem__("close", -1.0), history[-1]["close"])[1])
            t("append", lambda: history.append(bar))
            t("sort", lambda: history.sort(key=lambda h: h["close"]))
        if i == 7:
            self.res["next_bar_len_after_append"] = repr(len(history))
            self.res["next_bar_hist5_close"] = repr(history[5]["close"])
        return []

    def teardown(self):
        pass


def history_probes(observa, root, pd, np):
    hp = HistProbe(pd, np)
    rec = attempt(observa, root, "H", hp, base_rows(10))
    rec["observations"] = hp.res
    return {"H_history_compat": rec}


def run(out_json, extra_site):
    if extra_site:
        sys.path.append(extra_site)
    try:
        import pandas as pd
    except Exception:
        pd = None
    try:
        import numpy as np
    except Exception:
        np = None
    import observa
    root = tempfile.mkdtemp(prefix="trust_probe_", dir=os.environ.get("GOLDEN_RUN_ROOT"))
    res = {"observa": observa.__file__, "History": hasattr(observa, "History"),
           "pandas": getattr(pd, "__version__", None)}
    res.update(data_probes(observa, root, pd))
    res.update(return_probes(observa, root))
    res.update(config_probes(observa, root))
    res.update(history_probes(observa, root, pd, np))
    with open(out_json, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True, default=str)
    print("wrote", out_json, "runs under", root)


def compare(a, b):
    A, B = json.load(open(a)), json.load(open(b))
    for k in sorted(set(A) | set(B)):
        ra, rb = A.get(k), B.get(k)
        if not isinstance(ra, dict) or not isinstance(rb, dict):
            continue
        def summ(r):
            if r.get("result") == "accepted":
                e = r.get("econ", {})
                return f"accepted fills={e.get('n_fills')} final={e.get('final')}"
            return f"{r.get('result')} {r.get('code')} {r.get('msg', '')[:110]}"
        same_econ = ra.get("econ", {}).get("closes") == rb.get("econ", {}).get("closes") and \
            ra.get("econ", {}).get("final") == rb.get("econ", {}).get("final")
        tag = "SAME" if (ra.get("result") == rb.get("result") and ra.get("code") == rb.get("code")
                         and same_econ) else "DIFF"
        print(f"{tag} {k}\n   released: {summ(ra)}\n   fixed:    {summ(rb)}")
        if "observations" in ra:
            for ok in sorted(set(ra["observations"]) | set(rb["observations"])):
                va, vb = ra["observations"].get(ok), rb["observations"].get(ok)
                print(f"   {'  ' if va == vb else '!='} {ok:26s} rel={va}  fix={vb}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        es = sys.argv[sys.argv.index("--extra-site") + 1] if "--extra-site" in sys.argv else None
        run(sys.argv[2], es)
    else:
        compare(sys.argv[2], sys.argv[3])
