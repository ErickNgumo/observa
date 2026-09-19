"""OBS-MCP-01 / OBS-AI-05 — read-only MCP server tests (installed wheel).

Run against an installed Observa wheel **with the optional MCP extra**:

    pip install "dist/observa-...whl[mcp]"
    python python/tests/test_mcp.py

Primary coverage drives the server through a **real MCP v2 client over actual
stdio** (no mocked transport): tool surface, run discovery, path security,
per-tool delegation fidelity, pagination exactness, error envelopes, historical
compatibility, read-only guarantees and stdout protocol cleanliness.

OBS-AI-05 adds the **authoring-discovery** surface (contract / example / guide)
and lazy runs-root validation; both are covered here too.

Cache internals (load-once, ``list_runs`` never populating the cache) are
asserted in-process, because they are deliberately invisible from the wire.

See ``docs/MCP.md`` for the public contract.
"""

import asyncio
import builtins
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import observa
import observa.mcp_server as mcp_server
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from observa.samples.sample_strategy import SampleEma

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_canonical_baseline as tb  # noqa: E402

PASSED, FAILED = [], []

#: The frozen inspection surface — OBS-AI-05 adds nothing here and changes
#: nothing here.
INSPECTION_TOOLS = {
    "list_runs",
    "get_run_summary",
    "list_events",
    "get_event",
    "get_bar",
    "list_positions",
    "get_position",
    "get_order",
    "list_trades",
    "list_rejections",
}

#: The three read-only authoring-discovery tools added by OBS-AI-05.
AUTHORING_TOOLS = {
    "get_strategy_contract",
    "get_strategy_example",
    "get_strategy_guide",
}

#: Exact union — asserted with ``==``, never a loose ``>=``.
EXPECTED_TOOLS = INSPECTION_TOOLS | AUTHORING_TOOLS

#: The nine inspection tools that take a ``run``; ``list_runs`` takes none.
RUN_SCOPED_TOOLS = INSPECTION_TOOLS - {"list_runs"}

FORBIDDEN_TOOLS = {
    "get_metrics", "list_bars", "raw_file", "run_strategy", "create_run",
    "delete_run", "edit_run", "notes", "compare_runs", "explain",
    # OBS-AI-05: validation executes user code and stays CLI/Python-only.
    "validate_strategy", "write_strategy", "save_strategy", "generate_strategy",
    "get_strategy_path", "list_strategies", "delete_strategy",
}


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: %s" % (detail,)))


def sha_tree(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ── tiny deterministic datasets / strategies ─────────────────────────────

TINY_BARS = [
    (1.1000, 1.1010, 1.0990, 1.1000),
    (1.1000, 1.1010, 1.0990, 1.1005),
    (1.1005, 1.1015, 1.0995, 1.1010),
]
PROT_BARS = [
    (1.1000, 1.1010, 1.0990, 1.1000),
    (1.1000, 1.1005, 1.0980, 1.0990),   # low crosses the 1.0995 stop
    (1.0990, 1.0995, 1.0985, 1.0992),
]


def write_csv(path, bars):
    lines = ["timestamp,open,high,low,close,volume"]
    for i, (o, h, low, c) in enumerate(bars):
        lines.append("2024-03-01 %02d:%02d:00+00:00,%.4f,%.4f,%.4f,%.4f,100.0"
                     % (i // 4, (i % 4) * 15, o, h, low, c))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def tiny_config(csv_path, **kw):
    base = dict(
        dataset_source=csv_path,
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=0.0,
        interval="15m",
        strategy_name="TinyStrategy",
    )
    base.update(kw)
    return observa.Config(**base)


class TinyCloseByTicket:
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
            return {"signals": [{"direction": "buy", "size": 1.0,
                                 "reason": "tiny explicit close"}]}
        if portfolio["open_positions"]:
            pos = portfolio["open_positions"][0]
            return {"signals": [{"direction": "close", "size": pos["size"],
                                 "ticket": pos["position_id"], "reason": "closing"}]}
        return {"signals": []}


class TinyProtective:
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
            return {"signals": [{"direction": "buy", "size": 1.0,
                                 "sl": 1.0995, "reason": "tiny protective"}]}
        return {"signals": []}


class TinyOpenForever:
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
            return {"signals": [{"direction": "buy", "size": 1.0, "reason": "stays open"}]}
        return {"signals": []}


class TinyFailAfterOpen:
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
            return {"signals": [{"direction": "buy", "size": 1.0, "reason": "then fail"}]}
        raise RuntimeError("scripted failure after open")


# ── run fixtures ─────────────────────────────────────────────────────────


def _copy_run(src, dst):
    shutil.copytree(src, dst)
    return dst


def _read_events(run_dir):
    with open(os.path.join(run_dir, "events.jsonl"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_events(run_dir, events):
    with open(os.path.join(run_dir, "events.jsonl"), "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def _remap_uuid4(run_dir):
    """Rewrites every position_id to a genuine UUIDv4 value (pre-OBS-DET-01)."""
    events = _read_events(run_dir)
    mapping = {}
    for event in events:
        pid = event.get("position_id")
        if isinstance(pid, str):
            if pid not in mapping:
                mapping[pid] = str(uuid.uuid4())
            event["position_id"] = mapping[pid]
    _write_events(run_dir, events)


def _strip_signals(run_dir):
    events = _read_events(run_dir)
    for event in events:
        if event.get("type") == "strategy_decision":
            event.pop("signals", None)
    _write_events(run_dir, events)


def _strip_order_seq(run_dir):
    events = _read_events(run_dir)
    for event in events:
        if event.get("type") == "position_closed":
            event.pop("order_seq", None)
    _write_events(run_dir, events)


def _rewrite_dataset_source(run_dir, new_source):
    path = os.path.join(run_dir, "run.json")
    with open(path, encoding="utf-8") as fh:
        run = json.load(fh)
    run["dataset"]["source"] = new_source
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(run, fh)


def _build_strategy_gone(tmp, csv_path, out_dir):
    """Persists a run whose strategy module is deleted immediately afterwards."""
    module_dir = os.path.join(tmp, "gone_module")
    os.makedirs(module_dir, exist_ok=True)
    module_path = os.path.join(module_dir, "temp_strategy_module.py")
    with open(module_path, "w", encoding="utf-8") as fh:
        fh.write(
            "class S:\n"
            "    def initialize(self, params=None): pass\n"
            "    def teardown(self): pass\n"
            "    def on_bar(self, bar, portfolio, history):\n"
            "        if not getattr(self, 'done', False):\n"
            "            self.done = True\n"
            "            return [{'direction': 'buy', 'size': 1.0, 'reason': 'gone'}]\n"
            "        return []\n"
        )
    script = (
        "import sys, observa\n"
        "sys.path.insert(0, %r)\n"
        "from temp_strategy_module import S\n"
        "observa.run(S(), %r, config=observa.Config(dataset_source=%r, "
        "fill_mode=observa.NEXT_BAR_OPEN, spread=0.0002, slippage=0.0001, "
        "commission=0.0, interval='15m', strategy_name='Gone'), output=%r)\n"
    ) % (module_dir, csv_path, csv_path, out_dir)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("strategy_gone run failed: %s" % proc.stderr[-600:])
    os.remove(module_path)
    shutil.rmtree(os.path.join(module_dir, "__pycache__"), ignore_errors=True)
    return out_dir


def build_runs(tmp):
    """Builds one runs root containing every scenario the ticket requires."""
    root = os.path.join(tmp, "runs")
    outside = os.path.join(tmp, "outside")
    os.makedirs(root)
    os.makedirs(outside)

    canonical = os.path.join(root, "canonical")
    observa.run(SampleEma(), tb.FIXTURE,
                config=observa.Config(dataset_source=tb.FIXTURE, **tb.CANONICAL),
                output=canonical)

    csv_tiny = write_csv(os.path.join(tmp, "tiny.csv"), TINY_BARS)
    csv_prot = write_csv(os.path.join(tmp, "prot.csv"), PROT_BARS)

    observa.run(TinyCloseByTicket(), csv_tiny, config=tiny_config(csv_tiny),
                output=os.path.join(root, "tiny_ticket"))
    observa.run(TinyProtective(), csv_prot, config=tiny_config(csv_prot),
                output=os.path.join(root, "protective"))
    observa.run(TinyOpenForever(), csv_tiny, config=tiny_config(csv_tiny),
                output=os.path.join(root, "open_only"))
    try:
        observa.run(TinyFailAfterOpen(), csv_tiny, config=tiny_config(csv_tiny),
                    output=os.path.join(root, "failed"))
    except Exception:  # noqa: BLE001 - expected scripted failure
        pass

    uuidv4 = _copy_run(canonical, os.path.join(root, "uuidv4"))
    _remap_uuid4(uuidv4)

    noreason = _copy_run(canonical, os.path.join(root, "noreason"))
    _strip_signals(noreason)

    nolink = _copy_run(canonical, os.path.join(root, "nolink"))
    _strip_order_seq(nolink)

    no_ohlc = _copy_run(canonical, os.path.join(root, "no_ohlc"))
    _rewrite_dataset_source(no_ohlc, os.path.join(tmp, "gone.csv"))

    _build_strategy_gone(tmp, csv_tiny, os.path.join(root, "strategy_gone"))

    os.makedirs(os.path.join(root, "not_a_run"))

    broken = os.path.join(root, "broken")
    os.makedirs(broken)
    with open(os.path.join(broken, "run.json"), "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid json")

    outside_run = _copy_run(canonical, os.path.join(outside, "secret"))
    os.symlink(outside_run, os.path.join(root, "escape"))

    return root, outside_run


# ── stdio plumbing ───────────────────────────────────────────────────────


def server_params(root):
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "observa.mcp_server", "--runs-dir", root],
        env=dict(os.environ),
    )


def calls_sync(params, requests, timeout=300):
    """Runs ``[(tool, args), ...]`` in ONE real stdio session.

    Returns a list of ``(result, payload_or_None)``. Batching keeps the suite
    fast without mocking anything: every call still crosses a real stdio pipe.
    """

    async def go():
        async with Client(params, raise_exceptions=False) as client:
            out = []
            for tool, args in requests:
                result = await client.call_tool(tool, args)
                text = result.content[0].text if result.content else ""
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = None
                out.append((result, payload))
            return out

    return asyncio.run(asyncio.wait_for(go(), timeout=timeout))


def call_sync(params, tool, arguments, timeout=300):
    return calls_sync(params, [(tool, arguments)], timeout=timeout)[0]


# ── tests ────────────────────────────────────────────────────────────────


def test_startup_and_tool_surface(params):
    async def go():
        async with Client(params) as client:
            return await client.list_tools()

    tools = asyncio.run(asyncio.wait_for(go(), timeout=180)).tools
    names = {t.name for t in tools}
    check("stdio server starts and answers list_tools", bool(names), sorted(names))
    check("tool list is exactly the thirteen expected tools", names == EXPECTED_TOOLS,
          sorted(names ^ EXPECTED_TOOLS))
    check("the ten inspection tools are unchanged (frozen set)",
          INSPECTION_TOOLS <= names, sorted(INSPECTION_TOOLS - names))
    check("the three authoring-discovery tools are exposed",
          AUTHORING_TOOLS <= names, sorted(AUTHORING_TOOLS - names))
    check("no forbidden tool is exposed", not (names & FORBIDDEN_TOOLS), names & FORBIDDEN_TOOLS)
    check("every tool advertises an object-rooted input schema",
          all((t.input_schema or {}).get("type") == "object" for t in tools))
    lr = next(t for t in tools if t.name == "list_runs")
    check("list_runs requires no arguments",
          not (lr.input_schema or {}).get("required"), lr.input_schema.get("required"))
    required_with_run = {
        t.name for t in tools
        if "run" in (t.input_schema or {}).get("required", [])
    }
    check("run is required on exactly the nine run-scoped inspection tools",
          required_with_run == RUN_SCOPED_TOOLS,
          sorted(required_with_run ^ RUN_SCOPED_TOOLS))
    check("no authoring tool requires any argument",
          all(not (t.input_schema or {}).get("required")
              for t in tools if t.name in AUTHORING_TOOLS),
          {t.name: (t.input_schema or {}).get("required")
           for t in tools if t.name in AUTHORING_TOOLS})
    check("no authoring tool declares a path-like parameter",
          all(not (t.input_schema or {}).get("properties")
              for t in tools if t.name in AUTHORING_TOOLS),
          {t.name: (t.input_schema or {}).get("properties")
           for t in tools if t.name in AUTHORING_TOOLS})


def test_list_runs(root):
    _r, data = call_sync(server_params(root), "list_runs", {})
    names = {r["run"] for r in data["runs"]}
    check("list_runs returns count/runs/errors", (isinstance(data.get("count"), int)
          and isinstance(data.get("runs"), list) and isinstance(data.get("errors"), list)))
    check("list_runs finds every valid run",
          {"canonical", "tiny_ticket", "protective", "open_only", "failed", "uuidv4",
           "noreason", "nolink", "no_ohlc", "strategy_gone"} <= names, sorted(names))
    check("list_runs ignores a directory with no run.json", "not_a_run" not in names)
    check("list_runs does not follow a symlink escape", "escape" not in names)
    check("list_runs surfaces a malformed run.json as a structured error",
          any(e["run"] == "broken" and e["error"]["code"] == "RUN_ARTIFACTS_INVALID"
              for e in data["errors"]), data["errors"])
    entry = next(r for r in data["runs"] if r["run"] == "canonical")
    check("list_runs reports canonical facts straight from artifacts",
          (entry["status"], entry["bar_count"], entry["event_count"], entry["trades"]) ==
          ("completed", 1500, 4862, 47), entry)
    check("list_runs reports a failed run with no trades",
          next(r for r in data["runs"] if r["run"] == "failed")["status"] == "failed")
    check("list_runs exposes no absolute paths",
          root not in json.dumps(data) and os.path.dirname(root) not in json.dumps(data))
    check("list_runs reduces the dataset to a basename",
          entry["dataset"] == "canonical_m15.csv", entry["dataset"])


def test_security(root):
    params = server_params(root)
    bads = ["../../etc", "/etc", "..", "a/../../b", "nope", "", "./../x"]
    results = calls_sync(params, [("get_run_summary", {"run": b}) for b in bads])
    envelopes = [p for _r, p in results]
    check("every traversal/absolute/unknown run is refused",
          all(p and p["error"]["code"] == "RUN_DIR_NOT_FOUND" for p in envelopes),
          [(b, (p or {}).get("error", {}).get("code")) for b, p in zip(bads, envelopes)])
    # Same external error for every rejection: identical code and identical
    # message, differing only by the caller's own echoed identifier.
    normalised = {
        json.dumps({"code": p["error"]["code"],
                    "message": p["error"]["message"].split(" at ")[0],
                    "details": sorted(p["error"]["details"])}, sort_keys=True)
        for p in envelopes
    }
    check("escape, traversal and not-found are externally indistinguishable",
          len(normalised) == 1, normalised)
    check("each rejection echoes only the caller's own identifier",
          all(p["error"]["details"] == {"run": b} for b, p in zip(bads, envelopes)),
          [p["error"]["details"] for p in envelopes])
    check("a symlink escape is refused",
          call_sync(params, "get_run_summary", {"run": "escape"})[1]["error"]["code"]
          == "RUN_DIR_NOT_FOUND")
    blob = json.dumps(envelopes)
    check("a denial discloses no server-side filesystem path",
          root not in blob and "path" not in envelopes[0]["error"]["details"],
          envelopes[0])
    check("the error envelope carries code/message/details",
          set(envelopes[0]["error"]) == {"code", "message", "details"}, envelopes[0])
    check("anticipated failures do not set protocol is_error",
          results[0][0].is_error is False)


def test_delegation(root):
    """Every read tool must equal the corresponding PersistedRun call exactly."""
    params = server_params(root)
    persisted = observa.inspect_run(os.path.join(root, "canonical"))
    pid = persisted.positions(open=False)[0]["position_id"]
    first_event = persisted.events()[0]["event_seq"]
    all_positions = persisted.positions(open=False)
    signal_pos = [p for p in all_positions
                  if p["exit_reason"] == "Signal" and p["closing_order_seq"] is not None][0]

    requests = [
        ("get_run_summary", {"run": "canonical"}),
        ("list_events", {"run": "canonical", "limit": 1000}),
        ("get_bar", {"run": "canonical", "bar_index": 57}),
        ("get_position", {"run": "canonical", "position_id": pid}),
        ("get_order", {"run": "canonical", "order_seq": 1}),
        ("list_trades", {"run": "canonical"}),
        ("list_rejections", {"run": "canonical"}),
        ("list_positions", {"run": "canonical", "open": False}),
        ("list_positions", {"run": "canonical", "open": True}),
        ("get_event", {"run": "canonical", "event_seq": first_event}),
        ("get_position", {"run": "canonical", "position_id": signal_pos["position_id"]}),
    ]
    results = [p for _r, p in calls_sync(params, requests)]
    (summary, events, bar, pos, order, trades, rejections, positions,
     open_positions, single, signal_position) = results

    check("get_run_summary delegates to run_summary",
          summary["summary"]["status"] == "completed"
          and summary["summary"]["total_bars"] == 1500
          and summary["summary"]["trades"] == 47, summary["summary"].get("total_bars"))
    check("get_run_summary never recomputes metrics",
          summary["summary"]["metrics"] == observa.run_summary(
              os.path.join(root, "canonical"))["metrics"])
    check("get_run_summary reduces paths to basenames",
          summary["summary"]["artifact_dir"] == "canonical"
          and summary["summary"]["dataset_source"] == "canonical_m15.csv",
          (summary["summary"]["artifact_dir"], summary["summary"]["dataset_source"]))
    check("list_events delegates to PersistedRun.events in canonical order",
          events["events"] == persisted.events()[:len(events["events"])]
          and events["total"] == 4862, events["total"])
    check("get_bar delegates to PersistedRun.bar", bar["bar"] == persisted.bar(57))
    check("get_bar preserves OHLC availability semantics",
          bar["bar"]["ohlc_available"] is True and bar["bar"]["ohlc"] is not None)
    check("get_bar preserves decisions, reasons and drawings keys",
          set(bar["bar"]) >= {"strategy_decisions", "drawings", "portfolio", "events"})
    check("get_position delegates to PersistedRun.position", pos["position"] == persisted.position(pid))
    check("get_position preserves order lifecycles and annotations",
          set(pos["position"]) >= {"opening_order", "closing_order",
                                   "annotations_at_entry", "annotations_at_exit"})
    check("get_order delegates to PersistedRun.order", order["order"] == persisted.order(1))
    check("get_order exposes the position opened or closed by the order",
          order["order"]["position_id"] is not None)
    check("list_trades delegates to PersistedRun.trades unchanged",
          trades["trades"] == persisted.trades() and trades["count"] == 47)
    check("list_rejections delegates to PersistedRun.rejections",
          rejections["rejections"] == persisted.rejections())
    check("list_positions delegates with open=False and counts",
          positions["positions"] == all_positions and positions["count"] == len(all_positions))
    check("list_positions honours open=True", open_positions["count"] == 1, open_positions["count"])
    check("get_event delegates to PersistedRun.event",
          single["event"] == persisted.event(first_event))

    closer = signal_position["position"]["closing_order"]
    check("closing-order linkage is served exactly (case 1)",
          isinstance(closer, dict) and closer["order_seq"] == signal_pos["closing_order_seq"],
          closer and closer.get("order_seq"))
    _r, back = call_sync(params, "get_order", {"run": "canonical", "order_seq": closer["order_seq"]})
    check("the closing order points back at the position it closed",
          back["order"]["position_id"] == signal_pos["position_id"])


def test_envelopes(root):
    params = server_params(root)
    requests = [
        ("list_runs", {}),
        ("get_run_summary", {"run": "canonical"}),
        ("list_events", {"run": "canonical", "limit": 1}),
        ("get_event", {"run": "canonical", "event_seq": 0}),
        ("get_bar", {"run": "canonical", "bar_index": 0}),
        ("list_positions", {"run": "canonical"}),
        ("list_trades", {"run": "canonical"}),
        ("list_rejections", {"run": "canonical"}),
        ("get_position", {"run": "canonical", "position_id": "nope"}),
    ]
    results = calls_sync(params, requests)
    shapes = {t: type(p).__name__ for (t, _a), (_r, p) in zip(requests, results)}
    blocks = {t: len(r.content) for (t, _a), (r, _p) in zip(requests, results)}
    check("every tool returns a JSON object (never a bare list)",
          all(v == "dict" for v in shapes.values()), shapes)
    check("list_trades is one structured result, not one block per trade",
          blocks["list_trades"] == 1, blocks["list_trades"])
    check("no tool fragments its payload into many content blocks",
          all(v == 1 for v in blocks.values()), blocks)


def test_pagination(root):
    params = server_params(root)
    persisted = observa.inspect_run(os.path.join(root, "canonical"))
    full = [e["event_seq"] for e in persisted.events()]
    rejections_total = len(persisted.events(event_type="order_rejected"))
    bar_events = [e["event_seq"] for e in persisted.bar(57)["events"]]

    requests = [
        ("list_events", {"run": "canonical"}),
        ("list_events", {"run": "canonical", "limit": 99999}),
        ("list_events", {"run": "canonical", "limit": 0}),
        ("list_events", {"run": "canonical", "event_type": "order_rejected", "limit": 5}),
        ("list_events", {"run": "canonical", "event_type": "order_rejected", "limit": 1000}),
        ("list_events", {"run": "canonical", "bar_index": 57, "limit": 50}),
    ]
    (default, big, zero, filtered, complete, bybar) = [
        p for _r, p in calls_sync(params, requests)]

    check("list_events default limit is 100",
          default["limit"] == 100 and default["returned"] == 100, default["limit"])
    check("a truncated page always carries next_cursor", default["next_cursor"] is not None)
    check("next_cursor is the last returned event_seq",
          default["next_cursor"] == default["events"][-1]["event_seq"])
    check("limit is clamped down to the 1000 maximum",
          big["limit"] == 1000 and big["returned"] == 1000, big["limit"])
    check("limit is clamped up to at least 1", zero["limit"] == 1 and zero["returned"] == 1)
    check("filters compose with pagination", filtered["total"] == rejections_total,
          (filtered["total"], rejections_total))
    check("a complete result reports next_cursor null", complete["next_cursor"] is None)
    check("bar_index uses canonical chronology buckets",
          [e["event_seq"] for e in bybar["events"]] == bar_events)
    check("total is the filtered count regardless of cursor", complete["total"] == rejections_total)

    seen, cursor, pages = [], None, 0
    while pages < 20:
        args = {"run": "canonical", "limit": 500}
        if cursor is not None:
            args["cursor"] = cursor
        _r, chunk = call_sync(params, "list_events", args)
        seen += [e["event_seq"] for e in chunk["events"]]
        pages += 1
        cursor = chunk["next_cursor"]
        if cursor is None:
            break
    check("page walk returns the complete filtered result", seen == full, (len(seen), len(full)))
    check("page walk has no duplicates", len(set(seen)) == len(seen))
    check("page walk stays in ascending canonical order", seen == sorted(seen))
    check("page walk spanned more than one page", pages > 1, pages)


def test_history_and_errors(root):
    params = server_params(root)
    persisted = observa.inspect_run(os.path.join(root, "canonical"))
    with_reason = next(e for e in persisted.events(event_type="strategy_decision")
                       if e.get("signals"))
    reason_bar = with_reason["bar_index"]
    requests = [
        ("list_positions", {"run": "protective", "open": False}),
        ("list_positions", {"run": "nolink", "open": False}),
        ("list_positions", {"run": "uuidv4"}),
        ("list_events", {"run": "canonical", "bar_index": reason_bar,
                         "event_type": "strategy_decision", "limit": 10}),
        ("list_events", {"run": "noreason", "bar_index": reason_bar,
                         "event_type": "strategy_decision", "limit": 10}),
        ("get_run_summary", {"run": "failed"}),
        ("list_trades", {"run": "failed"}),
        ("get_bar", {"run": "no_ohlc", "bar_index": 0}),
        ("list_events", {"run": "no_ohlc", "limit": 1}),
        ("list_trades", {"run": "strategy_gone"}),
        ("get_run_summary", {"run": "broken"}),
        ("get_event", {"run": "canonical", "event_seq": 999999}),
        ("get_bar", {"run": "canonical", "bar_index": 999999}),
        ("get_position", {"run": "canonical", "position_id": "nope"}),
        ("get_order", {"run": "canonical", "order_seq": 999999}),
    ]
    (prot, nolink, uuidv4, reasons, noreasons, failed, failed_trades, no_ohlc,
     no_ohlc_events, gone, broken, missing_event, missing_bar, missing_pos,
     missing_order) = [p for _r, p in calls_sync(params, requests)]

    check("case 2: protective close has closing_order_seq null",
          prot["positions"][0]["closing_order_seq"] is None, prot["positions"][0])
    check("case 2: protective exit_reason is StopLoss/TakeProfit",
          prot["positions"][0]["exit_reason"] in ("StopLoss", "TakeProfit"),
          prot["positions"][0]["exit_reason"])
    pid_prot = prot["positions"][0]["position_id"]
    check("case 2: protective close serves closing_order null without inference",
          call_sync(params, "get_position", {"run": "protective",
                                             "position_id": pid_prot})[1]["position"]["closing_order"]
          is None)

    case3 = [p for p in nolink["positions"] if p["exit_reason"] == "Signal"]
    check("case 3: historical run still reports exit_reason Signal", bool(case3))
    check("case 3: historical Signal close has closing_order null",
          case3 and call_sync(params, "get_position",
                              {"run": "nolink",
                               "position_id": case3[0]["position_id"]})[1]["position"]["closing_order"]
          is None)
    check("case 3: historical close carries no closing_order_seq",
          case3 and case3[0]["closing_order_seq"] is None)

    check("UUIDv4 historical run is fully readable", uuidv4["count"] == 48, uuidv4["count"])
    check("historical ids keep UUID version 4",
          all(uuid.UUID(p["position_id"]).version == 4 for p in uuidv4["positions"]))

    check("strategy reasons are visible through list_events",
          reasons["events"] and any("signals" in e for e in reasons["events"])
          and any(s.get("reason") for e in reasons["events"]
                  for s in e.get("signals") or []), reasons["events"][:1])
    check("a pre-SCHEMA-01 run exposes no signals key",
          noreasons["events"] and all("signals" not in e for e in noreasons["events"]),
          noreasons["events"][:1])

    check("failed run reports status failed with metrics null",
          failed["summary"]["status"] == "failed" and failed["summary"]["metrics"] is None,
          failed["summary"]["status"])
    check("failed run serves its partial (empty) trade history",
          failed_trades["trades"] == [])
    check("dataset unavailable: ohlc null and flagged unavailable",
          no_ohlc["bar"]["ohlc"] is None and no_ohlc["bar"]["ohlc_available"] is False)
    check("dataset unavailable: canonical events still served",
          no_ohlc_events["total"] == 4862, no_ohlc_events["total"])
    check("strategy source removed: run remains inspectable",
          isinstance(gone.get("count"), int), gone)

    check("malformed artifacts map to RUN_ARTIFACTS_INVALID",
          broken["error"]["code"] == "RUN_ARTIFACTS_INVALID", broken)
    check("a malformed-artifact error discloses no absolute path",
          root not in json.dumps(broken)
          and not str(broken["error"]["details"].get("path", "")).startswith("/"),
          broken["error"])
    check("EVENT_NOT_FOUND carries details",
          missing_event["error"]["code"] == "EVENT_NOT_FOUND"
          and missing_event["error"]["details"] == {"event_seq": 999999}, missing_event)
    check("BAR_NOT_FOUND carries details",
          missing_bar["error"]["code"] == "BAR_NOT_FOUND"
          and missing_bar["error"]["details"] == {"bar_index": 999999}, missing_bar)
    check("POSITION_NOT_FOUND is reported",
          missing_pos["error"]["code"] == "POSITION_NOT_FOUND", missing_pos)
    check("ORDER_NOT_FOUND is reported",
          missing_order["error"]["code"] == "ORDER_NOT_FOUND", missing_order)


def test_read_only_and_determinism(root):
    params = server_params(root)
    persisted = observa.inspect_run(os.path.join(root, "canonical"))
    pid = persisted.positions(open=False)[0]["position_id"]
    requests = [
        ("list_runs", {}),
        ("get_run_summary", {"run": "canonical"}),
        ("list_events", {"run": "canonical", "limit": 50}),
        ("get_event", {"run": "canonical", "event_seq": 0}),
        ("get_bar", {"run": "canonical", "bar_index": 100}),
        ("list_positions", {"run": "canonical"}),
        ("get_position", {"run": "canonical", "position_id": pid}),
        ("list_trades", {"run": "canonical"}),
        ("list_rejections", {"run": "canonical"}),
    ]
    before = sha_tree(root)
    first = [p for _r, p in calls_sync(params, requests)]
    second = [p for _r, p in calls_sync(params, requests)]
    after = sha_tree(root)

    check("a full tool sweep writes nothing into any run directory",
          before == after,
          sorted(set(before) ^ set(after)) or
          [k for k in before if before[k] != after.get(k)][:3])
    check("repeated identical calls return identical payloads",
          json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True))


def test_concurrency(root):
    params = server_params(root)

    async def burst():
        async with Client(params) as client:
            return await asyncio.gather(*[
                client.call_tool("list_trades", {"run": "open_only"}) for _ in range(8)
            ])

    results = asyncio.run(asyncio.wait_for(burst(), timeout=180))
    decoded = [json.loads(r.content[0].text) for r in results]
    check("eight concurrent calls all succeed",
          len(decoded) == 8 and all(isinstance(d, dict) for d in decoded), len(decoded))
    check("concurrent calls agree on one deterministic payload",
          len({json.dumps(d, sort_keys=True) for d in decoded}) == 1)
    check("no concurrent call returns an error envelope",
          all("error" not in d for d in decoded))


def test_stdout_protocol_cleanliness(tmp, root):
    """Every server stdout line must be valid JSON-RPC protocol output."""
    log_path = os.path.join(tmp, "stdout.log")
    proxy = (
        "import os, subprocess, sys, threading\n"
        "log = open(os.environ['MCP_STDOUT_LOG'], 'ab', buffering=0)\n"
        "p = subprocess.Popen([sys.executable, '-m', 'observa.mcp_server',\n"
        "                      '--runs-dir', os.environ['MCP_RUNS_DIR']],\n"
        "                     stdin=sys.stdin.buffer, stdout=subprocess.PIPE,\n"
        "                     stderr=sys.stderr, env=dict(os.environ))\n"
        "def pump():\n"
        "    for line in p.stdout:\n"
        "        log.write(line)\n"
        "        sys.stdout.buffer.write(line); sys.stdout.buffer.flush()\n"
        "threading.Thread(target=pump, daemon=True).start()\n"
        "p.wait()\n"
    )
    env = dict(os.environ, MCP_RUNS_DIR=root, MCP_STDOUT_LOG=log_path)
    tee = StdioServerParameters(command=sys.executable, args=["-c", proxy], env=env)

    async def go():
        async with Client(tee) as client:
            await client.list_tools()
            await client.call_tool("list_runs", {})
            await client.call_tool("list_trades", {"run": "canonical"})

    asyncio.run(asyncio.wait_for(go(), timeout=180))

    raw = open(log_path, "rb").read().decode("utf-8", "replace")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    check("the tee captured real protocol traffic on stdout", len(lines) >= 3, len(lines))
    bad = []
    parsed = 0
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            bad.append(line[:80])
            continue
        if isinstance(msg, dict) and "jsonrpc" in msg:
            parsed += 1
        else:
            bad.append(line[:80])
    check("every stdout line is valid JSON-RPC", not bad, bad[:3])
    check("every stdout line is a protocol message", parsed == len(lines), (parsed, len(lines)))
    check("no human/diagnostic text leaked to stdout",
          not any(m in raw for m in ("Observa MCP", "Runs root:", "Tools:")), raw[:160])


def test_startup_stderr_and_cli(tmp, root):
    proc = subprocess.run(
        [sys.executable, "-m", "observa.mcp_server", "--runs-dir", root],
        input=b"", capture_output=True, timeout=120,
    )
    check("banner goes to stderr with root and tool count",
          b"Observa MCP" in proc.stderr and b"Runs root:" in proc.stderr
          and b"Tools: 13 (10 inspection, 3 authoring)" in proc.stderr, proc.stderr[:200])
    check("nothing is written to stdout at startup", proc.stdout == b"", proc.stdout[:120])
    check("the banner does not leak the dataset path",
          b"canonical_m15.csv" not in proc.stderr)

    absent = os.path.join(tmp, "does_not_exist")
    missing = subprocess.run(
        [sys.executable, "-m", "observa.mcp_server", "--runs-dir", absent],
        input=b"", capture_output=True, timeout=120)
    check("a nonexistent runs root still starts the server (OBS-AI-05)",
          missing.returncode == 0 and b"Observa MCP" in missing.stderr
          and b"Tools: 13" in missing.stderr, missing.stderr[:200])
    check("a nonexistent runs root produces no traceback",
          b"Traceback" not in missing.stderr)
    check("a nonexistent runs root is never created",
          not os.path.exists(absent), absent)

    bogus = subprocess.run([sys.executable, "-m", "observa.mcp_server", "--runs-dir", root,
                            "--bogus"], capture_output=True, timeout=120)
    check("an unknown argument exits 2 with usage",
          bogus.returncode == 2 and b"usage" in bogus.stderr.lower(), bogus.stderr[:160])

    helped = subprocess.run([sys.executable, "-m", "observa.mcp_server", "--help"],
                            capture_output=True, timeout=120)
    check("--help exits 0, usage on stderr, stdout clean",
          helped.returncode == 0 and b"usage" in helped.stderr.lower()
          and helped.stdout == b"", helped.stderr[:120])

    cli = subprocess.run(
        [sys.executable, "-c",
         "import sys; from observa.cli import main; "
         "sys.exit(main(['mcp', '--runs-dir', %r, '--help']))" % root],
        capture_output=True, timeout=120)
    check("observa mcp --help works through the console-script path",
          cli.returncode == 0 and b"usage" in cli.stderr.lower(), cli.returncode)


def test_import_isolation():
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys, observa, observa.cli; "
         "heavy=[m for m in sys.modules if m.split('.')[0] in "
         "('mcp','pydantic','starlette','uvicorn','httpx2','anyio','jsonschema')]; "
         "print('HEAVY', heavy); print('MCP', 'mcp' in sys.modules)"],
        capture_output=True, text=True, timeout=120)
    check("import observa and observa.cli pull in no MCP stack",
          proc.returncode == 0 and "HEAVY []" in proc.stdout and "MCP False" in proc.stdout,
          proc.stdout + proc.stderr[-200:])
    check("the mcp_server module imports without loading mcp eagerly",
          hasattr(mcp_server, "build_server"))
    check("mcp_server exposes exactly the thirteen tool functions",
          {fn.__name__ for fn in mcp_server._TOOL_FUNCTIONS} == EXPECTED_TOOLS,
          sorted(fn.__name__ for fn in mcp_server._TOOL_FUNCTIONS))
    check("the module's name tuples partition the surface exactly",
          set(mcp_server.INSPECTION_TOOL_NAMES) == INSPECTION_TOOLS
          and set(mcp_server.AUTHORING_TOOL_NAMES) == AUTHORING_TOOLS
          and mcp_server.TOOL_NAMES
          == mcp_server.INSPECTION_TOOL_NAMES + mcp_server.AUTHORING_TOOL_NAMES,
          (sorted(mcp_server.INSPECTION_TOOL_NAMES),
           sorted(mcp_server.AUTHORING_TOOL_NAMES), mcp_server.TOOL_NAMES))


def test_cache_semantics(root):
    """Cache behaviour that is deliberately invisible from the wire."""
    root = os.path.realpath(root)
    mcp_server._reset_cache()
    mcp_server.configure(root)

    listing = mcp_server.list_runs()
    check("list_runs does not populate the run cache",
          isinstance(listing, dict) and len(mcp_server._CACHE) == 0,
          len(mcp_server._CACHE))

    calls = {"n": 0}
    real = mcp_server.inspect_run

    def counting(path):
        calls["n"] += 1
        return real(path)

    mcp_server.inspect_run = counting
    try:
        mcp_server._reset_cache()
        mcp_server.configure(root)
        mcp_server.list_runs()
        check("list_runs never instantiates a PersistedRun", calls["n"] == 0, calls["n"])

        mcp_server._reset_cache()
        mcp_server.configure(root)
        _rel, first = mcp_server._load_run("canonical")
        _rel, second = mcp_server._load_run("canonical")
        check("a repeated load is served from the cache", calls["n"] == 1, calls["n"])
        check("the cached instance is reused, not rebuilt", first is second)

        mcp_server._reset_cache()
        mcp_server.configure(root)
        calls["n"] = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            loaded = list(pool.map(lambda _i: mcp_server._load_run("canonical")[1], range(8)))
        check("eight concurrent loads instantiate exactly once", calls["n"] == 1, calls["n"])
        check("concurrent loads all receive one cached instance",
              len({id(x) for x in loaded}) == 1)
        check("exactly one cache entry exists after the burst",
              len(mcp_server._CACHE) == 1, len(mcp_server._CACHE))
    finally:
        mcp_server.inspect_run = real
        mcp_server._reset_cache()


def test_packaging_metadata():
    try:
        import importlib.metadata as md

        meta = md.distribution("observa").metadata
        requires = meta.get_all("Requires-Dist") or []
        extras = meta.get_all("Provides-Extra") or []
    except Exception as exc:  # noqa: BLE001
        check("installed distribution metadata is readable", False, exc)
        return
    unconditional = [r for r in requires if "extra ==" not in r]
    check("base wheel declares no unconditional dependency", unconditional == [], unconditional)
    check("the mcp extra is declared", "mcp" in extras, extras)
    check("the mcp extra is upper-bounded below 3",
          any("mcp" in r and "<3" in r for r in requires), requires)


# ── OBS-AI-05: authoring discovery ───────────────────────────────────────


AUTHORING_REQUESTS = [
    ("get_strategy_contract", {}),
    ("get_strategy_example", {}),
    ("get_strategy_guide", {}),
]


def test_authoring_discovery(params):
    """Exact contract/example/guide fidelity, envelope shape and determinism."""
    results = calls_sync(params, AUTHORING_REQUESTS)
    (contract_r, contract), (example_r, example), (guide_r, guide) = results

    check("get_strategy_contract equals observa.agent_spec() exactly",
          contract == observa.agent_spec())
    check("get_strategy_contract carries strategy_api_version",
          contract.get("strategy_api_version") == observa.STRATEGY_API_VERSION == "1")
    check("get_strategy_contract carries observa_version",
          contract.get("observa_version") == observa.__version__)

    with open(observa.agent_example_path(), encoding="utf-8") as fh:
        example_text = fh.read()
    with open(observa.agent_guide_path(), encoding="utf-8") as fh:
        guide_text = fh.read()

    check("get_strategy_example source is the bundled example byte-for-byte",
          example.get("source") == example_text)
    check("get_strategy_example filename is the bundled basename",
          example.get("filename") == os.path.basename(observa.agent_example_path()))
    check("get_strategy_example declares strategy_api_version",
          example.get("strategy_api_version") == observa.STRATEGY_API_VERSION)

    check("get_strategy_guide source is the bundled guide byte-for-byte",
          guide.get("source") == guide_text)
    check("get_strategy_guide filename is the bundled basename",
          guide.get("filename") == os.path.basename(observa.agent_guide_path()))
    check("get_strategy_guide declares strategy_api_version",
          guide.get("strategy_api_version") == observa.STRATEGY_API_VERSION)

    blocks = {
        "get_strategy_contract": len(contract_r.content),
        "get_strategy_example": len(example_r.content),
        "get_strategy_guide": len(guide_r.content),
    }
    check("each authoring tool returns exactly one content block",
          all(v == 1 for v in blocks.values()), blocks)
    shapes = {"contract": type(contract).__name__, "example": type(example).__name__,
              "guide": type(guide).__name__}
    check("every authoring response is object-rooted",
          all(v == "dict" for v in shapes.values()), shapes)
    check("no authoring response is an error envelope",
          not any("error" in p for p in (contract, example, guide)))

    check("the contract is returned in full, not paginated or truncated",
          len(contract_r.content[0].text) > 9000, len(contract_r.content[0].text))
    check("the example is small enough for a single response",
          2000 < len(example_r.content[0].text) < 20000, len(example_r.content[0].text))
    check("the guide is small enough for a single response",
          2000 < len(guide_r.content[0].text) < 20000, len(guide_r.content[0].text))

    check("authoring responses leak no absolute filesystem paths",
          "/site-packages/" not in json.dumps([example, guide])
          and not os.path.isabs(example.get("filename", ""))
          and not os.path.isabs(guide.get("filename", "")))

    again = [p for _r, p in calls_sync(params, AUTHORING_REQUESTS)]
    check("repeated authoring calls are JSON-identical",
          json.dumps([contract, example, guide], sort_keys=True)
          == json.dumps(again, sort_keys=True))


def test_authoring_no_execution(tmp):
    """Authoring discovery reads two bundled assets and executes nothing."""
    check("mcp_server does not import validate_strategy",
          not hasattr(mcp_server, "validate_strategy"))

    referenced = set()
    for fn in (mcp_server.get_strategy_contract, mcp_server.get_strategy_example,
               mcp_server.get_strategy_guide):
        referenced |= set(fn.__code__.co_names)
    banned = {"validate_strategy", "exec_module", "spec_from_file_location",
              "import_module", "on_bar", "inspect_run", "Popen", "run"}
    check("authoring tools reference no execution machinery",
          not (referenced & banned), sorted(referenced & banned))

    absent = os.path.join(tmp, "ai05-probe-root")
    if os.path.exists(absent):
        shutil.rmtree(absent)
    mcp_server._reset_cache()
    mcp_server.configure(absent)

    real_open = builtins.open
    opened = []

    def spy(file, *a, **k):
        try:
            opened.append(os.fspath(file))
        except TypeError:
            opened.append(repr(file))
        return real_open(file, *a, **k)

    builtins.open = spy
    try:
        mcp_server.get_strategy_contract()
        mcp_server.get_strategy_example()
        mcp_server.get_strategy_guide()
    finally:
        builtins.open = real_open
        mcp_server._reset_cache()

    expected_files = {mcp_server.agent_example_path(), mcp_server.agent_guide_path()}
    check("authoring discovery reads exactly the two bundled assets",
          set(opened) == expected_files, sorted(set(opened)))
    check("no strategy module was opened or imported",
          not any(p.endswith(("strategy.py", ".pyc")) and p not in expected_files
                  for p in opened), sorted(set(opened)))


def test_authoring_read_only(tmp):
    """A full authoring sweep must create and modify nothing."""
    absent = os.path.join(tmp, "ai05-absent-root")
    if os.path.exists(absent):
        shutil.rmtree(absent)
    before = sha_tree(tmp)
    calls_sync(server_params(absent), AUTHORING_REQUESTS)
    after = sha_tree(tmp)
    check("an authoring sweep writes nothing",
          before == after,
          sorted(set(before) ^ set(after)) or
          [k for k in before if before[k] != after.get(k)][:3])
    check("an authoring sweep never creates the configured runs root",
          not os.path.exists(absent), absent)


def test_authoring_offline(tmp):
    """Authoring discovery works with sockets unavailable."""
    bootstrap = (
        "import socket, sys\n"
        "_real = socket.socket\n"
        "class _Guarded(_real):\n"
        "    def connect(self, address):\n"
        "        if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "            raise OSError('OBS-AI-05: network disabled')\n"
        "        return _real.connect(self, address)\n"
        "    def connect_ex(self, address):\n"
        "        if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "            raise OSError('OBS-AI-05: network disabled')\n"
        "        return _real.connect_ex(self, address)\n"
        "def _blocked(*a, **k):\n"
        "    raise OSError('OBS-AI-05: network disabled')\n"
        "socket.socket = _Guarded\n"
        "socket.create_connection = _blocked\n"
        "socket.getaddrinfo = _blocked\n"
        "from observa.mcp_server import main\n"
        "sys.exit(main(['--runs-dir', sys.argv[1]]))\n"
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", bootstrap, os.path.join(tmp, "ai05-offline-root")],
        env=dict(os.environ),
    )
    try:
        results = calls_sync(params, AUTHORING_REQUESTS, timeout=180)
    except Exception as exc:  # noqa: BLE001
        check("authoring discovery succeeds with sockets blocked", False, repr(exc))
        return
    payloads = [p for _r, p in results]
    check("authoring discovery succeeds with sockets blocked",
          all(isinstance(p, dict) and "error" not in p for p in payloads))
    check("offline contract matches observa.agent_spec()",
          payloads[0] == observa.agent_spec())


def test_zero_run_ux(tmp):
    """The server starts with no runs root; authoring works, inspection is coded."""
    absent = os.path.join(tmp, "ai05-absent-root")
    if os.path.exists(absent):
        shutil.rmtree(absent)
    params = server_params(absent)

    async def go():
        async with Client(params) as client:
            return await client.list_tools()

    tools = asyncio.run(asyncio.wait_for(go(), timeout=180)).tools
    check("server starts with a nonexistent runs root",
          {t.name for t in tools} == EXPECTED_TOOLS, sorted(t.name for t in tools))
    check("a nonexistent runs root is not created at startup",
          not os.path.exists(absent), absent)

    payloads = [p for _r, p in calls_sync(params, AUTHORING_REQUESTS)]
    check("authoring tools work with a nonexistent runs root",
          all(isinstance(p, dict) and "error" not in p for p in payloads))

    _r, listing = call_sync(params, "list_runs", {})
    check("list_runs reports coded RUN_DIR_NOT_FOUND for an absent root",
          isinstance(listing, dict) and listing.get("error", {}).get("code") == "RUN_DIR_NOT_FOUND",
          listing)
    check("the absent-root error redacts the absolute path",
          listing["error"]["details"].get("runs_dir") == ""
          and os.path.sep not in listing["error"]["message"],
          listing["error"])

    _r, summary = call_sync(params, "get_run_summary", {"run": "canonical"})
    check("run-scoped inspection reports RUN_DIR_NOT_FOUND for an absent root",
          isinstance(summary, dict) and summary.get("error", {}).get("code") == "RUN_DIR_NOT_FOUND",
          summary)

    empty = os.path.join(tmp, "ai05-empty-root")
    os.makedirs(empty, exist_ok=True)
    eparams = server_params(empty)
    _r, elisting = call_sync(eparams, "list_runs", {})
    check("list_runs on an existing empty root returns an empty collection",
          elisting == {"count": 0, "runs": [], "errors": []}, elisting)
    epayloads = [p for _r, p in calls_sync(eparams, AUTHORING_REQUESTS)]
    check("authoring tools work with an existing empty runs root",
          all(isinstance(p, dict) and "error" not in p for p in epayloads))


def main():
    tmp = tempfile.mkdtemp(prefix="qa-mcp01-")
    started = time.time()
    try:
        root, _outside = build_runs(tmp)
        params = server_params(root)

        test_startup_and_tool_surface(params)
        test_list_runs(root)
        test_security(root)
        test_delegation(root)
        test_envelopes(root)
        test_pagination(root)
        test_history_and_errors(root)
        test_read_only_and_determinism(root)
        test_concurrency(root)
        test_stdout_protocol_cleanliness(tmp, root)
        test_startup_stderr_and_cli(tmp, root)
        test_import_isolation()
        test_cache_semantics(root)
        test_packaging_metadata()
        # OBS-AI-05
        test_authoring_discovery(params)
        test_authoring_no_execution(tmp)
        test_authoring_read_only(tmp)
        test_authoring_offline(tmp)
        test_zero_run_ux(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks passed, %d failed (%.1fs)"
          % (len(PASSED), len(FAILED), time.time() - started))
    if FAILED:
        print("FAILED:")
        for name in FAILED:
            print("  -", name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
