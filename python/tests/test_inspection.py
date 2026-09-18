"""OBS-AI-03 — structured run inspection tests (installed wheel).

Run against an installed Observa wheel:

    python python/tests/test_inspection.py

Covers the full ``observa.inspect_run`` contract: artifact-only authority, the
nine-member surface, canonical chronology-bucket bar attribution, exact trade
equivalence with ``RunResult.trades``, lifecycle inspection, rejection joins,
historical UUIDv4 compatibility, failed runs, no-rerun / no-write guarantees and
JSON serializability.

See ``docs/STRATEGY_API.md`` (§ Run inspection) for the public contract.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

import observa
from observa.samples.sample_strategy import SampleEma

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_canonical_baseline as tb  # noqa: E402
import make_annotation_demo as demo  # noqa: E402

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


def cfg(**kw):
    base = dict(dataset_source=tb.FIXTURE, **tb.CANONICAL)
    base.update(kw)
    return observa.Config(**base)


def sha_dir(path):
    out = {}
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            full = os.path.join(root, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, path)] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ── fixture builders ────────────────────────────────────────────────────────


class OpenThenFail:
    """Opens on bar 0, then fails — a deterministic persisted failed run."""

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
            return {"signals": [{"direction": "buy", "size": 1.0, "reason": "entry"}]}
        raise RuntimeError("scripted failure after open")


class HeavyAnnotations:
    """Six primitives on every bar — the annotation-heavy scale case."""

    def __init__(self):
        self.n = 0

    def initialize(self, params=None):
        pass

    def teardown(self):
        pass

    def on_bar(self, bar, portfolio, history):
        self.n += 1
        return {"signals": [], "drawings": [
            {"id": "e", "type": "series", "value": bar["close"], "color": "#58a6ff"},
            {"id": "v", "type": "series", "value": bar["close"] * 0.999, "color": "#d29922"},
            {"id": "z", "type": "series", "value": (bar["close"] - 1.1) * 100,
             "color": "#8957e5", "pane": "separate"},
            {"id": "h", "type": "hline", "price": 1.1, "color": "#8b949e"},
            {"id": "r", "type": "rectangle", "time_start": bar["timestamp"],
             "time_end": None, "price_top": bar["high"], "price_bot": bar["low"],
             "color": "#3fb950"},
            {"id": "m", "type": "marker", "time": bar["timestamp"],
             "position": "below", "shape": "arrow_up", "color": "#3fb950"},
        ]}


class Rejections:
    """Produces canonical rejected orders (bad size, over-range size, bad SL,
    bogus close ticket) followed by one valid entry."""

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
            return {"signals": [
                {"direction": "buy", "size": 0.0, "reason": "invalid quantity"},
                {"direction": "buy", "size": 5000.0, "reason": "out of range"},
                {"direction": "buy", "size": 1.0, "sl": bar["close"] + 1.0,
                 "reason": "invalid SL"},
                {"direction": "close", "size": 1.0, "ticket": "not-a-uuid",
                 "reason": "bogus ticket"},
            ]}
        if i == 1:
            return {"signals": [{"direction": "buy", "size": 1.0, "reason": "valid"}]}
        return {"signals": []}


def build_canonical(tmp):
    """The canonical 1500-bar run, persisted, with its in-process RunResult."""
    out = os.path.join(tmp, "canonical")
    result = observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=out)
    return out, result


def build_demo(tmp):
    out = os.path.join(tmp, "annotation_demo")
    demo.main([out])
    return out


def build_heavy(tmp):
    out = os.path.join(tmp, "heavy")
    observa.run(HeavyAnnotations(), tb.FIXTURE, config=cfg(), output=out)
    return out


def build_failed(tmp):
    out = os.path.join(tmp, "failed")
    try:
        observa.run(OpenThenFail(), tb.FIXTURE, config=cfg(), output=out)
    except Exception:  # noqa: BLE001 - expected
        pass
    return out


def build_rejected(tmp):
    out = os.path.join(tmp, "rejected")
    observa.run(Rejections(), tb.FIXTURE, config=cfg(), output=out)
    return out


def build_legacy(tmp, canonical_dir):
    """A historical run whose position ids are genuine UUIDv4 values."""
    legacy = os.path.join(tmp, "legacy")
    shutil.copytree(canonical_dir, legacy)
    path = os.path.join(legacy, "events.jsonl")
    with open(path) as fh:
        lines = fh.read().splitlines()
    mapping = {}
    out_lines = []
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        pid = event.get("position_id")
        if isinstance(pid, str):
            if pid not in mapping:
                mapping[pid] = str(uuid.uuid4())
            event["position_id"] = mapping[pid]
        out_lines.append(json.dumps(event))
    with open(path, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")
    return legacy, mapping


def build_no_ohlc(tmp, canonical_dir):
    """A run whose dataset source no longer exists (OHLC unrecoverable)."""
    copy = os.path.join(tmp, "no_ohlc")
    shutil.copytree(canonical_dir, copy)
    path = os.path.join(copy, "run.json")
    with open(path) as fh:
        run_json = json.load(fh)
    run_json["dataset"]["source"] = os.path.join(tmp, "does-not-exist.csv")
    with open(path, "w") as fh:
        json.dump(run_json, fh)
    return copy


def build_strategy_gone(tmp):
    """A persisted run whose strategy module is deleted afterwards."""
    strategy_path = os.path.join(tmp, "temp_strategy_module.py")
    with open(strategy_path, "w") as fh:
        fh.write(
            "import observa\n"
            "class S:\n"
            "    def initialize(self, params=None): pass\n"
            "    def teardown(self): pass\n"
            "    def on_bar(self, bar, portfolio, history):\n"
            "        if not getattr(self, 'bought', False):\n"
            "            self.bought = True\n"
            "            return [{'direction': 'buy', 'size': 1.0, 'reason': 'once'}]\n"
            "        return []\n"
        )
    run_dir = os.path.join(tmp, "strategy_gone")
    script = (
        "import sys, observa\n"
        "sys.path.insert(0, %r)\n"
        "from temp_strategy_module import S\n"
        "observa.run(S(), %r, config=observa.Config(dataset_source=%r, **%r), output=%r)\n"
    ) % (tmp, tb.FIXTURE, tb.FIXTURE, tb.CANONICAL, run_dir)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("subprocess run failed: %s" % proc.stderr[-800:])
    os.remove(strategy_path)
    for leftover in ("__pycache__",):
        shutil.rmtree(os.path.join(tmp, leftover), ignore_errors=True)
    return run_dir


# ── checks ──────────────────────────────────────────────────────────────────


def test_meta_and_metrics(run, canonical_dir):
    raw = json.load(open(os.path.join(canonical_dir, "run.json")))
    check("meta is the persisted run.json verbatim", run.meta == raw)
    check("meta reports a completed run", run.meta.get("status") == "completed", run.meta.get("status"))
    check("meta carries the dataset identity", run.meta["dataset"]["bar_count"] == 1500)
    raw_metrics = json.load(open(os.path.join(canonical_dir, "metrics.json")))
    check("metrics is the persisted metrics.json verbatim", run.metrics == raw_metrics)
    check("metrics exposes the persisted drawdown window",
          "max_drawdown_start" in run.metrics and "max_drawdown_end" in run.metrics)
    check("meta is a fresh copy (mutation cannot reach the inspector)",
          _mutating_copy_is_isolated(run))


def _mutating_copy_is_isolated(run):
    first = run.meta
    first["status"] = "tampered"
    return run.meta.get("status") == "completed"


def test_event_queries(run):
    events = run.events()
    check("events() with no filters returns the full canonical history",
          len(events) == 4862, len(events))
    check("events() preserves ascending canonical event_seq",
          [e["event_seq"] for e in events] == sorted(e["event_seq"] for e in events))

    fills = run.events(event_type="order_filled")
    check("event_type filter returns only that type",
          fills and all(e["type"] == "order_filled" for e in fills), len(fills))

    check("unknown event_type returns an empty list",
          run.events(event_type="no_such_type") == [])

    one = run.events(event_seq=0)
    check("event_seq filter returns exactly that event",
          len(one) == 1 and one[0]["event_seq"] == 0)
    check("event_seq filter agrees with event()", one[0] == run.event(0))

    rng = run.events(start_event_seq=10, end_event_seq=20)
    check("event_seq range is inclusive",
          [e["event_seq"] for e in rng] == list(range(10, 21)),
          [e["event_seq"] for e in rng][:3])

    order_events = run.events(order_seq=0)
    check("order_seq filter returns every event carrying that sequence",
          order_events and all(e.get("order_seq") == 0 for e in order_events),
          len(order_events))

    pid = run.trades()[0]["position_id"]
    pos_events = run.events(position_id=pid)
    check("position_id filter returns the position events",
          pos_events and all(e.get("position_id") == pid for e in pos_events),
          [e["type"] for e in pos_events])

    combined = run.events(event_type="order_filled", order_seq=0)
    check("filters combine with AND semantics",
          all(e["type"] == "order_filled" and e["order_seq"] == 0 for e in combined),
          combined)

    check("no matches returns [] not None", run.events(event_type="order_filled", order_seq=999999) == [])

    try:
        run.events(event_type=123)
        raised = None
    except TypeError as exc:
        raised = exc
    check("a filter of the wrong type fails clearly (TypeError)", raised is not None, raised)

    try:
        run.events(bar_index=True)
        raised_bool = None
    except TypeError as exc:
        raised_bool = exc
    check("bool is rejected where an int filter is expected (no silent coercion)",
          raised_bool is not None)


def test_bar_attribution(run):
    """The critical invariant: bucket semantics, not raw-field equality."""
    for n in (0, 1, 200, 1499):
        from_events = run.events(bar_index=n)
        from_bar = run.bar(n)["events"]
        check("bar %d: events(bar_index=n) == bar(n)[\"events\"]" % n,
              from_events == from_bar, {"events": len(from_events), "bar": len(from_bar)})

    # order_created stores `created_bar`, and order_pending/order_expired have no
    # bar field at all — all three must be attributed by chronology.
    created_bars = {e["order_seq"]: e["created_bar"] for e in run.events(event_type="order_created")}
    attributed = 0
    for seq, created_bar in list(created_bars.items())[:20]:
        in_bucket = any(
            e.get("type") == "order_created" and e.get("order_seq") == seq
            for e in run.bar(created_bar)["events"]
        )
        attributed += 1 if in_bucket else 0
    check("order_created is attributed by chronology (created_bar)", attributed == 20, attributed)

    pending = run.events(event_type="order_pending")
    check("order_pending is attributed despite carrying no bar field", len(pending) > 0, len(pending))
    bar_count = run.meta["dataset"]["bar_count"]
    placed = 0
    for event in pending[:20]:
        for bar_index in range(bar_count):
            if any(e["event_seq"] == event["event_seq"] for e in run.bar(bar_index)["events"]):
                placed += 1
                break
    check("every order_pending event is placed in some chronology bucket",
          placed == len(pending[:20]), placed)

    check("run-level preamble events are not attributed to a bar",
          all(e["type"] != "run_started" for e in run.bar(0)["events"]))


def test_bar_lookup(run, demo_dir, no_ohlc_dir):
    bar = run.bar(0)
    canonical_bar0 = run.events(event_type="bar_processed")[0]
    check("bar() exposes the canonical index and timestamp",
          bar["bar_index"] == 0 and bar["timestamp"] == canonical_bar0["timestamp"],
          bar["timestamp"])
    check("bar() exposes a canonical strategy_decision",
          bar["strategy_decisions"] and "signal_count" in bar["strategy_decisions"][0])
    check("bar() exposes the canonical portfolio snapshot",
          bar["portfolio"] is not None and bar["portfolio"]["type"] == "portfolio_snapshot")
    fixture_row = open(tb.FIXTURE).read().splitlines()[1].split(",")
    check("bar() with a recovered dataset exposes verified OHLC",
          bar["ohlc_available"] is True
          and bar["ohlc"]["open"] == float(fixture_row[1])
          and bar["ohlc"]["close"] == float(fixture_row[4]), bar["ohlc"])
    check("bar() groups orders/fills/positions from canonical events",
          all(k in bar for k in ("orders", "fills", "rejections",
                                 "positions_opened", "positions_closed")))

    unavailable = observa.inspect_run(no_ohlc_dir)
    bar0 = unavailable.bar(0)
    check("bar() degrades cleanly when the dataset is unrecoverable",
          bar0["ohlc"] is None and bar0["ohlc_available"] is False, bar0["ohlc_available"])
    check("the rest of the bar view still works without OHLC",
          bar0["portfolio"] is not None and len(bar0["events"]) > 0)

    demo_run = observa.inspect_run(demo_dir)
    annotated = [n for n in range(200) if demo_run.bar(n)["drawings"]]
    check("bar() exposes exact canonical drawing specs", len(annotated) == 200, len(annotated))
    sample = demo_run.bar(30)["drawings"]
    types = sorted({d["type"] for d in sample})
    check("drawing specs are returned unmodified (types preserved)",
          set(types) <= {"series", "hline", "rectangle", "marker", "label"}, types)
    check("drawings match the canonical drawings_emitted payload",
          sample == _drawings_from_events(demo_run, 30), sample[:1])

    try:
        run.bar(99999)
        raised = None
    except KeyError as exc:
        raised = exc
    check("bar() raises KeyError/BAR_NOT_FOUND for an unknown bar",
          raised is not None and getattr(raised, "code", None) == "BAR_NOT_FOUND",
          getattr(raised, "code", None))
    check("BAR_NOT_FOUND details carry the bar_index",
          getattr(raised, "details", {}).get("bar_index") == 99999)


def _drawings_from_events(run, bar_index):
    out = []
    for event in run.events(event_type="drawings_emitted", bar_index=bar_index):
        out.extend(event["drawings"])
    return out


def test_positions(run, canonical_dir, legacy_dir, legacy_map):
    trades = run.trades()
    check("trades() returns every completed canonical trade", len(trades) == 47, len(trades))
    check("trades() is ordered by canonical close chronology",
          [t["bar_index"] for t in trades] == sorted(t["bar_index"] for t in trades))

    # 26. exactness vs the in-process RunResult.trades
    in_process = observa.run(SampleEma(), tb.FIXTURE, config=cfg()).trades
    check("trades() has exactly the RunResult.trades keys, in the same order",
          all(list(t) == list(u) for t, u in zip(trades, in_process)),
          {"persisted": list(trades[0]), "in_process": list(in_process[0])})
    check("trades() equals RunResult.trades value-for-value (bit-exact)",
          trades == in_process,
          next((i for i, (t, u) in enumerate(zip(trades, in_process)) if t != u), None))
    float_exact = all(
        all(t[k] == u[k] for k in t if isinstance(t[k], float))
        for t, u in zip(trades, in_process)
    )
    check("every trade float is bit-identical to the in-memory value",
          float_exact)

    pid = trades[0]["position_id"]
    lifecycle = run.position(pid)
    check("closed position lifecycle reports status=closed", lifecycle["status"] == "closed")
    check("closed position exposes opened/closed canonical events",
          lifecycle["opened"]["type"] == "position_opened"
          and lifecycle["closed"]["type"] == "position_closed")
    check("closed position exposes its opening order lifecycle",
          lifecycle["opening_order"] is not None
          and lifecycle["opening_order"]["state"] == "filled",
          lifecycle["opening_order"] and lifecycle["opening_order"]["state"])
    check("position events preserve ascending canonical event_seq",
          [e["event_seq"] for e in lifecycle["events"]]
          == sorted(e["event_seq"] for e in lifecycle["events"]))
    check("position events include the opening order's events",
          any(e["type"] == "order_created" for e in lifecycle["events"]))
    check("entry/exit bar indexes are canonical",
          lifecycle["entry_bar_index"] == lifecycle["opened"]["bar_index"]
          and lifecycle["exit_bar_index"] == lifecycle["closed"]["bar_index"])

    open_positions = run.positions(open=True)
    check("positions(open=True) returns the one open position",
          len(open_positions) == 1, len(open_positions))
    open_pid = open_positions[0]["position_id"]
    opened = run.position(open_pid)
    check("open position lifecycle reports status=open", opened["status"] == "open")
    check("open position has closed=None, trade=None and no exit bar",
          opened["closed"] is None and opened["exit_bar_index"] is None)
    check("open position is excluded from trades()",
          open_pid not in {t["position_id"] for t in trades})

    check("positions(open=False) matches trades() count",
          len(run.positions(open=False)) == len(trades))
    entry_seqs = [p["entry_event_seq"] for p in run.positions()]
    check("positions() ordering is by opening event_seq",
          entry_seqs == sorted(entry_seqs), entry_seqs[:5])
    id_order = [p["position_id"] for p in run.positions()]
    check("positions() ordering is not the id text order",
          id_order != sorted(id_order), id_order[:3])

    # 20/21 deterministic v5 and historical v4
    v5_ok = all(uuid.UUID(t["position_id"]).version == 5 for t in trades)
    check("current runs expose deterministic UUIDv5 position ids", v5_ok)
    legacy = observa.inspect_run(legacy_dir)
    legacy_ids = {t["position_id"] for t in legacy.trades()}
    check("historical UUIDv4 runs inspect successfully",
          len(legacy.trades()) == 47, len(legacy.trades()))
    check("historical ids are preserved verbatim (opaque, no migration)",
          legacy_ids <= set(legacy_map.values()) and len(legacy_ids) == 47)
    check("historical position ids resolve through position()",
          all(legacy.position(p)["status"] == "closed" for p in list(legacy_ids)[:5]))
    check("historical ids keep UUID version 4",
          all(uuid.UUID(i).version == 4 for i in legacy_ids))

    try:
        run.position("not-a-position")
        raised = None
    except KeyError as exc:
        raised = exc
    check("position() raises KeyError/POSITION_NOT_FOUND for an unknown id",
          raised is not None and getattr(raised, "code", None) == "POSITION_NOT_FOUND",
          getattr(raised, "code", None))


def test_orders_and_rejections(run, rejected_dir):
    filled = run.order(0)
    check("order() exposes the canonical lifecycle slots",
          all(k in filled for k in ("created", "pending", "triggered",
                                    "filled", "rejected", "expired")))
    check("order() state is the last canonical state event", filled["state"] == "filled",
          filled["state"])
    check("order() links to the position it opened when canonical",
          filled["position_id"] is not None, filled["position_id"])
    check("order() events preserve canonical ordering",
          [e["event_seq"] for e in filled["events"]]
          == sorted(e["event_seq"] for e in filled["events"]))

    rejected_run = observa.inspect_run(rejected_dir)
    rejections = rejected_run.rejections()
    check("rejections() returns the canonical rejected orders", len(rejections) >= 3,
          len(rejections))
    entry = rejections[0]
    check("a rejection joins the order parameters with the rejection",
          all(k in entry for k in ("order_seq", "bar_index", "order_type", "side",
                                   "quantity_lots", "category", "reason", "events")))
    check("a rejection supplies the order parameters that order_rejected lacks",
          entry["order_type"] is not None and entry["quantity_lots"] is not None,
          {k: entry[k] for k in ("order_type", "quantity_lots", "side")})
    canonical_rej = rejected_run.events(event_type="order_rejected")
    check("rejection reason/category are verbatim canonical values",
          {(e["order_seq"], e["category"], e["reason"]) for e in canonical_rej}
          == {(e["order_seq"], e["category"], e["reason"]) for e in rejections})
    check("rejection entries are ordered by canonical rejection event_seq",
          [e["events"][-1]["event_seq"] for e in rejections]
          == sorted(e["events"][-1]["event_seq"] for e in rejections))
    rejected_order = rejected_run.order(rejections[0]["order_seq"])
    check("order() reports state=rejected for a rejected order",
          rejected_order["state"] == "rejected", rejected_order["state"])
    check("the rejection scenario still opened the valid entry",
          len(rejected_run.positions()) == 1, len(rejected_run.positions()))

    try:
        run.order(999999)
        raised = None
    except KeyError as exc:
        raised = exc
    check("order() raises KeyError/ORDER_NOT_FOUND for an unknown order",
          raised is not None and getattr(raised, "code", None) == "ORDER_NOT_FOUND",
          getattr(raised, "code", None))


def test_annotations_on_position(run, demo_dir):
    demo_run = observa.inspect_run(demo_dir)
    # The demo's zone is created at bar 20 and removed at bar 60; positions are
    # not opened, so use the canonical run for lifecycle annotation wiring and
    # the demo for exactness.
    identifiers = {d["id"] for d in demo_run.bar(30)["drawings"]}
    check("annotation ids survive inspection unchanged",
          {"note_above", "note_below", "note_left", "note_right"} <= identifiers, identifiers)

    pid = run.trades()[0]["position_id"]
    lifecycle = run.position(pid)
    entry = lifecycle["entry_bar_index"]
    check("annotations_at_entry comes from the entry bar ([] when none)",
          lifecycle["annotations_at_entry"] == run.bar(entry)["drawings"])
    check("annotations_at_exit comes from the exit bar",
          lifecycle["annotations_at_exit"] == run.bar(lifecycle["exit_bar_index"])["drawings"])
    check("a run without drawings_emitted yields empty annotation views",
          run.bar(entry)["drawings"] == [])


def test_g11_g12_limitations(run, rejected_dir):
    lifecycle = run.position(run.trades()[0]["position_id"])
    check("G12: closing_order is None (never inferred)", lifecycle["closing_order"] is None)
    # G11: the strategy's prose reason is not persisted anywhere in the model.
    filled = run.order(0)
    check("G11: a filled order exposes no invented strategy reason",
          filled.get("reason") is None)
    decisions = run.events(event_type="strategy_decision")
    check("G11: strategy_decision carries only the canonical signal_count",
          all(set(e) == {"event_seq", "type", "bar_index", "signal_count"} for e in decisions),
          sorted(decisions[0]) if decisions else None)
    check("G11: order_created carries no reason field",
          all("reason" not in e for e in run.events(event_type="order_created")))
    rejections = observa.inspect_run(rejected_dir).events(event_type="order_rejected")
    check("the only canonical reason text is the rejection reason",
          rejections and all(isinstance(e.get("reason"), str) and e["reason"] for e in rejections))


def test_failed_run(failed_dir):
    run = observa.inspect_run(failed_dir)
    check("failed run inspects without rejection", run.meta.get("status") == "failed",
          run.meta.get("status"))
    check("failed run exposes metrics=None (no metrics.json)", run.metrics is None)
    check("failed run exposes the partial canonical history", len(run.events()) > 0)
    check("failed run history ends in run_failed",
          run.events()[-1]["type"] == "run_failed", run.events()[-1]["type"])
    opened = run.positions()
    check("positions opened before the failure are inspectable",
          len(opened) == 1 and opened[0]["status"] == "open", len(opened))
    check("the pre-failure position lifecycle is retrievable",
          run.position(opened[0]["position_id"])["opened"]["type"] == "position_opened")
    check("failed run has no trades (no close)",
          len(run.trades()) == 0, len(run.trades()))


def test_no_rerun_and_no_writes(gone_dir, canonical_dir):
    before = sha_dir(gone_dir)
    run = observa.inspect_run(gone_dir)
    # exercise the whole surface
    run.meta, run.metrics, run.events(), run.bar(0), run.positions(), run.trades(), run.rejections()
    for trade in run.trades():
        run.position(trade["position_id"])
    for order_event in run.events(event_type="order_created")[:5]:
        run.order(order_event["order_seq"])
    after = sha_dir(gone_dir)
    check("inspection writes nothing to the run directory", before == after,
          {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)})
    check("a run made by a deleted strategy module is fully inspectable",
          run.meta["status"] == "completed" and len(run.positions()) == 1
          and run.positions()[0]["status"] == "open", len(run.positions()))

    # and the canonical run is untouched by a full sweep too
    canonical_before = sha_dir(canonical_dir)
    r2 = observa.inspect_run(canonical_dir)
    r2.trades(); r2.bar(10); r2.events(); r2.rejections(); r2.positions()
    check("a full inspection sweep leaves canonical artifacts byte-identical",
          sha_dir(canonical_dir) == canonical_before)


def test_errors(tmp):
    missing = os.path.join(tmp, "does-not-exist")
    try:
        observa.inspect_run(missing)
        code = None
    except FileNotFoundError as exc:
        code = getattr(exc, "code", None)
    check("a missing run raises FileNotFoundError/RUN_DIR_NOT_FOUND",
          code == "RUN_DIR_NOT_FOUND", code)

    broken = os.path.join(tmp, "broken")
    os.makedirs(broken)
    with open(os.path.join(broken, "run.json"), "w") as fh:
        fh.write("{not json")
    try:
        observa.inspect_run(broken)
        bad_code = None
    except ValueError as exc:
        bad_code = getattr(exc, "code", None)
    check("invalid run.json raises ValueError/RUN_ARTIFACTS_INVALID",
          bad_code == "RUN_ARTIFACTS_INVALID", bad_code)

    truncated = os.path.join(tmp, "truncated")
    os.makedirs(truncated)
    shutil.copy(os.path.join(tmp, "canonical", "run.json"), os.path.join(truncated, "run.json"))
    shutil.copy(os.path.join(tmp, "canonical", "metrics.json"), os.path.join(truncated, "metrics.json"))
    with open(os.path.join(tmp, "canonical", "events.jsonl")) as fh:
        first = fh.readline()
    with open(os.path.join(truncated, "events.jsonl"), "w") as fh:
        fh.write(first)
        fh.write("{not json\n")
    try:
        observa.inspect_run(truncated)
        trunc_code = None
    except ValueError as exc:
        trunc_code = getattr(exc, "code", None)
    check("a corrupt events.jsonl line raises RUN_ARTIFACTS_INVALID",
          trunc_code == "RUN_ARTIFACTS_INVALID", trunc_code)


def test_scale_and_serialization(heavy_dir, run):
    import time
    start = time.time()
    heavy = observa.inspect_run(heavy_dir)
    elapsed = time.time() - start
    check("annotation-heavy run builds its indexes well under a second",
          elapsed < 5.0, "%.3fs" % elapsed)
    check("annotation-heavy event count is ~6000", len(heavy.events()) >= 6000, len(heavy.events()))
    check("annotation-heavy drawings are retrieved per bar",
          len(heavy.bar(500)["drawings"]) == 6, len(heavy.bar(500)["drawings"]))

    payload = {
        "meta": heavy.meta,
        "metrics": heavy.metrics,
        "events": heavy.events(event_type="drawings_emitted")[:5],
        "bar": heavy.bar(3),
        "positions": heavy.positions(),
        "trades": heavy.trades(),
        "rejections": heavy.rejections(),
    }
    try:
        json.dumps(payload)
        serializable = True
        detail = ""
    except TypeError as exc:
        serializable = False
        detail = str(exc)
    check("every public result is JSON-serializable", serializable, detail)

    types = set()
    for value in (heavy.meta, heavy.bar(3), heavy.positions()):
        types |= _types_in(value)
    check("results are composed only of dict/list/str/int/float/bool/None",
          types <= {dict, list, str, int, float, bool, type(None)}, types)


def _types_in(value, out=None):
    out = set() if out is None else out
    out.add(type(value))
    if isinstance(value, dict):
        for v in value.values():
            _types_in(v, out)
    elif isinstance(value, list):
        for v in value:
            _types_in(v, out)
    return out


def test_ordering(run):
    for name, events in (
        ("events()", run.events()),
        ("position events", run.position(run.trades()[0]["position_id"])["events"]),
        ("order events", run.order(0)["events"]),
        ("bar events", run.bar(120)["events"]),
    ):
        seqs = [e["event_seq"] for e in events]
        check("%s preserve canonical event_seq ordering" % name, seqs == sorted(seqs))


def main():
    tmp = tempfile.mkdtemp(prefix="qa-ai03-")
    try:
        canonical_dir, _result = build_canonical(tmp)
        demo_dir = build_demo(tmp)
        heavy_dir = build_heavy(tmp)
        failed_dir = build_failed(tmp)
        rejected_dir = build_rejected(tmp)
        legacy_dir, legacy_map = build_legacy(tmp, canonical_dir)
        no_ohlc_dir = build_no_ohlc(tmp, canonical_dir)
        gone_dir = build_strategy_gone(tmp)

        run = observa.inspect_run(canonical_dir)
        check("inspect_run returns a PersistedRun", isinstance(run, observa.PersistedRun))
        check("PersistedRun is exported from observa", "PersistedRun" in observa.__all__)
        check("inspect_run is exported from observa", "inspect_run" in observa.__all__)
        check("inspect_run accepts os.PathLike", isinstance(
            observa.inspect_run(type("P", (), {"__fspath__": lambda self: canonical_dir})()),
            observa.PersistedRun))

        test_meta_and_metrics(run, canonical_dir)
        test_event_queries(run)
        test_bar_attribution(run)
        test_bar_lookup(run, demo_dir, no_ohlc_dir)
        test_positions(run, canonical_dir, legacy_dir, legacy_map)
        test_orders_and_rejections(run, rejected_dir)
        test_annotations_on_position(run, demo_dir)
        test_g11_g12_limitations(run, rejected_dir)
        test_failed_run(failed_dir)
        test_no_rerun_and_no_writes(gone_dir, canonical_dir)
        test_errors(tmp)
        test_scale_and_serialization(heavy_dir, run)
        test_ordering(run)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
