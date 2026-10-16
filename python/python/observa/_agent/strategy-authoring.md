# Observa — Strategy Authoring Guide

You are writing a **user strategy** for Observa. Observa owns execution: you
express *intent*, the canonical Rust Engine decides fills, spread, slippage,
SL/TP and P&L. Never write a second backtest loop.

Machine-readable contract: `observa.agent_spec()`
Run the gold example: `python <observa.agent_example_path()>`
Validate: `observa validate-strategy strategy.py --json`

## 1. Mental model

Python says *what you want*. The Engine says *what happened*, and records it as
canonical events you can inspect afterwards.

```
your on_bar()  ->  signals (intent)  ->  Engine (fill, SL/TP, P&L)  ->  run artifacts
```

## 2. Lifecycle

```python
class MyStrategy:                       # subclassing observa.Strategy is optional
    def initialize(self, params=None): ...      # once, before the first bar
    def on_bar(self, bar, portfolio, history):  # once per closed bar
        return []
    def teardown(self): ...                     # once, after the last bar
```

`initialize` receives the resolved `params` dict (`{}` when none are configured).
If you subclass `observa.Strategy` you **must still override `on_bar`** — the
base class returns `[]`, so a missing override produces a silent zero-trade run.
Raising from any callback fails the run.

## 3. Simplest strategy

```python
import observa

class BuyAndHold(observa.Strategy):
    def on_bar(self, bar, portfolio, history):
        if portfolio["has_open_position"]:
            return []
        return [{"direction": "buy", "size": 1.0, "reason": "initial entry"}]
```

## 4. Signal fields

`on_bar` returns **a list** of signal dicts, or a dict
`{"signals": [...], "drawings": [...]}`. Two fields are required:

| Field | Required | Values |
| --- | --- | --- |
| `direction` | yes | `"buy"` \| `"sell"` \| `"close"` (lowercase) |
| `size` | yes | float, lots |
| `order_type` | no | `"market"` (default) \| `"limit"` \| `"stop"` |
| `price` | no | float — the limit/stop trigger price |
| `sl` / `tp` | no | float — protective stop loss / take profit (entries) |
| `reason` | no | str, ≤1024 UTF-8 bytes, persisted |
| `ticket` | **for close** | the exact `position_id` to close |

```python
return [{"direction": "buy", "size": 1.0, "price": bar["close"],
         "sl": bar["close"] - 0.0040, "reason": "breakout"}]
```

**Only those eight keys are allowed.** Anything else — `quantity`, `stop_loss`,
`take_profit`, `qty`, `sl_price` — fails the run at that bar with
`SIGNAL_FIELD_UNKNOWN`; `exc.details` names the `field`, a `suggestion`
(`stop_loss` → `sl`) and the `allowed` keys.

Never return a bare signal dict (`{"direction": ...}` without the `signals`
envelope), `None` (e.g. a path with no `return`), or a dict without a
`signals` list: the run fails at that bar with `STRATEGY_RETURN_INVALID`.
Return `[]` for no action.

## 5. `bar`, `portfolio`, `history`

* `bar` — dict: `timestamp`, `timestamp_ms`, `open`, `high`, `low`, `close`,
  `volume` (float or `None`). Use `bar["close"]`, not `bar.close`.
  `timestamp` is always the canonical UTC string
  `YYYY-MM-DDTHH:MM:SS[.f…]+00:00` (fractional seconds only when non-zero), whatever form the input used (an input
  `2025-06-01T00:05:00Z` is presented as `2025-06-01T00:05:00+00:00`).
  `timestamp_ms` is the integer epoch milliseconds — **join external data on
  `timestamp_ms` (or a parsed datetime), never on the raw input string.**
* `portfolio` — dict: `balance`, `equity`, `used_margin`, `free_margin`,
  `has_open_position`, `unrealised_pnl`, `open_positions`.
* `history` — a read-only, list-like sequence of the **strictly prior** bar
  dicts. No lookahead is possible. It is empty on the first bar and holds all
  prior bars (not a window). It supports `len`, `history[-1]`, slices such as
  `history[-20:]` (which return lists), iteration and `list(history)`; it
  cannot be mutated. Providing it costs O(1) per bar, so long intraday runs
  are fine.

```python
if len(history) < self.period:      # always guard warm-up
    return []
closes = [b["close"] for b in history[-self.period:]]
```

## 6. Closing a position — exact ticket

```python
pos = portfolio["open_positions"][0]
return [{"direction": "close", "size": pos["size"],
         "ticket": pos["position_id"], "reason": "exit rule fired"}]
```

There is **no FIFO**, no "close the oldest" and no implicit close. A close
without a valid ticket is recorded as an `order_rejected` event — it does not
raise, so check your runs.

Each position dict has: `position_id`/`ticket`, `symbol`, `direction`
(`"Buy"`/`"Sell"` — capitalised), `quantity`/`size`, `entry_price`,
`unrealized_pnl`/`unrealised_pnl`, `stop_loss`, `take_profit`. Note the
asymmetry: signal **input** uses lowercase `buy` and the keys `size`/`sl`/`tp`;
position **output** is `"Buy"` and `stop_loss`/`take_profit`.

## 7. SL/TP

Attach `sl` and/or `tp` to an **entry** signal; the Engine evaluates them and
records the outcome. Same-bar SL-first applies. Invalid distances are rejected
as events, not raised.

## 8. `reason`

`reason` is persisted on the canonical `strategy_decision` event and shown in
replay and via inspection. Write reasons a human would understand. Over 1024
UTF-8 bytes the whole run fails with `STRATEGY_REASON_TOO_LONG`.

## 9. Annotations (drawings)

Return an envelope with a `drawings` list to annotate the chart:

```python
return {"signals": [...], "drawings": [
    {"id": "entry_line", "type": "hline", "price": price,
     "color": "#58a6ff", "label": "entry"}]}
```

Types: `series`, `hline`, `line`, `rectangle`, `region`, `marker`, `label`,
`bar_color`. Maximum 256 per bar. Any `time` must be an already-seen bar
timestamp (no future bars). Annotations are descriptive only — they never
affect orders, fills or P&L. Malformed annotations fail the run with a
`DRAWING_*` code.

## 10. Config, run and persistence

```python
config = observa.Config(
    dataset_source=observa.sample_data_path(),
    fill_mode=observa.NEXT_BAR_OPEN,   # or observa.BAR_CLOSE
    spread=0.0002, slippage=0.0001,
    commission=7.0, commission_mode=observa.ROUND_TRIP,
    interval="15m", params={"period": 5}, strategy_name="MyStrategy",
)
result = observa.run(MyStrategy(), observa.sample_data_path(),
                     config=config, output="runs/my_strategy")
```

Always pass `output=` — that is what writes `run.json`, `events.jsonl` and
`metrics.json`. Output directories are **create-only**; re-running into the same
path raises `RUN_OUTPUT_EXISTS`.

## 11. Inspecting the result

```python
print(result.summary())          # status, bars, trades, balance, equity, metrics
run = observa.inspect_run("runs/my_strategy")
run.positions(); run.trades(); run.position(pid)["closing_order"]
```

Or over MCP (included in the standard install): `observa mcp --runs-dir runs/`
exposes thirteen read-only tools (ten inspection, three authoring discovery). Order rejections (bad size, bad SL distance, insufficient
margin) are canonical `order_rejected` events — read them, do not expect an
exception.

## 12. Forbidden behaviour

Do **not**: implement your own fill model or matching engine; apply spread,
slippage or commission yourself; compute balance, equity, P&L, drawdown or any
metric yourself; recreate order execution or SL/TP evaluation; read future bars;
assume FIFO; return a bare dict or `None` from `on_bar`; use `quantity`,
`stop_loss` or `take_profit` as signal input keys; or run `pip install observa`
or `pip install "observa[mcp]"` (that PyPI project is unrelated — install the
release wheel, or the same wheel with `[mcp]`).

## 13. Validation

```bash
observa validate-strategy strategy.py              # human output
observa validate-strategy strategy.py --json       # machine output (repair loop)
observa validate-strategy strategy.py --smoke      # + run 6 deterministic bars
```

Tiers: **A** structure (parses the source only — it does **not** import or
execute your code) → **B** imported class (**B imports the strategy module**, so
top-level Python code in it may execute; B never calls `on_bar`) → **C** smoke
(the real Engine executes your `on_bar`, validating the *raw* value it returns).

Smoke proves shape and integration only — it does not prove your logic, and a
strategy that emits zero signals in six bars is still valid.

> ⚠️ **Security: validation is not a sandbox.** Tier B imports the strategy
> module, which may execute top-level Python code, and Tier C additionally
> executes the strategy's `on_bar()` through the real Observa Engine. Only
> validate strategy code you trust.

Exit codes: `0` valid, `1` invalid strategy, `2` usage/setup error. With
`--json`, stdout carries JSON only; diagnostics go to stderr.

## 14. Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `STRATEGY_RETURN_INVALID` | returned a bare dict, `None` or a dict without `signals` | return a list or the `signals` envelope |
| `SIGNAL_FIELD_UNKNOWN` | used `stop_loss`/`quantity`/… as an input key | signal inputs are `sl`/`tp`/`size` (see `exc.details["suggestion"]`) |
| Run completes, zero trades | every order rejected (often margin) | read `order_rejected` events / `inspect_run(dir).rejections()` |
| External signals never match | joined on the timestamp *string* | join on `bar["timestamp_ms"]` |
| `DATA_INVALID` | NaN/inf, broken OHLC, timezone-less or millisecond timestamps | fix the row named in `exc.details["row"]` |
| `KeyError: 'position_id'` | read the wrong output key | use `pos["position_id"]` or `pos["ticket"]` |
| Close never happens | used `pos["direction"] == "buy"` | output casing is `"Buy"` |
| `IndexError` on early bars | indexed `history` without a warm-up guard | `if len(history) < period: return []` |
| Run fails with `STRATEGY_REASON_TOO_LONG` | reason > 1024 bytes | shorten the reason |
| Run fails with `DRAWING_*` | malformed annotation | check type/fields/limits |
| `RUN_OUTPUT_EXISTS` | output dir already exists | pick a new directory |
| Wrong package installed | `pip install observa` | install the release wheel |

---

Deeper references: `docs/execution-model.md` (fill/SL/TP/margin semantics),
`docs/STRATEGY_API.md`, `llms-full.txt`. Machine contract: `observa.agent_spec()`.
