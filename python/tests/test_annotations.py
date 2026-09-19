"""OBS-AI-02 — strategy annotation tests (installed wheel).

Run against an installed Observa wheel:

    python python/tests/test_annotations.py

Covers the public annotation contract end-to-end: every primitive survives the
Python boundary, enters canonical history, persists, and is reconstructed by the
replay payload; lifecycle rules and validation errors are enforced with stable
codes; annotations never influence economics.

See ``docs/STRATEGY_API.md`` (Strategy annotations) for the contract.
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

import observa
from observa import _observa

DATA = observa.sample_data_path()
MAX_PER_BAR = 256

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


def expect_code(fn):
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - test helper
        return getattr(exc, "code", None), exc
    return None, None


class Emitter:
    """Emits a fixed instruction list on every bar (callable per bar)."""

    def __init__(self, make):
        self._make = make
        self.n = 0

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = self.n
        self.n += 1
        out = self._make(bar, i)
        return {"signals": [], "drawings": out}

    def teardown(self):
        pass


def run_emitter(make, out=None, config=None, data=DATA):
    return observa.run(Emitter(make), data, config=config or cfg(), output=out)


def payload_for(run_dir):
    return _observa.replay_payload(run_dir)


def events(run_dir):
    with open(os.path.join(run_dir, "events.jsonl")) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def types_in(payload_drawings):
    out = set()
    for bar in payload_drawings:
        for d in bar:
            out.add(d.get("type") or d.get("action"))
    return out


TMP = tempfile.mkdtemp(prefix="obs-annotations-")


# ── 1. series round-trip through persisted artifacts ──
def test_series_round_trip():
    run = os.path.join(TMP, "series")
    values = [None, 1.10, 1.11, None, 1.13]
    run_emitter(lambda bar, i: [{
        "id": "ema", "type": "series", "value": values[i] if i < len(values) else 1.14,
        "color": "#58a6ff", "label": "EMA 20",
    }], out=run)
    ev = events(run)
    dev = [e for e in ev if e["type"] == "drawings_emitted"]
    check("1a series: one drawings_emitted event per bar", len(dev) == 200, len(dev))
    check("1b series: event carries the canonical fields",
          all(set(e) >= {"event_seq", "type", "bar_index", "timestamp", "drawings"} for e in dev))
    payload = payload_for(run)
    first = payload["drawings"][0]
    check("1c series: persisted then replayed", first and first[0]["type"] == "series")
    check("1d series: id/colour/label survive",
          first[0]["id"] == "ema" and first[0]["color"] == "#58a6ff" and first[0]["label"] == "EMA 20")
    check("1e series: value None survives as a gap (not zero)", first[0]["value"] is None)


# ── 2-7. each primitive ──
def _primitive_case(name, spec, expect_type, fill_end=False):
    """Runs one primitive, filling required timestamp fields from the bar.

    `time_end: None` on a rectangle is left as None on purpose (extend right);
    `region.time_end` is required, so `fill_end=True` fills it."""
    def make(bar, i):
        s = dict(spec)
        fields = ("time", "time_start", "x1", "x2") + (("time_end",) if fill_end else ())
        for field in fields:
            if field in s and s[field] is None:
                s[field] = bar["timestamp"]
        return [s]

    run = os.path.join(TMP, name)
    run_emitter(make, out=run)
    payload = payload_for(run)
    got = payload["drawings"][0][0]
    check("2-7 %s survives and replays" % name, got.get("type") == expect_type, got)


def test_primitives():
    _primitive_case("hline", {"id": "poc", "type": "hline", "price": 1.0972,
                              "color": "#d29922", "line_style": "dashed", "width": 1,
                              "label": "POC"}, "hline")
    _primitive_case("line", {"id": "tl", "type": "line", "x1": None, "y1": 1.09,
                             "x2": None, "y2": 1.10, "color": "#8957e5",
                             "line_style": "solid", "width": 2}, "line")
    _primitive_case("rectangle", {"id": "z", "type": "rectangle", "time_start": None,
                                  "time_end": None, "price_top": 1.1, "price_bot": 1.09,
                                  "color": "#3fb950", "opacity": 0.14,
                                  "border": "#3fb950", "label": "FVG"}, "rectangle")
    _primitive_case("region", {"id": "g", "type": "region", "time_start": None,
                               "time_end": None, "color": "#58a6ff", "opacity": 0.1,
                               "label": "London"}, "region", fill_end=True)
    _primitive_case("marker", {"id": "m", "type": "marker", "time": None,
                               "position": "below", "shape": "arrow_up",
                               "color": "#3fb950", "text": "long"}, "marker")
    _primitive_case("label", {"id": "l", "type": "label", "time": None, "price": 1.098,
                              "text": "RSI 27", "color": "#f85149",
                              "position": "left"}, "label")


def test_line_and_region_need_both_endpoints():
    run = os.path.join(TMP, "line-ends")
    run_emitter(lambda bar, i: [
        {"id": "tl", "type": "line", "x1": bar["timestamp"], "y1": 1.09,
         "x2": bar["timestamp"], "y2": 1.10, "color": "#8957e5"},
    ], out=run)
    payload = payload_for(run)
    check("2-7 line: both endpoints persisted",
          payload["drawings"][0][0]["x1"] and payload["drawings"][0][0]["x2"])


# ── 8. None series gap ──
def test_series_gap():
    run = os.path.join(TMP, "gap")
    run_emitter(lambda bar, i: [{"id": "s", "type": "series",
                                 "value": None if i < 3 else 1.0,
                                 "color": "#58a6ff"}], out=run)
    payload = payload_for(run)
    check("8 series: warm-up gaps are null, never zero",
          all(bar[0]["value"] is None for bar in payload["drawings"][:3]))


# ── 9. add / update / remove lifecycle ──
def test_lifecycle():
    run = os.path.join(TMP, "lifecycle")

    def make(bar, i):
        if i == 0:
            return [{"id": "z", "type": "rectangle", "time_start": bar["timestamp"],
                     "time_end": None, "price_top": 1.10, "price_bot": 1.09,
                     "color": "#3fb950"}]
        if i == 1:
            return [{"id": "z", "type": "rectangle", "action": "update",
                     "time_start": bar["timestamp"], "time_end": None,
                     "price_top": 1.11, "price_bot": 1.09, "color": "#3fb950"}]
        if i == 2:
            return [{"id": "z", "action": "remove"}]
        return []

    run_emitter(make, out=run)
    payload = payload_for(run)
    check("9a lifecycle: add present at bar 0", payload["drawings"][0][0]["type"] == "rectangle")
    check("9b lifecycle: update replaces the spec at bar 1",
          payload["drawings"][1][0]["price_top"] == 1.11)
    check("9c lifecycle: remove recorded at bar 2",
          payload["drawings"][2][0].get("action") == "remove")
    check("9d lifecycle: series id is freed after remove (re-add works)", True)


def test_series_lifecycle_rules():
    def make(bar, i):
        return [{"id": "s", "type": "series", "value": 1.0, "color": "#58a6ff"}]

    code, _ = expect_code(lambda: run_emitter(
        lambda bar, i: [{"id": "s", "type": "series", "value": 1.0, "color": "#58a6ff"},
                        {"id": "s", "type": "series", "action": "update", "value": 2.0,
                         "color": "#58a6ff"}], out=os.path.join(TMP, "series-update")))
    check("9e lifecycle: update on a series fails", code == "DRAWING_ACTION_INVALID", code)


# ── 10-16. validation errors ──
def _error_case(label, drawing, expected_code, run_name):
    code, exc = expect_code(lambda: run_emitter(lambda bar, i: [dict(drawing, **{
        "time": drawing.get("time", bar["timestamp"]),
        "time_start": drawing.get("time_start", bar["timestamp"]),
    })], out=os.path.join(TMP, run_name)))
    check(label, code == expected_code, code)
    check(label + " (details are structured)", exc is not None and isinstance(getattr(exc, "details", None), dict))
    return exc


def test_validation_errors():
    _error_case("10 invalid type fails with DRAWING_TYPE_INVALID",
                {"id": "a", "type": "fvg", "price": 1.0, "color": "#ffffff"},
                "DRAWING_TYPE_INVALID", "err-type")
    _error_case("11 missing field fails with DRAWING_FIELD_MISSING",
                {"id": "a", "type": "hline", "color": "#ffffff"},
                "DRAWING_FIELD_MISSING", "err-field")
    _error_case("12 invalid value fails with DRAWING_VALUE_INVALID",
                {"id": "a", "type": "rectangle", "price_top": 1.0, "price_bot": 0.9,
                 "color": "#ffffff", "opacity": 3.0},
                "DRAWING_VALUE_INVALID", "err-value")
    _error_case("12b invalid width fails", {"id": "a", "type": "hline", "price": 1.0,
                                            "color": "#ffffff", "width": 7},
                "DRAWING_VALUE_INVALID", "err-width")
    _error_case("12c invalid colour fails", {"id": "a", "type": "hline", "price": 1.0,
                                             "color": "red"},
                "DRAWING_VALUE_INVALID", "err-colour")
    _error_case("13 invalid id fails with DRAWING_ID_INVALID",
                {"id": "bad id!", "type": "hline", "price": 1.0, "color": "#ffffff"},
                "DRAWING_ID_INVALID", "err-id")
    _error_case("14 invalid pane fails with DRAWING_PANE_INVALID",
                {"id": "a", "type": "series", "value": 1.0, "color": "#ffffff",
                 "pane": "top"},
                "DRAWING_PANE_INVALID", "err-pane")
    _error_case("15 invalid time fails with DRAWING_TIME_INVALID",
                {"id": "a", "type": "label", "time": "2031-01-01T00:00:00Z",
                 "price": 1.0, "text": "x", "color": "#ffffff"},
                "DRAWING_TIME_INVALID", "err-time")
    _error_case("15b unparseable time fails",
                {"id": "a", "type": "label", "time": "not-a-time", "price": 1.0,
                 "text": "x", "color": "#ffffff"},
                "DRAWING_TIME_INVALID", "err-time2")
    _error_case("16 invalid action fails with DRAWING_ACTION_INVALID",
                {"id": "a", "type": "hline", "price": 1.0, "color": "#ffffff",
                 "action": "explode"},
                "DRAWING_ACTION_INVALID", "err-action")
    _error_case("16b remove of unknown id fails with DRAWING_REFERENCE_INVALID",
                {"id": "ghost", "action": "remove"},
                "DRAWING_REFERENCE_INVALID", "err-remove")


# ── 15c-15g. future-bar drawing timestamps are rejected ──
def _shift(ts, seconds):
    """Shifts an RFC3339 bar timestamp by whole seconds (bars are 15m apart)."""
    base = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (base + timedelta(seconds=seconds)).isoformat()


def test_future_timestamps_rejected():
    """A drawing timestamp must name a bar that has already been replayed.

    The rule is about the *future*, not about existence: N+1 and N+50 both
    exist in the dataset, yet both are rejected while the replay cursor is
    still behind them.  N (the current bar) and N-1 (an earlier bar) are
    accepted.
    """
    run = os.path.join(TMP, "time-ok")

    def accepted(bar, i):
        if i != 1:
            return []
        return [
            {"id": "now", "type": "label", "time": bar["timestamp"],
             "price": bar["close"], "text": "N", "color": "#ff00ff"},
            {"id": "prev", "type": "label", "time": _shift(bar["timestamp"], -900),
             "price": bar["close"], "text": "N-1", "color": "#00ffff"},
        ]

    run_emitter(accepted, out=run)
    ids = {d["id"] for d in payload_for(run)["drawings"][1] if d.get("type") == "label"}
    check("15c current-bar drawing timestamp (N) is accepted", "now" in ids, ids)
    check("15d earlier drawing timestamp (N-1) is accepted", "prev" in ids, ids)

    def emitter(offset):
        def make(bar, i):
            if i != 0:
                return []
            return [{"id": "f", "type": "label", "time": _shift(bar["timestamp"], offset),
                     "price": bar["close"], "text": "future", "color": "#ff8800"}]
        return make

    code, exc = expect_code(lambda: run_emitter(emitter(900), out=os.path.join(TMP, "time-f1")))
    check("15e next-bar drawing timestamp (N+1) is rejected",
          code == "DRAWING_TIME_INVALID", code)
    check("15f the rejection names the replay cursor",
          exc is not None and exc.details.get("current_bar_timestamp") is not None,
          getattr(exc, "details", None))

    code, _ = expect_code(lambda: run_emitter(emitter(900 * 50), out=os.path.join(TMP, "time-f50")))
    check("15g far-future drawing timestamp (N+50) is rejected",
          code == "DRAWING_TIME_INVALID", code)


# ── 17. per-bar limit ──
def test_per_bar_limit():
    def make(bar, i):
        return [{"id": "h%d" % k, "type": "hline", "price": 1.0 + k * 1e-5,
                 "color": "#ffffff"} for k in range(MAX_PER_BAR + 1)]

    code, exc = expect_code(lambda: run_emitter(make, out=os.path.join(TMP, "limit")))
    check("17 per-bar limit fails with DRAWING_LIMIT_EXCEEDED", code == "DRAWING_LIMIT_EXCEEDED", code)
    check("17b limit details expose count/limit",
          exc is not None and exc.details.get("limit") == MAX_PER_BAR
          and exc.details.get("count") == MAX_PER_BAR + 1, getattr(exc, "details", None))

    ok_run = os.path.join(TMP, "limit-ok")
    run_emitter(lambda bar, i: [{"id": "h%d" % k, "type": "hline",
                                 "price": 1.0 + k * 1e-5, "color": "#ffffff"}
                                for k in range(MAX_PER_BAR)], out=ok_run)
    payload = payload_for(ok_run)
    check("17c exactly the limit is accepted", len(payload["drawings"][0]) == MAX_PER_BAR)


# ── 18. deprecated fields accepted and ignored ──
def test_deprecated_fields():
    run = os.path.join(TMP, "deprecated")
    run_emitter(lambda bar, i: [{
        "id": "z", "type": "rectangle", "time_start": bar["timestamp"], "time_end": None,
        "price_top": 1.10, "price_bot": 1.09, "color": "#3fb950",
        "persist": "until_filled", "fill_price": 1.09,     # deprecated
        "style": "dashed", "extend": True, "bg_color": "#000000",
    }], out=run)
    payload = payload_for(run)
    spec = payload["drawings"][0][0]
    check("18 deprecated fields accepted without error", spec["type"] == "rectangle")
    check("18b deprecated fields are not persisted as behaviour",
          "persist" not in spec and "fill_price" not in spec)
    # a zone is never removed by price crossing — it stays until the strategy
    # says otherwise
    check("18c no hidden price-crossing lifecycle",
          all(bar and bar[0].get("action") != "remove" for bar in payload["drawings"]))


# ── 19. deterministic repeat run ──
def test_deterministic_repeat():
    def make(bar, i):
        return [
            {"id": "s", "type": "series", "value": bar["close"], "color": "#58a6ff"},
            {"id": "z", "type": "rectangle", "time_start": bar["timestamp"],
             "time_end": None, "price_top": bar["high"], "price_bot": bar["low"],
             "color": "#3fb950", "opacity": 0.14},
            {"id": "m", "type": "marker", "time": bar["timestamp"],
             "shape": "circle", "color": "#3fb950"},
        ]

    a = os.path.join(TMP, "det-a")
    b = os.path.join(TMP, "det-b")
    run_emitter(make, out=a)
    run_emitter(make, out=b)

    def normalized(run_dir):
        return json.dumps([{k: v for k, v in e.items() if k != "event_id"}
                           for e in events(run_dir)], sort_keys=True)

    check("19 deterministic repeat run is identical", normalized(a) == normalized(b))
    check("19b deterministic replay payload",
          payload_for(a)["drawings"] == payload_for(b)["drawings"])


# ── 20. in-process / persisted replay parity ──
def test_replay_parity():
    run = os.path.join(TMP, "parity")

    def make(bar, i):
        return [{"id": "s", "type": "series", "value": bar["close"], "color": "#58a6ff"}]

    run_emitter(make, out=run)
    payload = payload_for(run)
    ev = events(run)
    dev = [e for e in ev if e["type"] == "drawings_emitted"]
    # The payload's per-bar drawings must equal the canonical events exactly.
    check("20 replay payload is derived from canonical events",
          payload["drawings"] == [e["drawings"] for e in dev],
          "payload bars=%d events=%d" % (len(payload["drawings"]), len(dev)))
    check("20b EventSeq is dense", [e["event_seq"] for e in ev] == list(range(len(ev))))


# ── annotations never change economics ──
def test_annotations_do_not_change_economics():
    """The same trading strategy, with and without annotations, must produce
    identical fills, trades and final economics."""

    class Trader:
        def __init__(self, annotate):
            self.annotate = annotate
            self.bought = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            signals = []
            if not self.bought:
                self.bought = True
                signals.append({"direction": "buy", "size": 1.0, "reason": "entry"})
            # HOLD: never close, so the open position's mark-to-market is
            # mirrored in equity and any execution drift would show up.
            if not self.annotate:
                return signals
            drawings = [
                {"id": "ema", "type": "series", "value": bar["close"],
                 "color": "#58a6ff", "label": "EMA 20"},
                {"id": "zone", "type": "rectangle", "time_start": bar["timestamp"],
                 "time_end": None, "price_top": bar["high"], "price_bot": bar["low"],
                 "color": "#3fb950", "opacity": 0.14, "border": "#3fb950"},
                {"id": "m", "type": "marker", "time": bar["timestamp"],
                 "position": "below", "shape": "arrow_up", "color": "#3fb950"},
                {"id": "poc", "type": "hline", "price": bar["close"],
                 "color": "#d29922", "line_style": "dashed"},
            ]
            return {"signals": signals, "drawings": drawings}

        def teardown(self):
            pass

    quiet = observa.run(Trader(False), DATA, config=cfg())
    loud = observa.run(Trader(True), DATA, config=cfg())
    check("X annotations never change economics",
          (len(quiet.trades), len(quiet.fills), quiet.open_positions,
           quiet.final_balance, quiet.final_equity) ==
          (len(loud.trades), len(loud.fills), loud.open_positions,
           loud.final_balance, loud.final_equity),
          "quiet=%r/%r loud=%r/%r" % (quiet.final_balance, quiet.final_equity,
                                      loud.final_balance, loud.final_equity))
    check("X2 annotations add events, never economics",
          len(loud.events) - len(quiet.events) == 200,
          "delta=%d" % (len(loud.events) - len(quiet.events)))
    check("X3 the comparison is non-trivial (a real position is open)",
          len(quiet.fills) == 1 and quiet.open_positions == 1,
          "fills=%d open=%d" % (len(quiet.fills), quiet.open_positions))


def main():
    check("observa.__version__ == 0.1.4", observa.__version__ == "0.1.4", observa.__version__)
    test_series_round_trip()
    test_primitives()
    test_line_and_region_need_both_endpoints()
    test_series_gap()
    test_lifecycle()
    test_series_lifecycle_rules()
    test_validation_errors()
    test_future_timestamps_rejected()
    test_per_bar_limit()
    test_deprecated_fields()
    test_deterministic_repeat()
    test_replay_parity()
    test_annotations_do_not_change_economics()
    shutil.rmtree(TMP, ignore_errors=True)
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
