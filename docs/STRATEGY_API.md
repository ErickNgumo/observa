# Observa Python Strategy API

The canonical, authoritative reference for the released Python strategy
contract. It is intentionally short: the normative contract is machine-readable
and ships inside the wheel.

## Authority (read this first)

* **The shipped wheel binding is authoritative: `python/src/lib.rs`** (maturin
  project `python/`, module `observa._observa`). Everything in this document is
  a description of it.
* **`crates/observa-python/` is a legacy/dev-only bridge.** It is used only by
  the Rust `observa-cli` binary (`observa run --strategy …`), which is **not**
  part of the released wheel and **not** part of the release assets. Its
  portfolio/position dicts are smaller and differ (no `position_id`,
  `quantity`, `symbol`, `stop_loss`, `take_profit`, `used_margin`,
  `free_margin`). It is **not** the strategy contract of the released Python
  wheel; a later ticket may reconcile or remove it.
* Never derive the contract from prose when the code or the spec can be
  inspected.

## Discover the contract from an installed wheel

```python
import observa
observa.agent_spec()          # canonical machine-readable contract (dict)
observa.agent_spec_path()     # bundled spec.json
observa.agent_guide_path()    # short authoring guide
observa.agent_example_path()  # gold example to imitate
observa.validate_strategy("strategy.py", smoke=True)   # structured errors
```

```bash
observa agent-spec --json
observa validate-strategy strategy.py --json
```

`strategy_api_version` versions the **authoring surface only**. It is
independent of the package version and of `RUN_SCHEMA_VERSION` /
`METRICS_SCHEMA_VERSION` / `EVENT_SCHEMA_VERSION`.

## Contract

Generated from `observa.agent_spec()` — do not hand-edit this block; edit
`python/python/observa/_agent/contract.py` and re-render with
`python -m observa._agent._render --doc docs/STRATEGY_API.md`.

<!-- BEGIN GENERATED: strategy-contract -->
**strategy_api_version `1`** (observa 0.1.4). This block is generated from `observa.agent_spec()`; edit the contract, not this text.

A strategy is a plain Python class (subclassing `observa.Strategy` is optional):

```python
class MyStrategy:
    def initialize(self, params=None): ...
    def on_bar(self, bar, portfolio, history): ...
    def teardown(self): ...
```

Lifecycle order: initialize(params) once before the first bar; on_bar(bar, portfolio, history) once per closed bar; teardown() once after the last bar.

* A plain class with the three methods works; subclassing is optional.
* TRAP: if you subclass observa.Strategy you must still override on_bar - the base class returns [] and a missing override silently produces a zero-trade run.
* initialize receives the resolved params dict ({} when none are set).
* Raising from any callback fails the run (code STRATEGY_ERROR).

`on_bar` must return:

* `[]  # no action`
* `[{...signal...}, ...]`
* `{'signals': [...], 'drawings': [...]}`

Never return:

* TRAP: a bare signal dict {'direction': 'buy', 'size': 1.0} - the engine reads only the 'signals' key, so it is ignored. Wrap it in a list.
* TRAP: None - return [] for 'no action'; None is ambiguous.
* {'signal': [...]} - misspelled envelope key.
* str, tuple, number - anything not a list or dict.

### Fields (exact)

`bar` — dict (read-only):

| Key | Meaning |
| --- | --- |
| `close` | float |
| `high` | float |
| `low` | float |
| `open` | float |
| `timestamp` | str, RFC 3339 |
| `volume` | float or None |

No bar_index and no symbol. Use bar['close'], not bar.close.

`portfolio` — dict (read-only):

| Key | Meaning |
| --- | --- |
| `balance` | float, realised cash |
| `equity` | float, balance + unrealised P&L |
| `free_margin` | float |
| `has_open_position` | bool |
| `open_positions` | list of position dicts |
| `unrealised_pnl` | float |
| `used_margin` | float |

each `position` — dict (read-only), from portfolio['open_positions'][i]:

| Key | Meaning |
| --- | --- |
| `direction` | 'Buy' or 'Sell' - OUTPUT is capitalised |
| `entry_price` | float |
| `position_id` | str, the exact ticket to close with |
| `quantity` | float, alias of size |
| `size` | float, lots |
| `stop_loss` | float or None - OUTPUT name |
| `symbol` | str |
| `take_profit` | float or None - OUTPUT name |
| `ticket` | str, alias of position_id |
| `unrealised_pnl` | float |
| `unrealized_pnl` | float, alias of unrealised_pnl |

TRAP: signal INPUT uses lowercase 'buy' and keys size/sl/tp; position OUTPUT uses 'Buy' and stop_loss/take_profit. quantity is an output alias only - the input key is size.

`history` — strictly PRIOR bars only. No lookahead is possible. Guard warm-up yourself: if len(history) < period: return []. It is all prior bars, not a fixed window, so slice history[-period:].

### Signal fields

Required: `direction`, `size`.

| Key | Meaning |
| --- | --- |
| `direction` | 'buy' | 'sell' | 'close' (lowercase, case-insensitive on input) |
| `order_type` | 'market' (default) | 'limit' | 'stop' |
| `price` | float; limit/stop trigger price |
| `reason` | str, persisted, max 1024 UTF-8 bytes |
| `size` | float, lots (INPUT quantity field - not 'quantity') |
| `sl` | float, protective stop loss (entries) |
| `ticket` | str, REQUIRED for close - use position['position_id'] |
| `tp` | float, protective take profit (entries) |

TRAP: only those eight keys are read. Any other key (stop_loss, take_profit, quantity, qty, sl_price) is silently ignored, so a typo silently drops your stop loss. validate-strategy reports SIGNAL_FIELD_UNKNOWN.

Order types: `market`, `limit`, `stop` (default `market`); limit/stop trigger price goes in `price`.

Rejections (bad size, bad SL/TP distance, insufficient margin) are canonical order_rejected EVENTS, not Python exceptions.

Closing: `{'direction': 'close', 'size': pos['size'], 'ticket': pos['position_id']}` — requires a ticket: True; FIFO: False. No FIFO, no 'close oldest', no implicit close. A close without a valid ticket is rejected as an event, not raised.

`reason`: max 1024 UTF-8 bytes, code `STRATEGY_REASON_TOO_LONG`, persisted: True. Recorded on the canonical strategy_decision event; visible in replay and via inspect_run/MCP. Over-long reasons fail the whole run.

### Annotations (drawings)

Types: `series`, `hline`, `line`, `rectangle`, `region`, `marker`, `label`, `bar_color`. Maximum **256 per bar**. `id`: 1-64 chars from [A-Za-z0-9_.:-]. `time`: any 'time' must be an already-seen bar timestamp (no future bars).

Descriptive only - never affects orders, fills, P&L or chronology. Malformed drawings fail the run.

### Execution authority

The Engine owns:

* `order creation, scheduling and triggering`
* `fill timing and price (fill_mode)`
* `spread and slippage`
* `SL/TP evaluation and outcome`
* `commission and margin`
* `position identity and lifecycle`
* `balance, equity, drawdown and all metrics`

The strategy owns: intent only: direction, size, protective levels, reason.

### Validation and the trust boundary

`observa validate-strategy FILE [--class NAME] [--json] [--smoke]` runs three tiers:

* **A** — structural: parses, lifecycle methods visible in the AST; never executes user code
* **B** — imported: class resolves, signatures compatible, on_bar genuinely overridden; never calls on_bar
* **C** — smoke: real Engine over 6 bundled bars, validating the RAW on_bar return; shape/integration only

What actually runs at each tier:

| Tier | What runs |
| --- | --- |
| A | parses source only; does not import or execute the strategy |
| B | IMPORTS the strategy module - top-level Python code may execute |
| C | EXECUTES on_bar() through the real Observa Engine |

| Property | Value |
| --- | --- |
| sandboxed | `false` |
| trusted code only | `true` |

**WARNING: validate-strategy is not a sandbox. Tier B imports the strategy module, which may execute top-level Python code. Tier C additionally executes the strategy's on_bar() through the real Observa Engine. Only validate strategy code you trust.**

Validation does not change `observa.run` semantics, and it proves shape and integration only — not:

* strategy logic or profitability
* margin, SL/TP distance, or quantity validity (engine order_rejected events)
* that any signal will ever be produced - zero signals in six bars is valid
<!-- END GENERATED: strategy-contract -->

## Validation

> ⚠️ **Security — validation is not a sandbox.** Tier B **imports the strategy
> module**, which may execute top-level Python code, and Tier C additionally
> **executes the strategy's `on_bar()`** through the real Observa Engine. Only
> validate strategy code you trust.

`observa validate-strategy FILE [--class NAME] [--json] [--smoke]` runs three
tiers and reports structured, repairable errors:

* **A — structural** (parses the source only; does not import or execute the
  strategy): classes and lifecycle methods visible in the AST.
* **B — imported** (imports the module — top-level Python code may execute; no
  engine run and `on_bar` is never called): class resolves, callables and
  signatures are compatible, `on_bar` is genuinely overridden rather than
  inherited from `observa.Strategy`.
* **C — smoke** (real Engine over 6 bundled bars — **executes `on_bar()`**):
  validates the **raw** value returned by `on_bar` before the engine ignores or
  normalises it. Shape and integration only — never a claim about strategy logic
  or profitability, and a strategy that emits zero signals in six bars is still
  valid.

Exit codes: `0` valid, `1` invalid strategy, `2` usage/setup error. With
`--json`, stdout is JSON only.

Validation does **not** change `observa.run` semantics: the engine keeps its
historical behaviour, including silently ignoring unknown signal keys. The
validator exists so an agent does not *rely* on that leniency. Margin, SL/TP
distance, quantity ranges and ticket existence in future states remain the
Engine's business and surface as `order_rejected` events.

## Annotations (drawings)

Types, the 256-per-bar limit, id/time rules and the `DRAWING_*` codes are in the
generated block above and in `observa.agent_spec()["drawings"]`. Recipes and
worked examples: `docs/agent/strategy-authoring.md` and `llms-full.txt` §E2.

## Config and execution semantics

`observa.Config` fields, fill modes (`bar_close` / `next_bar_open`), spread,
slippage, SL-first evaluation, commission modes and margin:
`docs/execution-model.md`.

## Reading a persisted run

`observa.inspect_run(run_dir)`, `observa.run_summary(run_dir)`, and the
read-only MCP server (`observa mcp --runs-dir …`): `docs/MCP.md` and
`llms-full.txt` §K2/K3.

## Error codes

`observa.agent_spec()["error_codes"]` lists the authoring, drawing and runtime
codes. `observa.errors.ERROR_CODES` is the enumerable runtime set, and every
exception raised by Observa carries `exc.code` and `exc.details` — branch on
`exc.code`, never on exception message text.
