"""OBS-SCHEMA-01 — persisted strategy decision reasons (installed wheel).

Run against an installed Observa wheel:

    python python/tests/test_strategy_reason.py

Covers the Python-visible contract end-to-end: the bridge no longer substitutes
placeholder prose, authored text is preserved exactly, the 1024-byte UTF-8 limit
fails deterministically, reasons survive order rejection, the signal→order
invariant holds, historical runs still load, and ``inspect_run`` surfaces the
reason verbatim through the canonical ``strategy_decision`` event.

See ``docs/STRATEGY_API.md`` (§ Signal fields, § Run inspection) for the
contract.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

import observa

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_canonical_baseline as tb  # noqa: E402

DATA = observa.sample_data_path()
MAX_BYTES = 1024
PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


def cfg(**kw):
    base = dict(fill_mode=observa.NEXT_BAR_OPEN, spread=0.0002, slippage=0.0001,
                commission=7.0, commission_mode=observa.ROUND_TRIP, interval="15m",
                dataset_source=DATA)
    base.update(kw)
    return observa.Config(**base)


class EmitOn:
    """Emits a fixed signal list on one bar (default bar 0)."""

    def __init__(self, signals, at=0):
        self.signals = signals
        self.at = at
        self.n = 0

    def initialize(self, params=None):
        pass

    def teardown(self):
        pass

    def on_bar(self, bar, portfolio, history):
        i = self.n
        self.n += 1
        return list(self.signals) if i == self.at else []


class MixedOutcomes:
    """bar0: open. bar1: close + rejected entry + accepted entry."""

    def __init__(self):
        self.n = 0

    def initialize(self, params=None):
        pass

    def teardown(self):
        pass

    def on_bar(self, bar, portfolio, history):
        i = self.n
        self.n += 1
        if i == 0:
            return [{"direction": "buy", "size": 1.0, "reason": "entry"}]
        if i == 1:
            out = [
                {"direction": "buy", "size": 0.0, "reason": "rejected size"},
                {"direction": "buy", "size": 1.0, "reason": "accepted"},
            ]
            if portfolio["open_positions"]:
                p = portfolio["open_positions"][0]
                out.insert(0, {"direction": "close", "size": p["size"],
                               "ticket": p["position_id"], "reason": "exit"})
            return out
        return []


def run_strategy(strategy, tmp, name="run", data=None):
    out = os.path.join(tmp, name)
    observa.run(strategy, data or DATA, config=cfg(), output=out)
    return out


def decisions(run_dir):
    with open(os.path.join(run_dir, "events.jsonl")) as fh:
        return [json.loads(l) for l in fh if l.strip()
                and json.loads(l).get("type") == "strategy_decision"]


def raw_lines(run_dir):
    with open(os.path.join(run_dir, "events.jsonl"), "rb") as fh:
        return fh.read()


def main():
    tmp = tempfile.mkdtemp(prefix="qa-schema01-")
    try:
        # 1. authored reason persists verbatim and is inspectable
        run_dir = run_strategy(EmitOn([{"direction": "buy", "size": 1.0,
                                        "reason": "price crossed above VWAP"}]), tmp, "authored")
        dec = decisions(run_dir)[0]
        check("authored reason is persisted on strategy_decision",
              dec.get("signals") == [{"signal_index": 0, "reason": "price crossed above VWAP"}],
              dec.get("signals"))
        ins = observa.inspect_run(run_dir)
        bar0 = ins.bar(0)["strategy_decisions"][0]
        check("inspect_run surfaces the reason verbatim through bar()",
              bar0["signals"][0]["reason"] == "price crossed above VWAP")
        check("inspect_run surfaces it through events() too",
              ins.events(event_type="strategy_decision")[0]["signals"][0]["reason"]
              == "price crossed above VWAP")

        # 2/3. absent and empty reason → no placeholder, no `signals` field
        for label, sig in (("missing", {"direction": "buy", "size": 1.0}),
                           ("empty", {"direction": "buy", "size": 1.0, "reason": ""})):
            d = run_strategy(EmitOn([sig]), tmp, "no_reason_" + label)
            decs = decisions(d)
            check("absent/empty reason (%s) omits 'signals'" % label,
                  all("signals" not in e for e in decs), decs)
            check("no 'Python strategy signal' placeholder (%s)" % label,
                  "Python strategy signal" not in raw_lines(d).decode("utf-8"))

        # 4/5. Unicode and control characters round-trip exactly, jsonl intact
        text = "  spaced  \n line2\ttab \"quoted\" back\\slash é中文😀  "
        d = run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": text}]),
                         tmp, "unicode")
        dec = decisions(d)[0]
        check("Unicode/control text is preserved exactly",
              dec["signals"][0]["reason"] == text, repr(dec["signals"][0]["reason"]))
        blob = raw_lines(d).decode("utf-8")
        events_in_file = len([l for l in blob.split("\n") if l.strip()])
        check("a reason with newlines keeps events.jsonl one line per event",
              events_in_file == len([json.loads(l) for l in blob.split("\n") if l.strip()]),
              events_in_file)
        # the file must carry JSON escapes, not raw control characters, so the
        # one-event-per-line format cannot be broken by authored text
        check("control characters are JSON-escaped in the raw file",
              "\\n" in blob and "\\t" in blob and '\\"' in blob and "\\\\" in blob,
              blob[blob.find("spaced") - 10: blob.find("spaced") + 60])

        # 6. multiple signals: dense, index-aligned, nulls where absent
        d = run_strategy(EmitOn([
            {"direction": "buy", "size": 1.0, "reason": "first"},
            {"direction": "buy", "size": 1.0},
            {"direction": "buy", "size": 1.0, "reason": "third"},
        ]), tmp, "multi")
        dec = decisions(d)[0]
        check("multi-signal reasons are dense and index-aligned",
              dec["signals"] == [
                  {"signal_index": 0, "reason": "first"},
                  {"signal_index": 1, "reason": None},
                  {"signal_index": 2, "reason": "third"},
              ], dec["signals"])
        check("signal_count still matches the emitted signal list",
              dec["signal_count"] == 3)

        # 7/8. byte limit
        ok_reason = "a" * MAX_BYTES
        d = run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": ok_reason}]),
                         tmp, "limit_ok")
        check("exactly 1024 ASCII bytes is accepted",
              decisions(d)[0]["signals"][0]["reason"] == ok_reason)

        big = "a" * (MAX_BYTES + 1)
        try:
            run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": big}]),
                         tmp, "limit_bad")
            code, details = None, {}
        except Exception as exc:  # noqa: BLE001 - coded error expected
            code, details = getattr(exc, "code", None), dict(getattr(exc, "details", {}) or {})
        check("1025 bytes fails with STRATEGY_REASON_TOO_LONG",
              code == "STRATEGY_REASON_TOO_LONG", code)
        check("the failure is actionable (signal_index/actual/max)",
              details.get("signal_index") == 0 and details.get("actual_bytes") == MAX_BYTES + 1
              and details.get("max_bytes") == MAX_BYTES, details)

        multi_ok = "€" * 341  # 1023 bytes, 341 characters
        check("multi-byte text under the byte budget is accepted",
              len(multi_ok.encode()) <= MAX_BYTES)
        d = run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": multi_ok}]),
                         tmp, "mb_ok")
        check("multi-byte reason round-trips", decisions(d)[0]["signals"][0]["reason"] == multi_ok)

        multi_bad = "€" * 342  # 1026 bytes, 342 characters — under in chars, over in bytes
        try:
            run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": multi_bad}]),
                         tmp, "mb_bad")
            mb_code = None
        except Exception as exc:  # noqa: BLE001
            mb_code = getattr(exc, "code", None)
        check("the limit counts UTF-8 bytes, not characters",
              mb_code == "STRATEGY_REASON_TOO_LONG", mb_code)

        # 12. rejected order keeps the decision reason
        d = run_strategy(EmitOn([{"direction": "buy", "size": 0.0,
                                  "reason": "sizing mistake, stated intent"}]),
                         tmp, "rejected")
        dec = decisions(d)[0]
        events = [json.loads(l) for l in raw_lines(d).decode().splitlines() if l.strip()]
        check("the order really was rejected",
              any(e["type"] == "order_rejected" for e in events))
        check("the rejected order's signal still carries its reason",
              dec["signals"][0]["reason"] == "sizing mistake, stated intent")
        check("reason is not duplicated onto order_rejected",
              all("signals" not in e for e in events if e["type"] == "order_rejected"))

        # signal -> order invariant, with mixed accepted/rejected/close signals
        d = run_strategy(MixedOutcomes(), tmp, "mixed")
        events = [json.loads(l) for l in raw_lines(d).decode().splitlines() if l.strip()]
        for bar_index, expected in ((0, 1), (1, 3)):
            dec = [e for e in events if e["type"] == "strategy_decision"
                   and e["bar_index"] == bar_index][0]
            created = [e for e in events if e["type"] == "order_created"
                       and e["created_bar"] == bar_index]
            check("bar %d: signal_count == order_created count" % bar_index,
                  dec["signal_count"] == len(created) == expected,
                  (dec["signal_count"], len(created)))
            seqs = [e["order_seq"] for e in created]
            check("bar %d: order_created follows signal order" % bar_index, seqs == sorted(seqs))
        check("the mixed callback exercised rejection and acceptance",
              any(e["type"] == "order_rejected" for e in events)
              and any(e["type"] == "order_filled" for e in events))

        # 10. historical run without `signals` still loads and inspects
        hist = os.path.join(tmp, "historical")
        os.makedirs(hist)
        lines = []
        for line in raw_lines(d).decode().splitlines():
            e = json.loads(line)
            e.pop("signals", None)          # simulate a pre-OBS-SCHEMA-01 artifact
            lines.append(json.dumps(e))
        with open(os.path.join(hist, "events.jsonl"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        shutil.copy(os.path.join(d, "run.json"), os.path.join(hist, "run.json"))
        shutil.copy(os.path.join(d, "metrics.json"), os.path.join(hist, "metrics.json"))
        hrun = observa.inspect_run(hist)
        hdec = hrun.bar(1)["strategy_decisions"][0]
        check("a historical decision loads without the field",
              "signals" not in hdec and hdec["signal_count"] == 3, sorted(hdec))
        check("the historical run still inspects fully",
              len(hrun.trades()) == len(observa.inspect_run(d).trades()))

        # 11. determinism
        a = run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": "stable"},
                                 {"direction": "buy", "size": 1.0, "reason": "é中文😀"}]),
                         tmp, "det_a")
        b = run_strategy(EmitOn([{"direction": "buy", "size": 1.0, "reason": "stable"},
                                 {"direction": "buy", "size": 1.0, "reason": "é中文😀"}]),
                         tmp, "det_b")
        check("repeated runs produce byte-identical reason bytes",
              hashlib.sha256(raw_lines(a)).hexdigest() == hashlib.sha256(raw_lines(b)).hexdigest())

        # SampleEma (the canonical baseline strategy) really does supply reasons
        canon = os.path.join(tmp, "canonical")
        observa.run(observa.samples.sample_strategy.SampleEma(), tb.FIXTURE,
                    config=observa.Config(dataset_source=tb.FIXTURE, **tb.CANONICAL), output=canon)
        cins = observa.inspect_run(canon)
        cdecs = cins.events(event_type="strategy_decision")
        with_reason = [e for e in cdecs if e.get("signals")]
        non_null = sum(1 for e in with_reason for s in e["signals"] if s["reason"])
        check("canonical baseline: 1500 decisions, 88 with reasons",
              len(cdecs) == 1500 and len(with_reason) == 88
              and non_null == 88, (len(cdecs), len(with_reason), non_null))
        check("SampleEma's own reason text is preserved",
              with_reason[0]["signals"][0]["reason"] == "fast EMA crossed above slow EMA",
              with_reason[0]["signals"][0]["reason"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    import observa.samples.sample_strategy  # noqa: F401
    sys.exit(main())
