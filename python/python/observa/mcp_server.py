"""OBS-MCP-01 / OBS-AI-05 — read-only MCP server: run inspection + authoring discovery.

A **thin adapter** over :func:`observa.inspect_run`, :func:`observa.run_summary`
and the OBS-AI-04 bundled authoring assets. It exposes two read-only surfaces to
an MCP client:

* **run inspection** (10 tools) — canonical, already-persisted evidence;
* **authoring discovery** (3 tools) — the canonical strategy contract, the gold
  example and the authoring guide, exactly as bundled in the installed wheel.

It never runs a strategy, never imports user code, never validates a strategy,
never writes to a run directory, never reparses ``events.jsonl`` itself, never
reimplements chronology bucketing, never infers a closing order and never
interprets a strategy reason.

Start it with either form (stdio transport only)::

    observa mcp --runs-dir runs/
    python -m observa.mcp_server --runs-dir runs/

MCP support is part of the standard Observa install — no extra is needed::

    python -m pip install "<path-or-url-to-the-observa-wheel>"

Never install the bare PyPI name, which is an unrelated project.

Contracts this module guarantees
--------------------------------
* **stdio only.** No HTTP/SSE listener, no network socket. stdout carries
  *only* MCP protocol traffic; every human-facing line goes to stderr.
* **Read-only.** No tool creates, edits, deletes or writes anything. Returning
  artifacts byte-identical after a full tool sweep is a tested property.
* **Sandboxed.** Every ``run`` identifier is a path relative to one configured
  runs root. Absolute paths, ``..`` components, and anything that resolves
  outside the root are refused, and an escape is indistinguishable from a
  missing run (both report ``RUN_DIR_NOT_FOUND``), so the server never reveals
  whether a path outside the root exists.
* **Lazily rooted.** The configured runs root need not exist at startup, so an
  agent can discover how to author a strategy before any run has been persisted.
  The server never creates the directory. While the root is absent, authoring
  tools work normally and run-scoped inspection reports the coded
  ``RUN_DIR_NOT_FOUND``.
* **No execution.** Authoring discovery reads two fixed package-internal assets
  and the canonical contract. No tool takes a filesystem path, imports a strategy
  module, calls ``on_bar``, runs the Engine, or invokes
  :func:`observa.validate_strategy` (validation stays CLI/Python-only).
* **Object envelopes.** Every tool returns a JSON object — never a bare list —
  so a result arrives as one structured payload rather than one content block
  per element.
* **Anticipated failures are data.** Coded Observa errors are *returned* as
  ``{"error": {"code", "message", "details"}}`` so the code and details survive;
  the MCP protocol has no structured error channel of its own. Unexpected
  exceptions propagate and become real MCP tool errors, so genuine bugs stay
  visible instead of masquerading as domain failures.
* **No absolute filesystem paths** are exposed: path-shaped fields are reduced
  to basenames.
* **Immutable runs.** Loaded runs are cached for the process lifetime with no
  invalidation. Restart the server to observe artifact changes.

Historical compatibility is inherited from :class:`observa.PersistedRun`; this
module adds no schema requirement of its own.
"""

from __future__ import annotations

import functools
import json
import os
import sys
import threading

from . import (
    STRATEGY_API_VERSION,
    agent_example_path,
    agent_guide_path,
    agent_spec,
    run_summary,
)
from .errors import ERROR_CODES, coded
from .inspection import PersistedRun, inspect_run

#: The ten persisted-run inspection tools, in registration order. OBS-AI-05 adds
#: nothing here and changes nothing here.
INSPECTION_TOOL_NAMES = (
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
)

#: The three read-only authoring-discovery tools (OBS-AI-05), in registration
#: order. They read the OBS-AI-04 bundled assets and never execute user code.
AUTHORING_TOOL_NAMES = (
    "get_strategy_contract",
    "get_strategy_example",
    "get_strategy_guide",
)

#: The complete tool surface, in registration order.
TOOL_NAMES = INSPECTION_TOOL_NAMES + AUTHORING_TOOL_NAMES

#: Errors this adapter anticipates and reports as structured data. Anything
#: outside this set is a bug or an environmental failure and must propagate.
_ANTICIPATED_CODES = frozenset(
    code
    for code in ERROR_CODES
    if code
    in (
        "RUN_DIR_NOT_FOUND",
        "RUN_ARTIFACTS_INVALID",
        "EVENT_NOT_FOUND",
        "BAR_NOT_FOUND",
        "POSITION_NOT_FOUND",
        "ORDER_NOT_FOUND",
    )
)

#: Pagination bounds for ``list_events``.
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

#: How deep ``list_runs`` will search below the runs root. Bounded so a large
#: or accidental tree cannot turn discovery into a full filesystem walk.
MAX_SCAN_DEPTH = 3

_MISSING_EXTRA_HINT = (
    "error: MCP support is included with Observa, but its dependency could not "
    "be loaded.\n"
    "hint: this installation looks incomplete. Reinstall the official Observa "
    "release —\n"
    "      one install provides replay, strategy validation and MCP support.\n"
    "      See the install instructions in README.md (official GitHub Release "
    "wheel).\n"
    "      Do not run `pip install observa`; that PyPI project is unrelated."
)

USAGE = "usage: observa mcp --runs-dir <path>  (stdio transport)"

# ── process-local state ──────────────────────────────────────────

#: Resolved runs root. Set once by :func:`configure`; never a per-run selection.
_RUNS_ROOT: str | None = None

#: ``resolved_run_path -> PersistedRun``. Lazy, never invalidated (runs are
#: immutable). ``list_runs`` deliberately never touches this.
_CACHE: dict[str, PersistedRun] = {}

#: MCP v2 may execute synchronous tools on worker threads, so the cache needs
#: real mutual exclusion — the GIL is not a synchronization policy.
_CACHE_LOCK = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────


def _coded(exc_type, message, code, details=None):
    """Builds an exception carrying Observa's ``code``/``details`` attributes.

    Thin wrapper over :func:`observa.errors.coded` so the adapter reuses the
    project's existing coded-error convention rather than inventing a second one.
    """
    return coded(exc_type(message), code, details)


def _denied(run):
    """The single external failure for every unacceptable ``run`` identifier.

    Escapes, absolutes, ``..`` traversal, empties and genuinely missing runs all
    produce this exact error, so an external caller cannot tell whether a path
    outside the root exists.
    """
    return coded(
        FileNotFoundError(
            "no persisted Observa run at %r under the configured runs root" % (run,)
        ),
        "RUN_DIR_NOT_FOUND",
        {"run": run},
    )


def _error_payload(exc):
    """Wraps an anticipated coded error as the documented error envelope.

    Path-bearing detail values are reduced to basenames: ``run_summary`` and
    ``inspect_run`` report absolute artifact paths in their ``details``, and the
    server does not disclose the operator's filesystem layout.
    """
    return {
        "error": {
            "code": getattr(exc, "code", None),
            "message": _redact_message(str(exc)),
            "details": _sanitise_details(getattr(exc, "details", None)),
        }
    }


def _guard(fn):
    """Converts anticipated coded errors into the structured error envelope.

    Only errors carrying a known Observa ``code`` are converted; every other
    exception propagates unchanged (see the module docstring). ``functools.wraps``
    keeps the tool's name, docstring and type signature, which is what the MCP
    SDK turns into the tool schema.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised unless anticipated
            code = getattr(exc, "code", None)
            if isinstance(code, str) and code in _ANTICIPATED_CODES:
                return _error_payload(exc)
            raise

    return wrapper


def _basename(value):
    """Reduces a persisted path to its basename (``None`` passes through).

    Paths recorded at run time are absolute and may point outside the runs
    root; the server does not disclose the operator's filesystem layout.
    """
    if not isinstance(value, str) or not value:
        return value
    return os.path.basename(value.rstrip("/\\")) or value


#: Detail keys that carry filesystem paths and must never be echoed verbatim.
_PATH_DETAIL_KEYS = ("path", "runs_dir", "artifact_dir", "dataset_source")


def _redact_path(value):
    """Makes an in-root path run-relative; other absolute paths lose the directory.

    ``run_summary`` and ``inspect_run`` report absolute artifact paths, and the
    server does not disclose the operator's filesystem layout. A path under the
    configured runs root keeps its meaning (``broken/run.json``); anything else
    absolute is reduced to a basename.
    """
    if not isinstance(value, str) or not value:
        return value
    root = _RUNS_ROOT
    if root:
        if value == root:
            return ""
        prefix = root + os.sep
        if value.startswith(prefix):
            return value[len(prefix):]
    return _basename(value) if os.path.isabs(value) else value


def _redact_message(message):
    """Removes the absolute runs root from a human-readable error message."""
    if not isinstance(message, str) or not _RUNS_ROOT:
        return message
    return message.replace(_RUNS_ROOT + os.sep, "").replace(_RUNS_ROOT, "")


def _sanitise_details(details):
    """Returns ``details`` with path-bearing values made root-relative."""
    out = {}
    for key, value in (details or {}).items():
        out[key] = _redact_path(value) if key in _PATH_DETAIL_KEYS else value
    return out


def _read_strategy_name(run_json_path):
    """Best-effort ``strategy.name`` from a run description (``None`` if absent)."""
    try:
        with open(run_json_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    name = (doc.get("strategy") or {}).get("name")
    return name if isinstance(name, str) else None


def configure(runs_dir):
    """Resolves and records the configured runs root; returns it.

    **Existence is validated lazily, not here.** The path is resolved with
    ``realpath`` and stored even when it does not (yet) exist, so the server can
    start — and authoring discovery can serve — before any run has been
    persisted. The directory is *never* created.

    A missing root is not an escape hatch: :func:`resolve_run` still refuses
    anything that does not sit under the resolved root and does not contain a
    ``run.json``, and :func:`list_runs` reports the coded ``RUN_DIR_NOT_FOUND``.
    The only argument rejected here is a missing/empty value, which is a usage
    error rather than a filesystem condition.
    """
    global _RUNS_ROOT

    if not isinstance(runs_dir, (str, os.PathLike)) or not os.fspath(runs_dir):
        raise _coded(
            FileNotFoundError,
            "a runs directory is required (%s)" % USAGE,
            "RUN_DIR_NOT_FOUND",
            {"runs_dir": runs_dir},
        )
    resolved = os.path.realpath(os.path.abspath(os.fspath(runs_dir)))
    with _CACHE_LOCK:
        _RUNS_ROOT = resolved
    return resolved


def _runs_root():
    if _RUNS_ROOT is None:
        raise _coded(
            RuntimeError,
            "the MCP server has no configured runs root",
            "RUN_DIR_NOT_FOUND",
            {},
        )
    return _RUNS_ROOT


def _missing_root(root):
    """The coded error for a configured runs root that is absent/unusable."""
    return _coded(
        FileNotFoundError,
        "runs directory does not exist or is not a directory: %s" % root,
        "RUN_DIR_NOT_FOUND",
        {"runs_dir": root},
    )


def resolve_run(run):
    """Maps a ``run`` identifier to ``(relative_id, absolute_dir)``.

    Policy, in order: reject non-strings, empties and absolute paths; reject any
    ``..`` component *before* touching the filesystem; join under the root;
    resolve symlinks; require the result to remain inside the resolved root; and
    require a ``run.json``. Every rejection raises the same error as a missing
    run.
    """
    root = _runs_root()

    if not isinstance(run, str) or not run:
        raise _denied(run)
    if os.path.isabs(run):
        raise _denied(run)

    parts = [p for p in run.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise _denied(run)

    candidate = os.path.realpath(os.path.join(root, *parts))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise _denied(run)
    if not os.path.isdir(candidate):
        raise _denied(run)
    if not os.path.isfile(os.path.join(candidate, "run.json")):
        raise _denied(run)

    return os.path.relpath(candidate, root), candidate


def _load_run(run):
    """Returns ``(relative_id, PersistedRun)`` using the process-local cache.

    The whole get-or-create runs under the cache lock so concurrent first
    accesses load exactly once.
    """
    rel, path = resolve_run(run)
    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        if cached is None:
            cached = inspect_run(path)
            _CACHE[path] = cached
    return rel, cached


def _reset_cache():
    """Test-support: drops the cache and the configured root."""
    global _RUNS_ROOT
    with _CACHE_LOCK:
        _CACHE.clear()
        _RUNS_ROOT = None


def _effective_limit(limit):
    """Clamps ``limit`` into ``[1, MAX_LIMIT]`` (``DEFAULT_LIMIT`` if unusable)."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _iter_run_dirs(root):
    """Yields ``(relative_id, absolute_dir)`` for discoverable persisted runs.

    Deterministic (name-sorted), depth-bounded, skips hidden directories, never
    leaves the root, and does not descend into a directory once it is known to
    be a run. A directory reachable under two names (via a symlink inside the
    root) is yielded once.
    """
    seen = set()
    queue = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=True)
            except OSError:
                continue
            if not is_dir:
                continue

            real = os.path.realpath(entry.path)
            if real != root and not real.startswith(root + os.sep):
                continue  # would escape the runs root
            if not os.path.isfile(os.path.join(real, "run.json")):
                if depth + 1 < MAX_SCAN_DEPTH:
                    queue.append((real, depth + 1))
                continue
            if real in seen:
                continue
            seen.add(real)
            try:
                rel = os.path.relpath(entry.path, root)
            except ValueError:  # pragma: no cover - different drives (Windows)
                continue
            yield rel, real


# ── tools ────────────────────────────────────────────────────────


def list_runs():
    """List persisted Observa runs under the configured runs root.

    Discovery is intentionally cheap: it reads only ``run.json`` and, when
    present, ``metrics.json`` — it never loads event histories and never
    populates the run cache. Directories without a ``run.json`` are ignored;
    directories with unusable artifacts are reported in ``errors`` instead of
    failing the whole listing. Paths are reduced to basenames.
    """
    root = _runs_root()
    if not os.path.isdir(root):
        # Lazy root (OBS-AI-05): a configured-but-absent root is reported as the
        # existing coded error rather than silently as an empty run collection.
        raise _missing_root(root)
    runs = []
    errors = []
    for rel, path in _iter_run_dirs(root):
        try:
            summary = run_summary(path)
        except Exception as exc:  # noqa: BLE001 - reported per entry
            code = getattr(exc, "code", None)
            if not (isinstance(code, str) and code in _ANTICIPATED_CODES):
                raise
            errors.append({"run": rel, "error": _error_payload(exc)["error"]})
            continue
        runs.append(
            {
                "run": rel,
                "status": summary.get("status"),
                "strategy": _read_strategy_name(os.path.join(path, "run.json")),
                "bar_count": summary.get("total_bars"),
                "event_count": summary.get("events"),
                "trades": summary.get("trades"),
                "open_positions": summary.get("open_positions"),
                "final_balance": summary.get("final_balance"),
                "final_equity": summary.get("final_equity"),
                "run_schema_version": summary.get("run_schema_version"),
                "dataset": _basename(summary.get("dataset_source")),
            }
        )
    return {"count": len(runs), "runs": runs, "errors": errors}


def get_run_summary(run: str):
    """Summarise one persisted run from its artifacts (never re-runs it).

    Returns the persisted ``run.json``/``metrics.json`` facts via
    :func:`observa.run_summary`, with path-shaped fields reduced to basenames.
    ``metrics`` is ``null`` for failed runs.
    """
    rel, path = resolve_run(run)
    summary = run_summary(path)
    summary["artifact_dir"] = _basename(summary.get("artifact_dir"))
    summary["dataset_source"] = _basename(summary.get("dataset_source"))
    return {"run": rel, "summary": summary}


def list_events(
    run: str,
    event_type: str | None = None,
    event_seq: int | None = None,
    bar_index: int | None = None,
    position_id: str | None = None,
    order_seq: int | None = None,
    start_event_seq: int | None = None,
    end_event_seq: int | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: int | None = None,
):
    """List canonical events for one run, filtered and paginated.

    Filters have AND semantics and map 1:1 onto :meth:`PersistedRun.events`, so
    ``bar_index`` uses canonical chronology-bucket attribution and the result is
    always in ascending ``event_seq`` order.

    ``limit`` is clamped to 1..1000 (the effective value is echoed back).
    ``cursor`` means "start strictly after this event_seq" — the canonical
    ordering key, so pages are deterministic and cannot skip or duplicate
    events. ``total`` counts everything matching the filters *ignoring* the
    cursor. When the page is truncated, ``next_cursor`` is the last returned
    ``event_seq``; it is ``null`` when the result is complete, so truncation is
    never silent.
    """
    rel, persisted = _load_run(run)
    effective = _effective_limit(limit)

    matched = persisted.events(
        event_type=event_type,
        event_seq=event_seq,
        bar_index=bar_index,
        position_id=position_id,
        order_seq=order_seq,
        start_event_seq=start_event_seq,
        end_event_seq=end_event_seq,
    )
    total = len(matched)

    if cursor is not None:
        if isinstance(cursor, bool) or not isinstance(cursor, int):
            raise TypeError("cursor must be an int, got %s" % type(cursor).__name__)
        matched = [e for e in matched if isinstance(e.get("event_seq"), int) and e["event_seq"] > cursor]

    page = matched[:effective]
    next_cursor = None
    if page and len(matched) > len(page):
        next_cursor = page[-1]["event_seq"]

    return {
        "run": rel,
        "total": total,
        "returned": len(page),
        "limit": effective,
        "next_cursor": next_cursor,
        "events": page,
    }


def get_event(run: str, event_seq: int):
    """Return exactly one canonical event as persisted."""
    rel, persisted = _load_run(run)
    return {"run": rel, "event": persisted.event(event_seq)}


def get_bar(run: str, bar_index: int):
    """Return everything canonical the run recorded for one bar.

    Includes strategy decisions (with their persisted per-signal reasons),
    drawings, order and position activity, and the bar's portfolio snapshot.
    ``ohlc`` is ``null`` with ``ohlc_available == false`` when the dataset can
    no longer be verified against its persisted hash — no bar is ever
    fabricated.
    """
    rel, persisted = _load_run(run)
    return {"run": rel, "bar": persisted.bar(bar_index)}


def list_positions(run: str, open: bool | None = None):
    """List a run's position summaries (canonical order).

    ``open`` selects all (``null``), only open (``true``) or only closed
    (``false``) positions. Each summary carries ``opening_order_seq`` and
    ``closing_order_seq``.
    """
    rel, persisted = _load_run(run)
    positions = persisted.positions(open=open)
    return {"run": rel, "count": len(positions), "positions": positions}


def get_position(run: str, position_id: str):
    """Return one position's exact canonical lifecycle.

    ``opening_order`` and ``closing_order`` are the recovered order lifecycles,
    and ``annotations_at_entry``/``annotations_at_exit`` carry the drawings
    visible at those bars.

    ``closing_order`` is three-valued and the distinction matters:

    * a dict with ``exit_reason == "Signal"`` — the exact canonical order that
      closed the position was recorded;
    * ``null`` with ``exit_reason`` ``"StopLoss"``/``"TakeProfit"`` — a
      protective exit; no order ever existed;
    * ``null`` with ``exit_reason == "Signal"`` — the run predates the
      closing-order linkage; it was not recorded.

    It is never inferred from side, quantity, timestamp, adjacency or the
    opening order, and a ``null`` is never re-derived.
    """
    rel, persisted = _load_run(run)
    return {"run": rel, "position": persisted.position(position_id)}


def get_order(run: str, order_seq: int):
    """Return one order's canonical lifecycle.

    ``position_id`` is the position this order **opened or closed**, whichever
    the persisted linkage records; it is ``null`` when the order was rejected or
    never linked to a position. Rejection ``category``/``reason`` are returned
    verbatim.
    """
    rel, persisted = _load_run(run)
    return {"run": rel, "order": persisted.order(order_seq)}


def list_trades(run: str):
    """List completed canonical trades, exactly as persisted.

    The trade shape is identical to ``RunResult.trades``; no value is
    recalculated and nothing is added.
    """
    rel, persisted = _load_run(run)
    trades = persisted.trades()
    return {"run": rel, "count": len(trades), "trades": trades}


def list_rejections(run: str):
    """List rejected orders joined with the parameters ``order_rejected`` lacks.

    Supplies the order's type, side, quantity and creation bar alongside the
    canonical rejection category and reason. Nothing is interpreted or reworded.
    """
    rel, persisted = _load_run(run)
    rejections = persisted.rejections()
    return {"run": rel, "count": len(rejections), "rejections": rejections}


# ── authoring discovery tools (OBS-AI-05) ────────────────────────


def _read_asset(path):
    """Returns the exact UTF-8 text of one bundled package asset.

    These assets are package invariants (OBS-AI-04), not user input, so a failure
    here is an installation/packaging defect. It is deliberately allowed to
    propagate as a real MCP tool error rather than being disguised as a domain
    error — the module docstring's "expected failures are data, bugs stay
    visible" rule applies unchanged.
    """
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def get_strategy_contract():
    """Return Observa's canonical machine-readable strategy-authoring contract."""
    # Delegated verbatim. agent_spec() returns a fresh deep copy and already
    # carries strategy_api_version and observa_version at top level, so wrapping
    # it would only duplicate those fields and imply a second contract.
    return agent_spec()


def get_strategy_example():
    """Return the bundled canonical Observa strategy example."""
    path = agent_example_path()
    return {
        "strategy_api_version": STRATEGY_API_VERSION,
        "filename": os.path.basename(path),
        "source": _read_asset(path),
    }


def get_strategy_guide():
    """Return the bundled concise strategy-authoring guide."""
    path = agent_guide_path()
    return {
        "strategy_api_version": STRATEGY_API_VERSION,
        "filename": os.path.basename(path),
        "source": _read_asset(path),
    }


#: Registration order is the order ``list_tools`` reports.
_TOOL_FUNCTIONS = (
    list_runs,
    get_run_summary,
    list_events,
    get_event,
    get_bar,
    list_positions,
    get_position,
    get_order,
    list_trades,
    list_rejections,
    get_strategy_contract,
    get_strategy_example,
    get_strategy_guide,
)


# ── server / entry point ─────────────────────────────────────────


def build_server():
    """Constructs the stdio MCP server with all thirteen tools registered.

    Imports the ``mcp`` dependency lazily so that importing this module (and
    therefore ``observa.cli``) never initializes MCP. MCP ships with the wheel,
    but ordinary backtesting must not touch it.
    """
    try:
        from mcp.server import MCPServer
    except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
        raise ModuleNotFoundError(_MISSING_EXTRA_HINT) from exc

    server = MCPServer("observa")
    for fn in _TOOL_FUNCTIONS:
        server.add_tool(_guard(fn))
    return server


def _parse_args(argv):
    """Returns ``(runs_dir, error_message)``; ``error_message`` is ``None`` on success."""
    runs_dir = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--runs-dir":
            i += 1
            if i >= len(argv):
                return None, "--runs-dir requires a value"
            runs_dir = argv[i]
        elif arg.startswith("--runs-dir="):
            runs_dir = arg.split("=", 1)[1]
        else:
            return None, "unknown argument %r" % (arg,)
        i += 1
    if not runs_dir:
        return None, "a runs directory is required"
    return runs_dir, None


def main(argv=None) -> int:
    """Runs the read-only MCP server over stdio. Returns a process exit code.

    All human-facing output goes to **stderr**: stdout belongs exclusively to
    the MCP protocol stream.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if any(a in ("-h", "--help", "help") for a in args):
        sys.stderr.write(USAGE + "\n")
        return 0

    runs_dir, problem = _parse_args(args)
    if problem is not None:
        sys.stderr.write("error: %s\n%s\n" % (problem, USAGE))
        return 2

    # Check the dependency first: if the MCP SDK is missing the installation is
    # incomplete, and that hint is the actionable message, whatever the runs
    # directory looks like.
    try:
        server = build_server()
    except ModuleNotFoundError:
        sys.stderr.write(_MISSING_EXTRA_HINT + "\n")
        return 2

    try:
        root = configure(runs_dir)
    except Exception as exc:  # noqa: BLE001 - concise coded startup failure
        code = getattr(exc, "code", None)
        sys.stderr.write(
            "error: %s%s\n" % (exc, " [%s]" % code if code else "")
        )
        return 2

    sys.stderr.write(
        "Observa MCP\nRuns root: %s\nTools: %d (%d inspection, %d authoring)\n"
        % (root, len(_TOOL_FUNCTIONS), len(INSPECTION_TOOL_NAMES), len(AUTHORING_TOOL_NAMES))
    )
    sys.stderr.flush()

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
