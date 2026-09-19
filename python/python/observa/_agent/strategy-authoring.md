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

**Only those eight keys are read.** Anything else — `quantity`, `stop_loss`,
`take_profit`, `qty`, `sl_price` — is silently ignored by the engine, so a typo
becomes a silently missing stop loss. `validate-strategy` reports unknown keys
as `SIGNAL_FIELD_UNKNOWN`.

Never return a bare signal dict (`{"direction": ...}` without the `signals`
envelope) and never return `None`: both are ignored by the engine and look like
"the strategy did not trade". Return `[]` for no action.

## 5. `bar`, `portfolio`, `history`

* `bar` — dict: `timestamp` (RFC 3339 str), `open`, `high`, `low`, `close`,
  `volume` (float or `None`). Use `bar["close"]`, not `bar.close`.
* `portfolio` — dict: `balance`, `equity`, `used_margin`, `free_margin`,
  `has_open_position`, `unrealised_pnl`, `open_positions`.
* `history` — list of **strictly prior** bar dicts. No lookahead is possible.
  It is empty on the first bar and unbounded (all prior bars), not a window.

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

Or over MCP (optional extra): `observa mcp --runs-dir runs/` exposes ten
read-only tools. Order rejections (bad size, bad SL distance, insufficient
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

Tiers: **A** structure (no code execution) → **B** imported class (no engine
run) → **C** smoke (real Engine on 6 bundled bars, validating the *raw* value
your `on_bar` returns). Smoke proves shape and integration only — it does not
prove your logic, and a strategy that emits zero signals in six bars is still
valid.

Exit codes: `0` valid, `1` invalid strategy, `2` usage/setup error. With
`--json`, stdout carries JSON only; diagnostics go to stderr.

## 14. Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Run completes, zero trades | returned a bare dict or `None` | return a list or the `signals` envelope |
| Stop loss never applied | used `stop_loss` as an input key | signal inputs are `sl`/`tp` |
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
