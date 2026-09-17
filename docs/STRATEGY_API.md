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
- `reason`: optional
- `ticket`: required for `close`

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
