"""OBS-AI-03 — structured, read-only inspection of a persisted Observa run.

``observa.inspect_run(run_dir)`` opens an **existing** persisted run and returns
a :class:`PersistedRun` that answers structured questions about canonical
evidence without re-running the engine, importing the strategy, or parsing
``events.jsonl`` by hand.

Authority model
---------------
The persisted artifacts are authoritative and are the *only* input:

* ``run.json``      — run metadata (``run.meta``)
* ``events.jsonl``  — the canonical event history (everything else)
* ``metrics.json``  — derived metrics (``run.metrics``; ``None`` for failed runs)

Nothing here recomputes economics, and nothing here invents facts. Where the
canonical data does not contain something, the API returns ``None`` or ``[]``
rather than guessing. Two such gaps are documented in the module-level section
"Current canonical-data limitations" below.

No-rerun guarantee
------------------
Inspection never requires the original strategy code, never executes a strategy
and never writes to the run directory. It is usable by agents, CI and archived
research alike.

Result types
------------
Every public result is a freshly built ``dict``/``list`` of
``str``/``int``/``float``/``bool``/``None``, so results are JSON-serializable
and callers cannot mutate the inspector's internal indexes.

Current canonical-data limitations
----------------------------------
**G11 — strategy prose reason is not persisted.** ``StrategySignal.reason`` is
dropped by the engine: ``strategy_decision`` carries only ``signal_count`` and
``order_created`` carries no strategy reason. Persisted inspection therefore
cannot report *why* a strategy acted. No ``reason`` field is fabricated; the
only canonical reason text in the model belongs to ``order_rejected`` events and
is exposed verbatim by :meth:`PersistedRun.rejections` and
:meth:`PersistedRun.order`. A future schema ticket is needed.

**G12 — a position's closing order is not derivable.** ``position_closed``
carries no ``order_seq`` (only ``position_opened`` does), so
:meth:`PersistedRun.position` always reports ``closing_order = None``. It is
never inferred from side, quantity, timestamp, neighbouring events or bar
correlation.

Both are read-only limitations of the current event schema; OBS-AI-03 does not
change the schema.

Ordering
--------
Every event collection preserves ascending canonical ``event_seq``. Nothing is
sorted by UUID, by dict key, or by hash iteration. ``positions()`` is ordered by
the position's opening ``event_seq``.
"""

import json
import os

from .errors import coded

__all__ = ["PersistedRun", "inspect_run"]

#: Event types that belong to one order's lifecycle (all carry ``order_seq``).
_ORDER_EVENT_TYPES = (
    "order_created",
    "order_pending",
    "order_triggered",
    "order_filled",
    "order_rejected",
    "order_expired",
)

#: Maps an order event type to the lifecycle slot it fills.
_ORDER_SLOTS = {
    "order_created": "created",
    "order_pending": "pending",
    "order_triggered": "triggered",
    "order_filled": "filled",
    "order_rejected": "rejected",
    "order_expired": "expired",
}

#: Last-event-wins lifecycle state, matching the canonical replay reducer.
_ORDER_STATE = {
    "order_created": "created",
    "order_pending": "pending",
    "order_triggered": "triggered",
    "order_filled": "filled",
    "order_rejected": "rejected",
    "order_expired": "expired",
}

#: Filter name -> accepted Python types (``bool`` is rejected for int filters).
_FILTER_TYPES = {
    "event_type": (str,),
    "event_seq": (int,),
    "bar_index": (int,),
    "position_id": (str,),
    "order_seq": (int,),
    "start_event_seq": (int,),
    "end_event_seq": (int,),
}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_filter(name, value):
    expected = _FILTER_TYPES[name]
    if expected == (int,):
        if not _is_int(value):
            raise TypeError(
                "%s must be an int, got %s" % (name, type(value).__name__)
            )
    elif not isinstance(value, expected):
        raise TypeError(
            "%s must be %s, got %s"
            % (name, " or ".join(t.__name__ for t in expected), type(value).__name__)
        )


def inspect_run(run_dir):
    """Opens a persisted run for structured inspection.

    Parameters
    ----------
    run_dir:
        Path to a persisted run directory (``str`` or ``os.PathLike``) created by
        ``observa.run(..., output=dir)`` or ``result.save(dir)``.

    Returns
    -------
    PersistedRun

    Raises
    ------
    FileNotFoundError
        ``code == "RUN_DIR_NOT_FOUND"`` when the run directory or its
        ``run.json`` is missing.
    ValueError
        ``code == "RUN_ARTIFACTS_INVALID"`` when ``run.json``, ``events.jsonl``
        or ``metrics.json`` cannot be parsed.

    Examples
    --------
    >>> run = observa.inspect_run("runs/quickstart_20260918")   # doctest: +SKIP
    >>> run.meta["status"]                                      # doctest: +SKIP
    'completed'
    >>> len(run.trades())                                       # doctest: +SKIP
    47
    """
    return PersistedRun(run_dir)


class PersistedRun:
    """Read-only inspection surface over one persisted run directory.

    Construct with :func:`inspect_run`. The run is parsed once, eagerly, at
    construction time; four in-memory indexes are then built in a single pass.
    No database, sidecar index or persistent cache is used, and nothing is
    written to the run directory.
    """

    def __init__(self, run_dir):
        from . import _observa

        self._artifact_dir = os.path.abspath(os.fspath(run_dir))

        # Loading goes through the single canonical persisted-run loader. Its
        # replay-facing error codes are mapped onto the run-inspection codes so
        # that run *inspection* reports the same codes as run *summary*.
        try:
            payload = _observa.replay_payload(self._artifact_dir)
        except BaseException as exc:  # noqa: BLE001 - re-raised, mapped below
            code = getattr(exc, "code", None)
            details = dict(getattr(exc, "details", {}) or {})
            if code == "REPLAY_RUN_NOT_FOUND":
                raise coded(FileNotFoundError(str(exc)), "RUN_DIR_NOT_FOUND", details)
            if code == "REPLAY_ARTIFACTS_INVALID":
                raise coded(ValueError(str(exc)), "RUN_ARTIFACTS_INVALID", details)
            raise

        run_json_path = os.path.join(self._artifact_dir, "run.json")
        try:
            with open(run_json_path, "r", encoding="utf-8") as fh:
                self._meta = json.load(fh)
        except (OSError, ValueError) as exc:  # pragma: no cover - loader validated
            raise coded(
                ValueError("invalid run artifacts at %s: %s" % (run_json_path, exc)),
                "RUN_ARTIFACTS_INVALID",
                {"path": run_json_path},
            )

        self._metrics = payload.get("metrics")
        raw_events = payload.get("events") or []
        self._bars = list(payload.get("bars") or [])

        self._build_indexes(raw_events)

    # ── indexing ────────────────────────────────────────────────

    def _build_indexes(self, events):
        by_event_seq = {}
        by_bar = {}
        by_position = {}
        by_order = {}
        order_to_position = {}
        bar_order = []
        preamble = []
        current_bar = -1

        for event in events:
            seq = event.get("event_seq")
            if _is_int(seq):
                by_event_seq[seq] = event

            etype = event.get("type")

            # Canonical chronology-bucket attribution: every event belongs to
            # the bar whose `bar_processed` is currently open (the rule the
            # replay frontend uses). This is deliberately NOT a raw `bar_index`
            # field match — several event types carry no bar field at all, and
            # `order_created` stores it as `created_bar`.
            if etype == "bar_processed":
                bar_index = event.get("bar_index")
                if _is_int(bar_index):
                    current_bar = bar_index
                    if current_bar not in by_bar:
                        by_bar[current_bar] = []
                        bar_order.append(current_bar)
            if current_bar < 0:
                preamble.append(event)
            else:
                by_bar[current_bar].append(event)

            if etype in _ORDER_EVENT_TYPES:
                seq = event.get("order_seq")
                if _is_int(seq):
                    by_order.setdefault(seq, []).append(event)

            if etype == "position_opened":
                pid = event.get("position_id")
                if isinstance(pid, str):
                    record = by_position.setdefault(pid, {"events": []})
                    record["opened"] = event
                    record["events"].append(event)
                    seq = event.get("order_seq")
                    if _is_int(seq):
                        record["opening_order_seq"] = seq
                        order_to_position[seq] = pid
            elif etype == "position_closed":
                pid = event.get("position_id")
                if isinstance(pid, str):
                    record = by_position.setdefault(pid, {"events": []})
                    record["closed"] = event
                    record["events"].append(event)

        self._by_event_seq = by_event_seq
        self._by_bar = by_bar
        self._bar_order = bar_order
        self._preamble = preamble
        self._by_position = by_position
        self._by_order = by_order
        self._order_to_position = order_to_position
        self._events = events

    # ── run metadata ────────────────────────────────────────────

    @property
    def meta(self):
        """The persisted ``run.json`` as a plain dict (never recomputed)."""
        return json.loads(json.dumps(self._meta))

    @property
    def metrics(self):
        """The persisted ``metrics.json`` as a plain dict, or ``None``.

        ``None`` for failed runs, which intentionally have no ``metrics.json``.
        """
        if self._metrics is None:
            return None
        return json.loads(json.dumps(self._metrics))

    # ── events ──────────────────────────────────────────────────

    def events(
        self,
        event_type=None,
        event_seq=None,
        bar_index=None,
        position_id=None,
        order_seq=None,
        start_event_seq=None,
        end_event_seq=None,
    ):
        """Returns canonical events matching all supplied filters.

        Filters combine with AND semantics. The result always preserves
        ascending canonical ``event_seq`` order. No match returns ``[]`` (never
        ``None``); an unknown ``event_type`` therefore returns ``[]``.

        ``bar_index`` uses canonical chronology-bucket attribution, so it
        returns exactly the same events as ``bar(bar_index)["events"]``.

        ``position_id`` matches the events that carry that id
        (``position_opened`` / ``position_closed``). Canonical order events do
        not carry ``position_id``; use :meth:`position` for a full lifecycle.

        ``order_seq`` matches every event carrying that sequence, which includes
        the six order events and the ``position_opened`` opened by that order.

        Raises ``TypeError`` for a filter of the wrong type.
        """
        supplied = {
            "event_type": event_type,
            "event_seq": event_seq,
            "bar_index": bar_index,
            "position_id": position_id,
            "order_seq": order_seq,
            "start_event_seq": start_event_seq,
            "end_event_seq": end_event_seq,
        }
        for name, value in supplied.items():
            if value is not None:
                _check_filter(name, value)

        if bar_index is not None:
            candidates = self._by_bar.get(bar_index, [])
        else:
            candidates = self._events

        out = []
        for event in candidates:
            if event_type is not None and event.get("type") != event_type:
                continue
            if event_seq is not None and event.get("event_seq") != event_seq:
                continue
            if position_id is not None and event.get("position_id") != position_id:
                continue
            if order_seq is not None and event.get("order_seq") != order_seq:
                continue
            seq = event.get("event_seq")
            if start_event_seq is not None and (not _is_int(seq) or seq < start_event_seq):
                continue
            if end_event_seq is not None and (not _is_int(seq) or seq > end_event_seq):
                continue
            out.append(_copy(event))

        if bar_index is None:
            out.sort(key=lambda e: e.get("event_seq", 0))
        return out

    def event(self, event_seq):
        """Returns exactly one canonical event as a plain dict.

        Raises ``KeyError`` with ``code == "EVENT_NOT_FOUND"`` when absent.
        """
        if not _is_int(event_seq):
            raise TypeError("event_seq must be an int, got %s" % type(event_seq).__name__)
        found = self._by_event_seq.get(event_seq)
        if found is None:
            raise coded(
                KeyError("no canonical event with event_seq=%r" % (event_seq,)),
                "EVENT_NOT_FOUND",
                {"event_seq": event_seq},
            )
        return _copy(found)

    # ── bar ─────────────────────────────────────────────────────

    def bar(self, bar_index):
        """Returns canonical evidence grouped for one bar.

        Keys: ``bar_index``, ``timestamp``, ``ohlc``, ``ohlc_available``,
        ``events`` (every event attributed to the bar, canonical order),
        ``strategy_decisions``, ``drawings`` (exact canonical specs),
        ``orders`` (order_created/pending/triggered/expired), ``fills``,
        ``rejections``, ``positions_opened``, ``positions_closed``,
        ``portfolio`` (the bar's canonical ``portfolio_snapshot``, or ``None``).

        ``ohlc`` is ``None`` and ``ohlc_available`` is ``False`` when the
        dataset cannot be safely recovered (its ``sha256`` no longer matches the
        persisted identity). No OHLC is ever fabricated.

        Raises ``KeyError`` with ``code == "BAR_NOT_FOUND"`` for a bar that the
        run never processed.
        """
        if not _is_int(bar_index):
            raise TypeError("bar_index must be an int, got %s" % type(bar_index).__name__)
        bucket = self._by_bar.get(bar_index)
        if bucket is None:
            raise coded(
                KeyError("no canonical bar with bar_index=%r" % (bar_index,)),
                "BAR_NOT_FOUND",
                {"bar_index": bar_index},
            )

        decisions, drawings, orders, fills, rejections = [], [], [], [], []
        opened, closed, snapshots = [], [], []
        timestamp = None
        for event in bucket:
            etype = event.get("type")
            if etype == "bar_processed":
                timestamp = event.get("timestamp", timestamp)
            elif etype == "strategy_decision":
                decisions.append(_copy(event))
            elif etype == "drawings_emitted":
                drawings.extend(_copy(d) for d in (event.get("drawings") or []))
            elif etype == "order_filled":
                fills.append(_copy(event))
            elif etype == "order_rejected":
                rejections.append(_copy(event))
            elif etype in _ORDER_EVENT_TYPES:
                orders.append(_copy(event))
            elif etype == "position_opened":
                opened.append(_copy(event))
            elif etype == "position_closed":
                closed.append(_copy(event))
            elif etype == "portfolio_snapshot":
                snapshots.append(_copy(event))
        if timestamp is None:
            for event in bucket:
                if event.get("timestamp") is not None:
                    timestamp = event.get("timestamp")
                    break

        ohlc = self._ohlc(bar_index)
        return {
            "bar_index": bar_index,
            "timestamp": timestamp,
            "ohlc": ohlc,
            "ohlc_available": ohlc is not None,
            "events": [_copy(e) for e in bucket],
            "strategy_decisions": decisions,
            "drawings": drawings,
            "orders": orders,
            "fills": fills,
            "rejections": rejections,
            "positions_opened": opened,
            "positions_closed": closed,
            "portfolio": snapshots[-1] if snapshots else None,
        }

    def _ohlc(self, bar_index):
        if 0 <= bar_index < len(self._bars):
            return _copy(self._bars[bar_index])
        return None

    def _drawings_on_bar(self, bar_index):
        """Exact canonical drawing specs for one bar (``[]`` when absent)."""
        bucket = self._by_bar.get(bar_index)
        if not bucket:
            return []
        out = []
        for event in bucket:
            if event.get("type") == "drawings_emitted":
                out.extend(_copy(d) for d in (event.get("drawings") or []))
        return out

    # ── positions ───────────────────────────────────────────────

    def position(self, position_id):
        """Returns one position's canonical lifecycle.

        Works for both open and closed positions. Keys: ``position_id``,
        ``status`` (``"open"``/``"closed"``), ``opened``, ``closed``,
        ``opening_order`` (the full order lifecycle, or ``None``),
        ``closing_order`` (**always ``None``** — see the module docstring, G12),
        ``events``, ``entry_bar_index``, ``exit_bar_index``,
        ``annotations_at_entry``, ``annotations_at_exit``.

        Position ids are opaque: historical UUIDv4 ids and current UUIDv5 ids
        are both accepted.

        Raises ``KeyError`` with ``code == "POSITION_NOT_FOUND"`` when absent.
        """
        if not isinstance(position_id, str):
            raise TypeError(
                "position_id must be a str, got %s" % type(position_id).__name__
            )
        record = self._by_position.get(position_id)
        if record is None:
            raise coded(
                KeyError("no position with position_id=%r" % (position_id,)),
                "POSITION_NOT_FOUND",
                {"position_id": position_id},
            )

        opened = record.get("opened")
        closed = record.get("closed")

        events = list(record.get("events") or [])
        opening_seq = record.get("opening_order_seq")
        if _is_int(opening_seq):
            for event in self._by_order.get(opening_seq, []):
                events.append(event)
        events = _dedupe_by_event_seq(events)

        opening_order = None
        if _is_int(opening_seq):
            try:
                opening_order = self.order(opening_seq)
            except KeyError:  # pragma: no cover - defensive
                opening_order = None

        entry_bar = opened.get("bar_index") if opened else None
        exit_bar = closed.get("bar_index") if closed else None

        return {
            "position_id": position_id,
            "status": "closed" if closed is not None else "open",
            "opened": _copy(opened) if opened else None,
            "closed": _copy(closed) if closed else None,
            "opening_order": opening_order,
            # G12: `position_closed` carries no `order_seq`, so the closing order
            # is not canonically derivable. It is never inferred.
            "closing_order": None,
            "events": [_copy(e) for e in events],
            "entry_bar_index": entry_bar if _is_int(entry_bar) else None,
            "exit_bar_index": exit_bar if _is_int(exit_bar) else None,
            "annotations_at_entry": (
                self._drawings_on_bar(entry_bar) if _is_int(entry_bar) else []
            ),
            "annotations_at_exit": (
                self._drawings_on_bar(exit_bar)
                if closed is not None and _is_int(exit_bar)
                else []
            ),
        }

    def positions(self, open=None):
        """Returns every position lifecycle summary, canonically ordered.

        ``open=None`` returns all, ``True`` only open, ``False`` only closed.
        Ordering is by the position's **opening ``event_seq``** ascending — never
        by id, dict key or hash iteration.
        """
        if open is not None and not isinstance(open, bool):
            raise TypeError("open must be True, False or None")
        out = []
        for pid, record in self._by_position.items():
            opened = record.get("opened")
            closed = record.get("closed")
            is_open = closed is None
            if open is not None and is_open is not open:
                continue
            seq = opened.get("event_seq") if opened else None
            out.append(
                (
                    seq if _is_int(seq) else -1,
                    {
                        "position_id": pid,
                        "status": "open" if is_open else "closed",
                        "side": opened.get("side") if opened else None,
                        "quantity_lots": opened.get("quantity_lots") if opened else None,
                        "entry_price": opened.get("entry_price") if opened else None,
                        "exit_price": closed.get("exit_price") if closed else None,
                        "exit_reason": closed.get("exit_reason") if closed else None,
                        "net_realized_pnl": (
                            closed.get("net_realized_pnl") if closed else None
                        ),
                        "opening_order_seq": record.get("opening_order_seq"),
                        "opened_bar": opened.get("bar_index") if opened else None,
                        "closed_bar": closed.get("bar_index") if closed else None,
                        "entry_event_seq": seq if _is_int(seq) else None,
                    },
                )
            )
        out.sort(key=lambda item: item[0])
        return [summary for _, summary in out]

    def trades(self):
        """Returns completed canonical trades, newest close last.

        The shape is exactly ``RunResult.trades``: ``bar_index``,
        ``position_id``, ``direction``, ``quantity_lots``, ``entry_price``,
        ``exit_price``, ``exit_reason``, ``gross_realized_pnl``,
        ``total_commission``, ``net_realized_pnl`` — every value copied from the
        canonical ``position_closed`` event, never recomputed.
        """
        closed = [
            record["closed"]
            for record in self._by_position.values()
            if record.get("closed") is not None
        ]
        closed.sort(key=lambda e: e.get("event_seq", 0))
        return [
            {
                "bar_index": e.get("bar_index"),
                "position_id": e.get("position_id"),
                "direction": e.get("side"),
                "quantity_lots": e.get("quantity_lots"),
                "entry_price": e.get("entry_price"),
                "exit_price": e.get("exit_price"),
                "exit_reason": e.get("exit_reason"),
                "gross_realized_pnl": e.get("gross_realized_pnl"),
                "total_commission": e.get("total_commission"),
                "net_realized_pnl": e.get("net_realized_pnl"),
            }
            for e in closed
        ]

    # ── orders ──────────────────────────────────────────────────

    def order(self, order_seq):
        """Returns one order's canonical lifecycle.

        Keys: ``order_seq``, ``state`` (last canonical state event wins),
        ``created``/``pending``/``triggered``/``filled``/``rejected``/``expired``,
        ``position_id`` (when canonically linked through
        ``position_opened.order_seq``), ``events`` (every event carrying that
        sequence, including the linked ``position_opened``).

        Rejection ``category`` and ``reason`` are returned verbatim from the
        canonical ``order_rejected`` event — never interpreted.

        Raises ``KeyError`` with ``code == "ORDER_NOT_FOUND"`` when absent.
        """
        if not _is_int(order_seq):
            raise TypeError("order_seq must be an int, got %s" % type(order_seq).__name__)
        events = self._by_order.get(order_seq)
        if events is None:
            raise coded(
                KeyError("no order with order_seq=%r" % (order_seq,)),
                "ORDER_NOT_FOUND",
                {"order_seq": order_seq},
            )

        lifecycle = {slot: None for slot in _ORDER_SLOTS.values()}
        state = None
        for event in events:
            etype = event.get("type")
            slot = _ORDER_SLOTS.get(etype)
            if slot is not None:
                lifecycle[slot] = _copy(event)
                state = _ORDER_STATE[etype]

        return {
            "order_seq": order_seq,
            "state": state,
            "created": lifecycle["created"],
            "pending": lifecycle["pending"],
            "triggered": lifecycle["triggered"],
            "filled": lifecycle["filled"],
            "rejected": lifecycle["rejected"],
            "expired": lifecycle["expired"],
            "position_id": self._order_to_position.get(order_seq),
            "events": [_copy(e) for e in sorted(events, key=lambda e: e.get("event_seq", 0))],
        }

    def rejections(self):
        """Returns every rejected order joined with its canonical parameters.

        ``order_rejected`` alone does not say *what* was rejected —
        ``order_type``, ``side`` and ``quantity_lots`` live on ``order_created``.
        Each entry supplies: ``order_seq``, ``bar_index``, ``order_type``,
        ``side``, ``quantity_lots``, ``created_bar``, ``category``, ``reason``
        and the canonical ``events`` involved. Nothing is interpreted, ranked or
        reworded. Ordered by the rejection's canonical ``event_seq``.
        """
        out = []
        for seq, events in self._by_order.items():
            rejected = next(
                (e for e in events if e.get("type") == "order_rejected"), None
            )
            if rejected is None:
                continue
            created = next(
                (e for e in events if e.get("type") == "order_created"), None
            )
            involved = [
                e for e in events if e.get("type") in ("order_created", "order_rejected")
            ]
            involved.sort(key=lambda e: e.get("event_seq", 0))
            out.append(
                (
                    rejected.get("event_seq", 0),
                    {
                        "order_seq": seq,
                        "bar_index": rejected.get("bar_index"),
                        "order_type": created.get("order_type") if created else None,
                        "side": created.get("side") if created else None,
                        "quantity_lots": (
                            created.get("quantity_lots") if created else None
                        ),
                        "created_bar": created.get("created_bar") if created else None,
                        "category": rejected.get("category"),
                        "reason": rejected.get("reason"),
                        "events": [_copy(e) for e in involved],
                    },
                )
            )
        out.sort(key=lambda item: item[0])
        return [entry for _, entry in out]


# ── helpers ─────────────────────────────────────────────────────


def _copy(value):
    """Returns a fresh plain-dict copy so callers never touch our indexes."""
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def _dedupe_by_event_seq(events):
    seen = set()
    out = []
    for event in sorted(events, key=lambda e: e.get("event_seq", 0)):
        seq = event.get("event_seq")
        if _is_int(seq):
            if seq in seen:
                continue
            seen.add(seq)
        out.append(event)
    return out
