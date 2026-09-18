# Observa Python Strategy API

> **STATUS: CURRENT CONTRACT SUMMARY — VERIFY AGAINST SOURCE CODE BEFORE CHANGING IMPLEMENTATION**
>
> The original knowledge base explicitly warned that an earlier strategy document was aspirational and that the actual Python contract must stay synchronized with `portfolio_to_py()` / `bar_to_py()` in the implementation.

## Strategy class

```python
class MyStrategy:
    def initialize(self, params=None) -> None:
        ...

    def on_bar(self, bar: dict, portfolio: dict, history: list) -> list | dict:
        ...

    def teardown(self) -> None:
        ...
```

## Bar

- `open`
- `high`
- `low`
- `close`
- `volume` or `None`
- `timestamp` as ISO 8601 string

## Portfolio

- `balance`
- `equity`
- `has_open_position`
- `unrealised_pnl`
- `open_positions`

## Open position

- `ticket`
- `direction`
- `size`
- `entry_price`
- `unrealised_pnl`
- `sl`
- `tp`

### Position identity

`ticket` (alias `position_id`) identifies the position for **explicit-ticket
closes**. It is **deterministic and run-local**: the same dataset, config and
strategy always produce the same id, so repeat runs are byte-identical and two
runs can be compared position-by-position.

Treat the id as an **opaque string** — do not parse it or infer anything
economic from its text. Uniqueness is guaranteed within a run, not across runs.
See `ticket` under [Signal fields](#signal-fields).

## History

History is oldest-first and contains only bars available before the current strategy decision. The design intent is that future bars are structurally inaccessible.

## Return values

### Signals only

```python
return [
    {
        "direction": "buy",
        "size": 1.0,
    }
]
```

### Signals plus drawings

```python
return {
    "signals": [...],
    "drawings": [...],
}
```

Signal-only strategies may also return a plain list. A malformed drawing **fails
the run** with a coded error (see [Strategy annotations](#strategy-annotations-drawings)) —
drawings are never silently discarded.

## Signal fields

- `direction`: `buy`, `sell`, or `close`
- `size`: required
- `price`: optional
- `sl`: optional
- `tp`: optional
- `reason`: optional strategy-authored text explaining **this signal** (see
  *Reason contract* below). At most 1024 UTF-8 bytes; longer fails the run with
  `STRATEGY_REASON_TOO_LONG`.
- `ticket`: required for `close` — the exact `position_id`/`ticket` of the
  position to close (no FIFO fallback). Ids are deterministic and run-local, so
  a ticket is reproducible across identical runs.

### Reason contract

`reason` is the strategy's **own** text — Observa never generates, rewrites or
interprets it. It is recorded per signal on the canonical `strategy_decision`
event, so a persisted run can be inspected later for the strategy's stated
rationale without re-running the strategy.

- Optional. Omitting it (or passing `None`) records **no** reason; an empty
  string is equivalent. There is no placeholder text.
- **Preserved exactly**: no trimming, case folding, punctuation rewriting, space
  collapsing or Unicode alteration. Leading/trailing whitespace and any Unicode
  (including emoji) are stored as authored.
- **Per signal**: a bar returning several signals gets one reason per signal,
  index-aligned in the order the strategy returned them, with `null` for signals
  that gave none.
- **At most 1024 UTF-8 bytes**, measured in encoded bytes (not characters), so
  multi-byte text reaches the limit sooner. Longer reasons fail the run with
  `exc.code == "STRATEGY_REASON_TOO_LONG"` and `exc.details` carrying
  `bar_index`, `signal_index`, `actual_bytes` and `max_bytes`. Reasons are never
  truncated or silently dropped.
- **All-or-nothing**: every reason on a bar is validated before the decision is
  recorded or any signal is processed, so an invalid reason cannot leave a
  partially executed callback behind.
- **Survives rejection**: the reason is recorded before order processing, so a
  signal whose resulting order is rejected still has its reason in canonical
  history. The reason is not copied onto the rejection event.
- **Descriptive only**: reasons never influence prices, fills, spread, slippage,
  commissions, SL/TP, margin, P&L, position identity, ordering or metrics.
- **Deterministic**: reasons become part of the byte-reproducible canonical
  history, so they must not contain wall-clock, random or environment-derived
  text.
- A deliberate **hold** has no reason: a strategy that decides not to act emits
  zero signals, so there is nothing to record.

## Current gaps from the source KB

- `on_fill()` is not yet wired through the Python bridge.
- Python-side indicator registration is not implemented.
- Strategies are currently single-threaded.

## Synchronization rule

Any change to `bar_to_py()` or `portfolio_to_py()` must update this contract and its tests in the same change set.

---

# Strategy annotations (drawings)

Human-inspectable annotations produced by a strategy and rendered by replay.
Observa is moving toward an AI-native workflow in which a human may never read
the generated strategy code, so replay must show **what the strategy was
looking at** — indicators, zones, levels, signal context.

## Authority rule (non-negotiable)

Annotations are **descriptive only**. They never influence order creation,
fills, spread/slippage, SL/TP, margin, portfolio accounting, metrics or
execution chronology. Observa never interprets a strategy concept such as
"FVG" or "POC"; it renders the generic primitive the strategy asks for.

Execution markers (entries/exits) are owned by Observa and derived from
canonical `position_opened` / `position_closed` events. Strategy `marker`
drawings are a **separate layer** and must not be used to fake fills.

## Return shape

```python
def on_bar(self, bar, portfolio, history):
    return {
        "signals": [...],
        "drawings": [
            {"id": "ema_20", "type": "series", "value": ema20, "color": "#58a6ff", "label": "EMA 20"},
        ],
    }
```

Every drawing has a stable `id` (`^[A-Za-z0-9_.:-]{1,64}$`) and an optional
`action` (`add` default, `update`, `remove`). `label` is presentation only and
is never the identity.

Rules that matter:

* `series` uses `add` for every point; `update` on a series is invalid.
* `remove` (id only) deletes a drawing or stops a series from that bar onward.
* `update` requires an existing id and must keep the same `type`.
* Reusing an id with a different type is invalid.
* At most **256** drawing instructions per bar (`DRAWING_LIMIT_EXCEEDED`).
* Timestamps must be real bar timestamps (`bar["timestamp"]`) — never a future
  or invented time.
* Colours are `#RRGGBB` or `#RRGGBBAA`. `width` is 1, 2 or 3.

## Primitives

### `series` — continuous per-bar values (EMA, VWAP, z-score, spread)

```python
{"id": "ema_20", "type": "series", "value": 1.09876,
 "series_type": "line",       # line | histogram
 "line_style": "solid",       # solid | dashed | dotted
 "width": 1,                  # 1 | 2 | 3
 "color": "#58a6ff",
 "pane": "price",             # price | separate
 "label": "EMA 20"}
```

The same `id` emitted across bars is one continuous series; each emission is
the **current** bar's value. `value: null` — or simply not emitting that bar —
is a gap: it is never zero and never interpolated. Use gaps for warm-up.

`pane: "price"` overlays the candle chart. `pane: "separate"` uses the single
generic secondary pane, for values on a different scale (z-score, spread,
RSI-like user values).

### `hline` — horizontal level (POC / VAH / VAL / support / resistance)

```python
{"id": "poc", "type": "hline", "price": 1.0972,
 "color": "#d29922", "line_style": "dashed", "width": 1, "label": "POC"}
```

Naturally extended across the chart — emit it once; do not re-emit every bar.

### `line` — straight segment (trend line, channel edge)

```python
{"id": "trend_1", "type": "line",
 "x1": ts1, "y1": 1.0950, "x2": ts2, "y2": 1.0975,
 "color": "#8957e5", "line_style": "solid", "width": 1}
```

`x1/y1/x2/y2` are all required. Observa does not draw infinite sloped rays —
use `hline` for indefinitely extended levels.

### `rectangle` — price zone (FVG, order block, value area)

```python
{"id": "zone_7", "type": "rectangle",
 "time_start": ts, "time_end": None,   # None extends right as replay advances
 "price_top": 1.0990, "price_bot": 1.0981,
 "color": "#3fb950", "opacity": 0.14, "border": "#3fb950", "label": "FVG"}
```

The **strategy owns the lifecycle**. Invalidate it explicitly when price
trades back into the zone:

```python
{"id": "zone_7", "action": "remove"}
```

### `region` — time window (session, news window, research window)

```python
{"id": "london", "type": "region",
 "time_start": ts1, "time_end": ts2,
 "color": "#58a6ff", "opacity": 0.10, "label": "London"}
```

No price semantics.

### `marker` — strategy marker (signal fired, rejected signal, anomaly)

```python
{"id": "sig_12", "type": "marker", "time": ts,
 "position": "below",     # above | below
 "shape": "arrow_up",     # circle | square | arrow_up | arrow_down
 "color": "#3fb950", "text": "long condition true"}
```

Bar-anchored icon. Kept visually separate from canonical execution markers.

### `label` — text callout

```python
{"id": "note_3", "type": "label", "time": ts, "price": 1.0980,
 "text": "RSI 27", "color": "#f85149",
 "position": "below"}     # above | below | left | right
```

## Recipes

### EMA overlay

```python
def on_bar(self, bar, portfolio, history):
    self.closes.append(bar["close"])
    ema = None
    if len(self.closes) >= self.period:
        ema = sum(self.closes[-self.period:]) / self.period
    return {"signals": [], "drawings": [
        {"id": "ema", "type": "series", "value": ema,       # None = warm-up gap
         "color": "#58a6ff", "label": f"EMA {self.period}"},
    ]}
```

### VWAP

```python
{"id": "vwap", "type": "series", "value": vwap, "color": "#d29922", "label": "VWAP"}
```

### Three-line sigma bands (±2σ)

No shaded band primitive is needed — three series describe it exactly:

```python
[{"id": "bb_mid", "type": "series", "value": mid, "color": "#8b949e", "label": "Mid"},
 {"id": "bb_up",  "type": "series", "value": mid + 2 * sd, "color": "#58a6ff", "label": "+2σ"},
 {"id": "bb_dn",  "type": "series", "value": mid - 2 * sd, "color": "#58a6ff", "label": "-2σ"}]
```

### FVG zone + invalidation

```python
# on the gap bar
{"id": f"fvg_{n}", "type": "rectangle", "time_start": bar["timestamp"], "time_end": None,
 "price_top": gap_high, "price_bot": gap_low, "color": "#3fb950", "opacity": 0.14,
 "border": "#3fb950", "label": "FVG"}
# on the bar that fills it
{"id": f"fvg_{n}", "action": "remove"}
```

### POC / VAH / VAL levels

```python
[{"id": "poc", "type": "hline", "price": poc, "color": "#d29922", "label": "POC"},
 {"id": "vah", "type": "hline", "price": vah, "color": "#8b949e", "line_style": "dashed", "label": "VAH"},
 {"id": "val", "type": "hline", "price": val, "color": "#8b949e", "line_style": "dashed", "label": "VAL"}]
```

### Rejected-signal marker

```python
{"id": f"rej_{n}", "type": "marker", "time": bar["timestamp"], "position": "above",
 "shape": "square", "color": "#f85149", "text": "rejected"}
```

### Session region

```python
{"id": "session_london", "type": "region", "time_start": ts_start, "time_end": ts_end,
 "color": "#58a6ff", "opacity": 0.10, "label": "London"}
```

### z-score in the separate pane

```python
[{"id": "zscore", "type": "series", "value": z, "pane": "separate",
  "series_type": "line", "color": "#8957e5", "label": "z-score"},
 {"id": "z0", "type": "hline", "price": 0.0, "color": "#8b949e", "line_style": "dotted"}]
```

## Validation errors

Malformed drawings fail the run (the exception keeps its normal class and adds
`exc.code` / `exc.details`, exactly like the OBS-AI-01 error model):

| Code | Meaning | Useful `details` |
| --- | --- | --- |
| `DRAWING_TYPE_INVALID` | missing/unknown `type` | `drawing_id`, `drawing_type`, `index` |
| `DRAWING_FIELD_MISSING` | required field absent | `field`, `drawing_type` |
| `DRAWING_VALUE_INVALID` | wrong type / non-finite / out of range | `field`, `value` |
| `DRAWING_ID_INVALID` | id missing or not `^[A-Za-z0-9_.:-]{1,64}$` | `drawing_id` |
| `DRAWING_ACTION_INVALID` | bad action; update on a series; type change on update | `action` |
| `DRAWING_PANE_INVALID` | `pane` not `price`/`separate` | `field`, `value` |
| `DRAWING_TIME_INVALID` | unparseable or non-bar timestamp | `field`, `value` |
| `DRAWING_REFERENCE_INVALID` | update/remove of an unknown id | `action` |
| `DRAWING_LIMIT_EXCEEDED` | more than 256 instructions on one bar | `count`, `limit` |

```python
try:
    observa.run(MyStrategy(), data, config=config)
except RuntimeError as exc:
    print(exc.code)      # e.g. "DRAWING_FIELD_MISSING"
    print(exc.details)   # {"field": "price", "drawing_type": "hline", ...}
```

## Deprecated fields

**`style` is a deprecated compatibility alias for `line_style`.** It is
honoured, not ignored:

```python
{"id": "poc", "type": "hline", "price": 1.0972, "style": "dashed"}
# identical to:  "line_style": "dashed"
```

The following fields are accepted for backward compatibility and are
**ignored** — they have no effect on the rendering or on the engine:

| Field | Status |
| --- | --- |
| `persist` | ignored. There is no hidden price-crossing lifecycle; the strategy decides when to emit `action: "remove"`. |
| `fill_price` | ignored (it was only meaningful together with `persist`). |
| `extend` | ignored. `line` requires both endpoints; use `hline` for indefinitely extended levels. |
| `bg_color` | ignored. Label backgrounds are derived from `color`. |

Do not use any of these in new strategies.

## Deprecated: `bar_color`

`bar_color` is accepted for backward compatibility only. It is not part of this
public contract and receives no new functionality.

# Run inspection (persisted runs)

`observa.inspect_run(run_dir)` opens an **existing** persisted run and returns a
read-only `PersistedRun`. Use it to ask what canonical history contains without
re-running the engine, importing the strategy, or parsing `events.jsonl` by
hand.

```python
import observa

run = observa.inspect_run("runs/quickstart_20260918")

run.meta                  # the persisted run.json (plain dict)
run.metrics               # the persisted metrics.json, or None for a failed run

run.events(event_type="order_rejected")
run.events(bar_index=421)
run.events(position_id=pid, start_event_seq=100)
run.event(254)            # one canonical event by event_seq

run.bar(421)              # every canonical event attributed to that bar
run.position(pid)         # one position's full lifecycle
run.order(17)             # one order's full lifecycle
run.positions(open=None)  # every position summary, opening event_seq order
run.trades()              # completed canonical trades
run.rejections()          # rejected orders joined with their order parameters
```

## Authority and guarantees

- **Artifacts are authoritative.** Everything comes from `run.json`,
  `events.jsonl` and `metrics.json`. `events.jsonl` is the source of truth for
  history.
- **No engine execution.** Inspection never runs the engine, never imports or
  executes a strategy, and never writes to the run directory. A persisted run
  remains inspectable after its strategy code is gone.
- **No recomputation.** Economics and metrics are never recomputed. `trades()`
  copies the canonical `position_closed` values verbatim, so for a run created
  in-process it is value-for-value identical to `RunResult.trades`.
- **Plain data only.** Every result is composed of `dict`, `list`, `str`, `int`,
  `float`, `bool` and `None`, is JSON-serializable, and is a fresh copy the
  caller may mutate freely.
- **Canonical ordering.** Every event collection preserves ascending
  `event_seq`. `positions()` is ordered by the position's opening `event_seq`.
  Nothing is ordered by identifier text.
- **Opaque ids.** Current runs use deterministic UUIDv5 `position_id` values and
  historical runs use UUIDv4; both are accepted and returned unchanged. Do not
  parse an id or infer economics from its text.

## `events(...)` filters

| Filter | Semantics |
| --- | --- |
| `event_type` | exact canonical event type; an unknown type returns `[]` |
| `event_seq` | exact primary key (agrees with `event()`) |
| `bar_index` | **canonical chronology bucket** — identical to `bar(n)["events"]` |
| `position_id` | events carrying that id (`position_opened` / `position_closed`) |
| `order_seq` | every event carrying that sequence (order events + the `position_opened` it opened) |
| `start_event_seq` / `end_event_seq` | inclusive range on `event_seq` |

Filters combine with **AND**. No match returns `[]` (never `None`). A filter of
the wrong type raises `TypeError`. There are no predicates, no OR expressions
and no query language.

## `bar(bar_index)`

Returns canonical evidence for one bar: `bar_index`, `timestamp`, `ohlc`
(`None` unless the dataset is safely recoverable), `ohlc_available`, the
complete `events` list, plus grouped `strategy_decisions`, `drawings` (exact
canonical specs), `orders` (created/pending/triggered/expired), `fills`,
`rejections`, `positions_opened`, `positions_closed`, and `portfolio` (the
canonical `portfolio_snapshot`, or `None`).

Bar attribution follows the replay chronology rule: an event belongs to the bar
whose `bar_processed` is open. Several event types carry no bar field at all and
`order_created` stores `created_bar`, which is why a naive field match would be
wrong. OHLC is only returned when the recorded `dataset.source` still hashes to
the persisted `dataset.sha256`; otherwise the API degrades cleanly and never
fabricates bars.

## `position(position_id)`

One lifecycle object for both open and closed positions: `position_id`,
`status`, `opened`, `closed`, `opening_order` (the full order lifecycle),
`closing_order` (the full lifecycle of the canonical order that closed the
position, or `None`), `events`, `entry_bar_index`, `exit_bar_index`,
`annotations_at_entry`, `annotations_at_exit`. A "trade" is simply a closed
position, which is why there is no separate `trade()` accessor.

A closing order is recorded whenever one exists (OBS-SCHEMA-02):
`position_closed.order_seq` is persisted for every explicit strategy/ticket
close, in both fill modes, and `closing_order` resolves it through the same
order index that `opening_order` uses. Protective SL/TP exits have no closing
order in the current execution model — they are ordered by the fixed per-bar
protective stage, are not strategy-generated orders, and their
`position_closed` omits the key entirely. Symmetrically,
`order(order_seq)["position_id"]` is the position that order **opened or
closed**. `positions()` summaries expose `opening_order_seq` and
`closing_order_seq` (`int` or `None`).

## Error codes

Inspection reuses the existing run codes and adds four lookup codes. Exceptions
keep their normal Python classes; `exc.code` and `exc.details` carry the
machine-readable form (`observa.error_code(exc)`).

| Code | Class | When |
| --- | --- | --- |
| `RUN_DIR_NOT_FOUND` | `FileNotFoundError` | the run directory or its `run.json` is missing |
| `RUN_ARTIFACTS_INVALID` | `ValueError` | `run.json`, `events.jsonl` or `metrics.json` cannot be parsed, or a canonical `order_seq` reference on a position resolves to no order |
| `EVENT_NOT_FOUND` | `KeyError` | `event(event_seq)` has no such event |
| `BAR_NOT_FOUND` | `KeyError` | `bar(bar_index)` has no such bar |
| `POSITION_NOT_FOUND` | `KeyError` | `position(position_id)` has no such position |
| `ORDER_NOT_FOUND` | `KeyError` | `order(order_seq)` has no such order |

Absent data is not an error: a failed run has `metrics is None`, a run without
annotations yields `drawings == []`, and an unrecoverable dataset yields
`ohlc_available is False`.

## Current canonical-data limitations

- **Historical runs may lack reason data.** Runs produced before OBS-SCHEMA-01
  have no `signals` on `strategy_decision`; `decision.get("signals")` is then
  absent and there are simply no reasons to read. Nothing is back-filled or
  re-run. A deliberate hold still has no canonical reason (see the reason
  contract above).
- **Protective exits have no closing order.** A StopLoss/TakeProfit close is not
  a strategy order: it allocates no `OrderSeq`, emits no `order_created` /
  `order_filled`, and its `position_closed` omits `order_seq` entirely (never
  `null`). `position(pid)["closing_order"]` is therefore `None` for those
  closes, and `closing_order_seq` is `None` in the `positions()` summary.
- **Runs created before OBS-SCHEMA-02 may have Signal closes without recorded
  closing-order linkage.** Their `position_closed` has no `order_seq` at all, so
  `closing_order` is `None` even though an order did close the position. The
  historical closer is **never** guessed — not from side, quantity, timestamp,
  adjacency, bar correlation or the opening order.

`closing_order` is therefore three-valued in practice, and the distinctions must
not be collapsed:

| `closing_order` | `exit_reason` | Meaning |
| --- | --- | --- |
| dict | `Signal` | the exact canonical closing order is recorded |
| `None` | `StopLoss` / `TakeProfit` | protective exit — no order ever existed |
| `None` | `Signal` | run predates OBS-SCHEMA-02 — the link was not recorded |

A present, well-typed `order_seq` that resolves to no order is **not** a third
kind of `None`: it is a corrupt artifact set and raises
`RUN_ARTIFACTS_INVALID` when the run is opened.
