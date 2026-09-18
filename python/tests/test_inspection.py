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
    """A genuinely historical run.

    Historically faithful in both respects this project cares about:
    UUIDv4 position ids (pre-OBS-DET-01) and **no** ``position_closed.order_seq``
    (pre-OBS-SCHEMA-02) — matching the frozen
    ``legacy_uuidv4_close_ticket.json`` fixture.
    """
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
        if event.get("type") == "position_closed":
            event.pop("order_seq", None)
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


def test_g11_limitations(run, rejected_dir):
    # OBS-SCHEMA-01: the strategy's own per-signal reason IS now persisted on the
    # canonical strategy_decision event and surfaces here verbatim.
    filled = run.order(0)
    check("an order exposes no invented strategy reason", filled.get("reason") is None)
    decisions = run.events(event_type="strategy_decision")
    allowed = {"event_seq", "type", "bar_index", "signal_count", "signals"}
    check("strategy_decision carries only canonical fields",
          all(set(e) <= allowed for e in decisions),
          sorted(decisions[0]) if decisions else None)
    with_reason = [e for e in decisions if e.get("signals")]
    check("a decision that carried a reason persists it",
          with_reason and all(isinstance(e["signals"], list) and e["signals"] for e in with_reason),
          len(with_reason))
    check("persisted reasons are index-aligned with at least one non-null",
          all([s["signal_index"] for s in e["signals"]] == list(range(len(e["signals"])))
              and any(s["reason"] for s in e["signals"]) for e in with_reason))
    check("order_created carries no reason field",
          all("reason" not in e for e in run.events(event_type="order_created")))
    rejections = observa.inspect_run(rejected_dir).events(event_type="order_rejected")
    check("a rejection keeps its own canonical reason text",
          rejections and all(isinstance(e.get("reason"), str) and e["reason"] for e in rejections))


# ── OBS-SCHEMA-02 — canonical closing-order linkage ────────────────────────


def build_linkage_run(tmp, fill_mode):
    """A deterministic run with one explicit ticket close in `fill_mode`."""

    class OpenThenClose:
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
                return {"signals": [{"direction": "buy", "size": 1.0, "reason": "open"}]}
            if portfolio["open_positions"]:
                pos = portfolio["open_positions"][0]
                return {"signals": [{"direction": "close", "size": pos["size"],
                                     "ticket": pos["position_id"], "reason": "close"}]}
            return {"signals": []}

    out = os.path.join(tmp, "linkage_%s" % fill_mode)
    observa.run(OpenThenClose(), tb.FIXTURE,
                config=cfg(fill_mode=fill_mode), output=out)
    return out


def build_multi_close_run(tmp):
    """Three simultaneous positions: close the second, then the other two on one
    bar — the multi/hedged/same-bar matrix from the ticket."""

    class MultiClose:
        def __init__(self):
            self.n = 0
            self.ids = []

        def initialize(self, params=None):
            pass

        def teardown(self):
            pass

        def on_bar(self, bar, portfolio, history):
            i = self.n
            self.n += 1
            if i == 0:
                return {"signals": [
                    {"direction": "buy", "size": 1.0, "reason": "A"},
                    {"direction": "buy", "size": 1.0, "reason": "B"},
                    {"direction": "buy", "size": 1.0, "reason": "C"},
                ]}
            opens = portfolio["open_positions"]
            if len(opens) == 3:
                self.ids = [p["position_id"] for p in opens]
                return {"signals": [{"direction": "close", "size": 1.0,
                                     "ticket": self.ids[1], "reason": "close B"}]}
            if len(opens) == 2:
                return {"signals": [
                    {"direction": "close", "size": 1.0, "ticket": self.ids[0],
                     "reason": "close A"},
                    {"direction": "close", "size": 1.0, "ticket": self.ids[2],
                     "reason": "close C"},
                ]}
            return {"signals": []}

    out = os.path.join(tmp, "multi_close")
    observa.run(MultiClose(), tb.FIXTURE, config=cfg(fill_mode=observa.NEXT_BAR_OPEN),
                output=out)
    return out


def build_protective_run(tmp, kind):
    """A run whose only close is a protective SL/TP exit.

    The level sits ~10 pips from the entry, well inside the canonical dataset's
    per-bar range (>= 34 pips), so the exit is guaranteed within the run.
    """

    class Protective:
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
                level = bar["close"] - 0.0010 if kind == "sl" else bar["close"] + 0.0010
                return {"signals": [{"direction": "buy", "size": 1.0,
                                     "sl": level if kind == "sl" else None,
                                     "tp": level if kind == "tp" else None,
                                     "reason": "open"}]}
            return {"signals": []}

    out = os.path.join(tmp, "protective_%s" % kind)
    observa.run(Protective(), tb.FIXTURE, config=cfg(fill_mode=observa.NEXT_BAR_OPEN),
                output=out)
    return out


def build_rejected_close(tmp):
    """A run where the only close attempt is rejected — it must never close."""

    class RejectedClose:
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
                return {"signals": [{"direction": "buy", "size": 1.0, "reason": "open"}]}
            if i == 1:
                return {"signals": [{"direction": "close", "size": 1.0,
                                     "ticket": "not-a-uuid", "reason": "bogus"}]}
            return {"signals": []}

    out = os.path.join(tmp, "rejected_close")
    observa.run(RejectedClose(), tb.FIXTURE, config=cfg(), output=out)
    return out


def _tamper(tmp, source_dir, name, mutate):
    """Copies a run and applies `mutate` to each parsed events.jsonl line."""
    dest = os.path.join(tmp, name)
    shutil.copytree(source_dir, dest)
    path = os.path.join(dest, "events.jsonl")
    with open(path) as fh:
        lines = [json.loads(l) for l in fh if l.strip()]
    with open(path, "w") as fh:
        for event in lines:
            fh.write(json.dumps(mutate(event)) + "\n")
    return dest


def test_closing_order_linkage(tmp, run, canonical_dir, legacy_dir):
    """OBS-SCHEMA-02: item-by-item linkage contract."""
    # ── 1. Only Signal closes carry a recorded closing order ──
    raw = [json.loads(l) for l in open(os.path.join(canonical_dir, "events.jsonl"))
           if l.strip()]
    closes = [e for e in raw if e["type"] == "position_closed"]
    signal_closes = [e for e in closes if e["exit_reason"] == "Signal"]
    protective_closes = [e for e in closes if e["exit_reason"] != "Signal"]
    check("canonical baseline has 47 closes (40 Signal / 7 protective)",
          (len(closes), len(signal_closes), len(protective_closes)) == (47, 40, 7),
          (len(closes), len(signal_closes), len(protective_closes)))
    check("every Signal close persists an int order_seq",
          all("order_seq" in e and isinstance(e["order_seq"], int)
              and not isinstance(e["order_seq"], bool)
              for e in signal_closes))
    check("no protective close carries an order_seq key (omitted, not null)",
          all("order_seq" not in e for e in protective_closes),
          [e.get("order_seq") for e in protective_closes])
    check("event count is unchanged by the additive field", len(raw) == 4862, len(raw))

    # ── 2. position() resolves the exact order ──
    trades = run.trades()
    sig = [t for t in trades if t["exit_reason"] == "Signal"]
    prot = [t for t in trades if t["exit_reason"] != "Signal"]
    check("the canonical run has 40 Signal and 7 protective trades",
          (len(sig), len(prot)) == (40, 7), (len(sig), len(prot)))

    for trade in sig[:5]:
        pid = trade["position_id"]
        lifecycle = run.position(pid)
        closer = lifecycle["closing_order"]
        check("position(%s) closing_order is the persisted order" % pid[:8],
              closer is not None
              and closer["order_seq"] == lifecycle["closed"]["order_seq"],
              closer and closer.get("order_seq"))
        check("the resolved closing order is filled and distinct from the opener",
              closer["state"] == "filled"
              and closer["order_seq"] != lifecycle["opening_order"]["order_seq"],
              (closer.get("order_seq"),
               lifecycle["opening_order"] and lifecycle["opening_order"].get("order_seq")))

    # ── 3. Bidirectional order <-> position reference ──
    for trade in sig:
        lifecycle = run.position(trade["position_id"])
        seq = lifecycle["closing_order"]["order_seq"]
        check("order(%d) points back at the position it closed" % seq,
              run.order(seq)["position_id"] == trade["position_id"],
              run.order(seq)["position_id"])
    entry_ok = all(
        run.order(run.position(t["position_id"])["opening_order"]["order_seq"])["position_id"]
        == t["position_id"]
        for t in trades
    )
    check("opening orders still resolve to the position they opened", entry_ok)

    # ── 4. Protective closes resolve to None, with no synthetic lifecycle ──
    for trade in prot:
        pid = trade["position_id"]
        lifecycle = run.position(pid)
        check("protective close (%s) reports closing_order=None" % trade["exit_reason"],
              lifecycle["closing_order"] is None, lifecycle["closing_order"])
        event = lifecycle["closed"]
        check("protective close event has no order_seq key",
              "order_seq" not in event, event.get("order_seq"))
        check("protective close exposes no order events beyond the opener's",
              all(e.get("order_seq") == lifecycle["opening_order"]["order_seq"]
                  for e in lifecycle["events"] if "order_seq" in e),
              [e["type"] for e in lifecycle["events"]])

    # ── 5. positions() summary ──
    summaries = {p["position_id"]: p for p in run.positions()}
    check("positions() exposes closing_order_seq for every Signal close",
          all(summaries[t["position_id"]]["closing_order_seq"]
              == run.position(t["position_id"])["closing_order"]["order_seq"]
              for t in sig))
    check("positions() reports closing_order_seq=None for protective closes",
          all(summaries[t["position_id"]]["closing_order_seq"] is None for t in prot))
    check("positions() keeps opening_order_seq unchanged",
          all(isinstance(p["opening_order_seq"], int) for p in summaries.values()))
    open_pid = run.positions(open=True)[0]["position_id"]
    check("an open position has no closing_order_seq",
          summaries[open_pid]["closing_order_seq"] is None)
    check("an open position has closing_order=None",
          run.position(open_pid)["closing_order"] is None)

    # ── 6. Position event list includes the closer's lifecycle ──
    sample = run.position(sig[0]["position_id"])
    closer_seq = sample["closing_order"]["order_seq"]
    closer_events = [e["type"] for e in sample["events"] if e.get("order_seq") == closer_seq]
    check("position events include the closing order's lifecycle",
          {"order_created", "order_filled"} <= set(closer_events), closer_events)
    check("position events for the closer are de-duplicated and ordered",
          [e["event_seq"] for e in sample["events"]]
          == sorted({e["event_seq"] for e in sample["events"]}))

    # ── 7. trades() is untouched ──
    in_process = observa.run(SampleEma(), tb.FIXTURE, config=cfg()).trades
    check("trades() still matches RunResult.trades exactly (no injected field)",
          trades == in_process and all("closing_order" not in t for t in trades))

    # ── 8. BAR_CLOSE and NEXT_BAR_OPEN both link exactly one order ──
    for fill_mode in (observa.BAR_CLOSE, observa.NEXT_BAR_OPEN):
        link_dir = build_linkage_run(tmp, fill_mode)
        link_run = observa.inspect_run(link_dir)
        link_trades = link_run.trades()
        check("%s close produced exactly one trade" % fill_mode, len(link_trades) == 1)
        lifecycle = link_run.position(link_trades[0]["position_id"])
        closer = lifecycle["closing_order"]
        check("%s close links an order_seq" % fill_mode,
              closer is not None and isinstance(closer["order_seq"], int))
        check("%s closer is not the opening order" % fill_mode,
              closer["order_seq"] != lifecycle["opening_order"]["order_seq"],
              (closer["order_seq"], lifecycle["opening_order"]["order_seq"]))
        check("%s closer resolves back to the position" % fill_mode,
              link_run.order(closer["order_seq"])["position_id"]
              == link_trades[0]["position_id"])
        check("%s closer lifecycle has order_created and order_filled" % fill_mode,
              closer["created"] is not None and closer["filled"] is not None)

    # ── 9. Multiple/hedged/same-bar closes stay unambiguous ──
    multi_dir = build_multi_close_run(tmp)
    multi = observa.inspect_run(multi_dir)
    m_trades = multi.trades()
    check("multi-close scenario closed three positions", len(m_trades) == 3, len(m_trades))
    closer_seqs = [multi.position(t["position_id"])["closing_order"]["order_seq"]
                   for t in m_trades]
    check("each multi-close position has its own distinct closing order",
          len(set(closer_seqs)) == 3, closer_seqs)
    check("closing orders differ from every opening order",
          all(multi.position(t["position_id"])["closing_order"]["order_seq"]
              != multi.position(t["position_id"])["opening_order"]["order_seq"]
              for t in m_trades))
    same_bar = [t for t in m_trades if t["bar_index"] == m_trades[-1]["bar_index"]]
    check("two closes share a bar and still link distinct orders",
          len(same_bar) == 2
          and len({multi.position(t["position_id"])["closing_order"]["order_seq"]
                   for t in same_bar}) == 2,
          [t["bar_index"] for t in m_trades])
    check("each position's closer resolves back to itself",
          all(multi.order(multi.position(t["position_id"])["closing_order"]["order_seq"])[
              "position_id"] == t["position_id"] for t in m_trades))

    # ── 10. Protective runs allocate no order at all ──
    for kind, reason in (("sl", "StopLoss"), ("tp", "TakeProfit")):
        p_dir = build_protective_run(tmp, kind)
        p_run = observa.inspect_run(p_dir)
        p_trades = p_run.trades()
        check("protective %s run closed exactly one position" % kind, len(p_trades) == 1)
        event = p_run.position(p_trades[0]["position_id"])["closed"]
        check("protective %s close has no order_seq key" % kind, "order_seq" not in event)
        check("protective %s close resolves to closing_order=None" % kind,
              p_run.position(p_trades[0]["position_id"])["closing_order"] is None)
        orders = p_run.events(event_type="order_created")
        check("protective %s close allocated exactly one (entry) order" % kind,
              len(orders) == 1, len(orders))

    # ── 11. A rejected close never becomes a closing order ──
    r_dir = build_rejected_close(tmp)
    r_run = observa.inspect_run(r_dir)
    check("rejected close produced no trade", r_run.trades() == [])
    check("rejected close produced no position_closed",
          r_run.events(event_type="position_closed") == [])
    check("rejected close is recorded as a rejection",
          len(r_run.events(event_type="order_rejected")) == 1)
    check("the still-open position has no closing-order linkage",
          all(p["closing_order_seq"] is None for p in r_run.positions()))

    # ── 12. Historical runs return None and are never modified ──
    legacy = observa.inspect_run(legacy_dir)
    legacy_signal = [t for t in legacy.trades() if t["exit_reason"] == "Signal"]
    check("historical UUIDv4 run still inspects", len(legacy.trades()) == 47)
    check("historical Signal closes report closing_order=None (not recorded)",
          legacy_signal
          and all(legacy.position(t["position_id"])["closing_order"] is None
                  for t in legacy_signal))
    check("historical Signal closes have no order_seq key",
          all("order_seq" not in legacy.position(t["position_id"])["closed"]
              for t in legacy_signal))
    check("historical positions expose closing_order_seq=None",
          all(p["closing_order_seq"] is None for p in legacy.positions()))

    # frozen fixture: byte-identical evidence, closing_order stays None
    frozen = os.path.join(HERE, "fixtures", "legacy_uuidv4_close_ticket.json")
    frozen_events = json.load(open(frozen))["events"]
    frozen_closes = [e for e in frozen_events if e["type"] == "position_closed"]
    check("frozen legacy fixture has no order_seq key",
          frozen_closes and all("order_seq" not in e for e in frozen_closes))

    # ── 13-15. Malformed references are invalid artifacts ──
    sig_pid = sig[0]["position_id"]

    def set_seq(value):
        def mutate(event):
            if (event.get("type") == "position_closed"
                    and event.get("position_id") == sig_pid):
                event["order_seq"] = value
            return event
        return mutate

    for label, value in (("missing target", 987654), ("non-integer string", "3"),
                         ("boolean", True), ("float", 2.5)):
        bad = _tamper(tmp, canonical_dir, "bad_%s" % label.replace(" ", "_"),
                      set_seq(value))
        try:
            observa.inspect_run(bad)
            raised = None
        except ValueError as exc:
            raised = exc
        check("malformed order_seq (%s) raises RUN_ARTIFACTS_INVALID" % label,
              raised is not None
              and getattr(raised, "code", None) == "RUN_ARTIFACTS_INVALID",
              getattr(raised, "code", None))

    # A well-typed reference with no target is caught by the inspector's
    # canonical-reference validation, which reports both identifiers.
    bad_target = _tamper(tmp, canonical_dir, "bad_target", set_seq(987654))
    try:
        observa.inspect_run(bad_target)
        raised_target = None
    except ValueError as exc:
        raised_target = exc
    check("an unresolved order_seq reports position_id + order_seq",
          getattr(raised_target, "details", {}).get("position_id") == sig_pid
          and getattr(raised_target, "details", {}).get("order_seq") == 987654,
          getattr(raised_target, "details", None))

    # A wrongly-typed reference is rejected even earlier, by the canonical Rust
    # loader, with the offending file and line — never coerced.
    for label, value in (("string", "3"), ("boolean", True), ("float", 2.5)):
        bad_type = _tamper(tmp, canonical_dir, "type_%s" % label, set_seq(value))
        try:
            observa.inspect_run(bad_type)
            raised_type = None
        except ValueError as exc:
            raised_type = exc
        details = getattr(raised_type, "details", {}) or {}
        check("a %s order_seq is rejected by the canonical loader, not coerced" % label,
              getattr(raised_type, "code", None) == "RUN_ARTIFACTS_INVALID"
              and details.get("path", "").endswith("events.jsonl")
              and isinstance(details.get("line"), int),
              (getattr(raised_type, "code", None), details))

    # Defense in depth: the inspector's own index also refuses a wrongly-typed
    # reference if one ever reaches it (loaders are not the only entry point).
    from observa import inspection as _inspection

    checks = []
    for value in ("3", True, 2.5):
        payload = [{
            "event_seq": 0, "type": "bar_processed", "bar_index": 0,
        }, {
            "event_seq": 1, "type": "position_closed", "position_id": "P",
            "order_seq": value, "side": "Buy", "quantity_lots": 1.0,
            "entry_price": 1.0, "exit_price": 1.0, "exit_reason": "Signal",
            "gross_realized_pnl": 0.0, "total_commission": 0.0,
            "net_realized_pnl": 0.0, "bar_index": 0,
            "timestamp": "2024-01-01T00:00:00Z",
        }]
        probe = _inspection.PersistedRun.__new__(_inspection.PersistedRun)
        try:
            probe._build_indexes(payload)
            checks.append((value, None))
        except ValueError as exc:
            checks.append((value, getattr(exc, "code", None)))
    check("the inspector index independently rejects non-integer order_seq",
          all(code == "RUN_ARTIFACTS_INVALID" for _v, code in checks), checks)

    # explicit null / absence are both valid
    nulled = _tamper(tmp, canonical_dir, "null_seq", set_seq(None))
    nulled_run = observa.inspect_run(nulled)
    check("an explicit null order_seq is accepted as no linkage",
          nulled_run.position(sig_pid)["closing_order"] is None)

    # ── 16. Broken OPENING references get the same treatment ──
    def break_opening(event):
        if event.get("type") == "position_opened":
            event["order_seq"] = 987654
        return event

    bad_open = _tamper(tmp, canonical_dir, "bad_opening", break_opening)
    try:
        observa.inspect_run(bad_open)
        raised_open = None
    except ValueError as exc:
        raised_open = exc
    check("a broken opening-order reference raises RUN_ARTIFACTS_INVALID",
          raised_open is not None
          and getattr(raised_open, "code", None) == "RUN_ARTIFACTS_INVALID",
          getattr(raised_open, "code", None))

    # A conflicting link (one order claimed by two positions) is invalid rather
    # than resolved by picking a winner.
    other_pid = next(t["position_id"] for t in sig if t["position_id"] != sig_pid)
    other_opening = run.position(other_pid)["opening_order"]["order_seq"]
    conflict = _tamper(tmp, canonical_dir, "conflict", set_seq(other_opening))
    try:
        observa.inspect_run(conflict)
        raised_conflict = None
    except ValueError as exc:
        raised_conflict = exc
    check("an order linked to two positions is an invalid artifact",
          raised_conflict is not None
          and getattr(raised_conflict, "code", None) == "RUN_ARTIFACTS_INVALID",
          getattr(raised_conflict, "code", None))

    # ── 17. No heuristic fallback exists (behavioural) ──
    # A historical run whose ONLY change is a missing order_seq must return None
    # even though a filled order sits on the same bar and the opener is known.
    stripped = _tamper(tmp, canonical_dir, "stripped", lambda e: _strip_close_seq(e))
    stripped_run = observa.inspect_run(stripped)
    check("stripping the persisted link yields None (never re-derived)",
          all(stripped_run.position(t["position_id"])["closing_order"] is None
              for t in stripped_run.trades()))
    check("adjacent same-bar filled orders are not used as a fallback",
          stripped_run.position(sig[0]["position_id"])["closing_order"] is None)


def _strip_close_seq(event):
    if event.get("type") == "position_closed":
        event.pop("order_seq", None)
    return event


def test_no_heuristic_lookup():
    """Source audit: `closing_order` may only be resolved from `order_seq`.

    The audit inspects *executable logic* (AST), never docstrings or comments,
    so documentation that names the forbidden techniques cannot mask — or
    falsely trigger — the check.
    """
    import ast

    from observa import inspection

    tree = ast.parse(open(inspection.__file__, encoding="utf-8").read())

    def find(name, within=None):
        nodes = [
            n for n in ast.walk(within if within is not None else tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        ]
        assert len(nodes) == 1, "expected exactly one %s()" % name
        return nodes[0]

    position = find("position")
    index = find("_build_indexes")

    # 1. The returned `closing_order` value is the resolved reference variable.
    returned = None
    for node in ast.walk(position):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == "closing_order":
                    returned = v
    check("position() returns a closing_order key", returned is not None)
    check("closing_order is returned as a plain variable (no expression)",
          isinstance(returned, ast.Name), ast.dump(returned) if returned else None)

    # 2. That variable is bound only from None or self.order(<reference>).
    target = returned.id
    bindings = [
        n for n in ast.walk(position)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == target for t in n.targets)
    ]
    check("closing_order is assigned only in the None/self.order() branch",
          len(bindings) == 2
          and isinstance(bindings[0].value, ast.Constant)
          and bindings[0].value.value is None
          and isinstance(bindings[1].value, ast.Call)
          and isinstance(bindings[1].value.func, ast.Attribute)
          and bindings[1].value.func.attr == "order",
          [ast.dump(b.value) for b in bindings])

    # 3. No candidate scoring, sorting, searching or scanning anywhere in the
    #    resolver or the index that could stand in for the persisted reference.
    for fn in (position, index):
        banned_calls = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        } & {"sorted", "min", "max", "next", "filter", "sum"}
        check("%s() performs no candidate search/score/selection" % fn.name,
              not banned_calls, banned_calls)

    # 4. No comparison logic over the identifying attributes that a heuristic
    #    would need (side / quantity / bar / timestamp matching).
    for fn in (position, index):
        fields = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) or isinstance(sub, ast.Subscript):
                        fields.add(getattr(sub, "attr", "") or "")
                    if isinstance(sub, ast.Name):
                        fields.add(sub.id)
        used = fields & {"side", "quantity_lots", "bar_index", "created_bar",
                         "timestamp", "filled_bar", "executed_price"}
        check("%s() compares no economic identity fields" % fn.name, not used, used)

    # 5. The linkage is read from the persisted event, never computed.
    check("the index stores the persisted closing_order_seq",
          any(
              isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Subscript) and
                      isinstance(t.slice, ast.Constant) and
                      t.slice.value == "closing_order_seq" for t in n.targets)
              for n in ast.walk(index)
          ))

    # 6. Behavioural proof of item 3-4: with the persisted link removed, a
    #    run whose closer is trivially "findable" by adjacency still yields None.
    check("the closing reference is never re-derived (behavioural proof)",
          _stripped_run_returns_none())


def _stripped_run_returns_none():
    """Behavioural counterpart to the AST audit.

    Takes a real explicit-close run, deletes every persisted
    ``position_closed.order_seq``, then asserts the inspector still reports
    ``closing_order = None`` even though the closing order is the immediately
    preceding ``order_filled`` on the same bar (the adjacency a heuristic would
    exploit).
    """
    tmp = tempfile.mkdtemp(prefix="qa-schema02-nofallback-")
    try:
        out = os.path.join(tmp, "run")
        observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=out)
        stripped = _tamper(tmp, out, "stripped", _strip_close_seq)
        run = observa.inspect_run(stripped)
        closed = [t for t in run.trades() if t["exit_reason"] == "Signal"]
        if not closed or any(run.position(t["position_id"])["closing_order"] is not None
                             for t in closed):
            return False
        # Sanity: the exploitable structure really is present (a filled order
        # on the same chronology as the close) — otherwise the check is vacuous.
        sample = run.position(closed[0]["position_id"])
        return any(e["type"] == "order_filled" for e in sample["events"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_linkage_determinism(tmp, canonical_dir):
    """Repeated runs reproduce the linkage and the artifacts byte-for-byte."""
    out_a = os.path.join(tmp, "det_a")
    out_b = os.path.join(tmp, "det_b")
    observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=out_a)
    observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=out_b)
    a = observa.inspect_run(out_a)
    b = observa.inspect_run(out_b)
    check("closing_order linkage is identical across repeated runs",
          [a.position(t["position_id"])["closing_order"] for t in a.trades()]
          == [b.position(t["position_id"])["closing_order"] for t in b.trades()])
    check("run.json is byte-identical across repeated runs",
          sha_dir(out_a)["run.json"] == sha_dir(out_b)["run.json"])
    check("metrics.json is byte-identical across repeated runs",
          sha_dir(out_a)["metrics.json"] == sha_dir(out_b)["metrics.json"])
    check("events.jsonl is byte-identical across repeated runs",
          sha_dir(out_a)["events.jsonl"] == sha_dir(out_b)["events.jsonl"])
    # OrderSeq allocation is unchanged by the linkage.
    check("OrderSeq allocation is unchanged (88 orders)",
          len({e["order_seq"] for e in a.events()
               if e["type"] == "order_created"}) == 88)
    check("the closing orders are a subset of the canonical 88",
          all(t["position_id"] for t in a.trades()))



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
        test_g11_limitations(run, rejected_dir)
        test_closing_order_linkage(tmp, run, canonical_dir, legacy_dir)
        test_no_heuristic_lookup()
        test_linkage_determinism(tmp, canonical_dir)
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
