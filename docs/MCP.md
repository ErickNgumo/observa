# Connect an AI to Observa (MCP)

## What is MCP?

MCP ("Model Context Protocol") is a way for supported AI applications and
coding agents to connect to other software.

For Observa, that means an AI can ask Observa directly about your saved
backtests — instead of you copying results into the chat by hand.

```
Your AI tool
    │
    │ MCP
    ▼
  Observa
    │
    ▼
Saved backtests
```

## Why use it with Observa?

After a backtest, most of the interesting questions are about *details*, not
final numbers. An AI connected through MCP can go and look them up in the saved
run and answer in plain language.

## What can you ask?

- Why did this trade close?
- Show me all rejected orders.
- What happened around this losing trade?
- Which order opened this position?
- How do I write an Observa strategy?

## Is MCP required?

No. Running a backtest, replaying it in the browser, inspecting it from Python
and validating a strategy all work without MCP. MCP is an extra way in, not a
prerequisite.

## Start Observa's MCP server

**MCP support is already included when you install Observa.** There is no second
`pip` command, no extra, and nothing else to enable.

```bash
observa mcp --runs-dir runs/
```

## Connect your AI client

Starting the server and connecting a client are **two separate steps**. The
command above makes the server available on stdio; it does not by itself connect
every AI application.

Client setup differs by application. What any MCP-capable client needs to be
told is the command to launch as a local stdio server:

```bash
observa mcp --runs-dir /path/to/runs
```

A generic (illustrative) client block looks like this — check your own
application's documentation for the exact file and key names:

```json
{
  "mcpServers": {
    "observa": {
      "command": "observa",
      "args": ["mcp", "--runs-dir", "/abs/path/to/runs"]
    }
  }
}
```

## What the AI can access

- how Observa strategies are written (the bundled guide and example)
- the list of saved backtests under the runs root
- trades, orders and positions
- strategy decisions, including the reasons the strategy gave
- rejected orders and why they were rejected
- run metrics and run information

## What the AI cannot do

It cannot run arbitrary strategy code, and it cannot modify, create or delete
your saved runs. Everything it reads is a saved backtest; nothing it does
executes a strategy.

> ⚠️ Do **not** `pip install observa` or `pip install "observa[mcp]"`. The
> public PyPI project named `observa` is unrelated to this wheel. (The `[mcp]`
> extra is still accepted as an empty compatibility alias for older scripts —
> it installs exactly the same thing as the plain wheel.) If you have not
> installed Observa yet, follow the one install command in
> [README.md](../README.md).

If the MCP SDK cannot be loaded, the installation is incomplete rather than
missing an optional component:

```
error: MCP support is included with Observa, but its dependency could not be loaded.
hint: this installation looks incomplete. Reinstall the official Observa release —
      one install provides replay, strategy validation and MCP support.
      See the install instructions in README.md (official GitHub Release wheel).
      Do not run `pip install observa`; that PyPI project is unrelated.
```

---

# Reference

## Transport, startup and scope

stdio transport only (the transport MCP clients spawn locally — no port, no
listener):

```bash
observa mcp --runs-dir runs/
# equivalent:
python -m observa.mcp_server --runs-dir runs/
```

`--runs-dir` is required and is the **only** place the server will look for runs.
The directory **does not have to exist yet**: the server starts with a missing or
empty root so an agent can discover how to author a strategy before any backtest
has been persisted. It never creates the directory. At startup it resolves that
path and prints a one-line banner **to stderr**:

```
Observa MCP
Runs root: /abs/path/to/runs
Tools: 13 (10 inspection, 3 authoring)
```

While the root is absent, the authoring-discovery tools work normally and every
run-scoped inspection tool reports the coded `RUN_DIR_NOT_FOUND`.

stdout is reserved exclusively for the MCP protocol stream, so the server is
safe to launch as a subprocess.

### Generic MCP client configuration

Client setup differs by application; the block below is an illustrative generic
shape, not a verified configuration for a specific product. Confirm the exact
file and key names against your own application's documentation.

```json
{
  "mcpServers": {
    "observa": {
      "command": "observa",
      "args": ["mcp", "--runs-dir", "/abs/path/to/runs"]
    }
  }
}
```

Any MCP host that can launch a stdio server works with that block; substitute
`python -m observa.mcp_server` for the command if `observa` is not on `PATH`.

---

## Run inspection

Ten read-only tools. Every tool except `list_runs` takes an explicit `run`
identifier; there is no implicit "current run".

| Tool | Purpose |
| --- | --- |
| `list_runs()` | Valid runs under the runs root, with per-run errors |
| `get_run_summary(run)` | Persisted `run.json` / `metrics.json` facts |
| `list_events(run, ...)` | Canonical events, filtered and paginated |
| `get_event(run, event_seq)` | One canonical event |
| `get_bar(run, bar_index)` | Everything canonical recorded for a bar |
| `list_positions(run, open?)` | Position summaries (`open = null/true/false`) |
| `get_position(run, position_id)` | One position's full lifecycle |
| `get_order(run, order_seq)` | One order's lifecycle |
| `list_trades(run)` | Completed canonical trades |
| `list_rejections(run)` | Rejected orders plus what was rejected |

### Common questions

| Question | Call |
| --- | --- |
| What runs are available? | `list_runs()` |
| Summarise this run. | `get_run_summary(run)` |
| List all trades. | `list_trades(run)` |
| Inspect position X. | `get_position(run, pid)` |
| Which exact order closed this position? | `get_position(run, pid)["closing_order"]` |
| Inspect order Y. | `get_order(run, seq)` |
| Why was order Y rejected? | `get_order(run, seq)["rejected"]` |
| What happened on bar N? | `get_bar(run, n)` |
| What strategy reason was recorded? | `list_events(run, bar_index=n, event_type="strategy_decision")` |
| What annotations were present at entry? | `get_position(run, pid)["annotations_at_entry"]` |

### `list_events` filters and pagination

Filters mirror the Python API exactly and combine with AND semantics:
`event_type`, `event_seq`, `bar_index`, `position_id`, `order_seq`,
`start_event_seq`, `end_event_seq`. `bar_index` uses canonical
chronology-bucket attribution, so it returns exactly `get_bar(run, n)["events"]`.

`limit` defaults to **100** and is clamped to **1000**. `cursor` means *start
strictly after this `event_seq`* — the canonical ordering key, so pages are
deterministic.

```jsonc
{
  "run": "sample", "total": 4862, "returned": 1000, "limit": 1000,
  "next_cursor": 999, "events": [ /* ascending event_seq */ ]
}
```

`total` counts everything matching the filters *ignoring* the cursor.
`next_cursor` is `null` only when the result is complete, so truncation is never
silent. Walking pages with `next_cursor` reproduces the full filtered result
exactly — no gaps and no duplicates.

### Output shape

Every tool returns a JSON **object** (never a bare list), for example
`{"run": "...", "count": 47, "trades": [...]}`. List payloads are nested under
a named key, which keeps a result in a single structured block.

---

## Authoring discovery

Three read-only tools let an MCP-only agent learn how to write an Observa
strategy without a repository checkout, a network fetch, or a human pasting
documentation. They return the **same canonical assets that ship inside the
installed wheel** (`observa.agent_spec()`, `observa.agent_example_path()`,
`observa.agent_guide_path()`) — nothing is generated or reworded.

| Tool | Purpose |
| --- | --- |
| `get_strategy_contract()` | The canonical machine-readable contract, exactly `observa.agent_spec()` |
| `get_strategy_example()` | The bundled gold example source |
| `get_strategy_guide()` | The bundled concise authoring guide |

None of them takes an argument.

```jsonc
// get_strategy_contract() — returned verbatim; it already carries both versions
{
  "strategy_api_version": "1",
  "observa_version": "0.1.4",
  "lifecycle": { ... }, "signals": { ... }, "drawings": { ... },
  "execution_rules": { ... }, "forbidden_patterns": [ ... ],
  "validation": { ... }, "installation": { ... }
}

// get_strategy_example() / get_strategy_guide()
{
  "strategy_api_version": "1",
  "filename": "example_strategy.py",   // basename only — never an absolute path
  "source": "<exact bundled file text>"
}
```

The `source` field is byte-identical to the bundled file. Each call returns one
object in one content block; the contract is ~10 KB and is deliberately **not**
paginated.

What these tools are **not**:

- they do **not** generate, write or save a strategy — the agent writes code;
- they do **not** validate strategy code;
- they do **not** execute anything — no module import, no `on_bar()`, no Engine;
- they do **not** accept a filesystem path or read arbitrary files;
- they do **not** reach the network.

**Validation stays CLI/Python-only.** `observa validate-strategy FILE --smoke`
and `observa.validate_strategy(...)` remain the way to check a strategy; they are
intentionally not exposed over MCP, because Tier B imports the strategy module
(top-level Python may execute) and Tier C executes `on_bar()` through the real
Engine. An agent with shell or Python access should use those directly.

---

## Expected errors

Anticipated failures are **returned as data**, because MCP has no structured
error channel of its own:

```jsonc
{
  "error": {
    "code": "POSITION_NOT_FOUND",
    "message": "no position with position_id='...'",
    "details": {"position_id": "..."}
  }
}
```

The codes are Observa's existing ones — the server invents no MCP-specific
duplicates:

| Code | Meaning |
| --- | --- |
| `RUN_DIR_NOT_FOUND` | Unknown `run`, a path refused by the root policy, or an absent/unusable runs root |
| `RUN_ARTIFACTS_INVALID` | Artifacts present but unreadable/inconsistent |
| `EVENT_NOT_FOUND` | No such `event_seq` |
| `BAR_NOT_FOUND` | No such `bar_index` |
| `POSITION_NOT_FOUND` | No such `position_id` |
| `ORDER_NOT_FOUND` | No such `order_seq` |

Because the failure is returned rather than raised, the protocol-level
`is_error` flag stays `false`. **Clients should inspect `response.error`** for
expected domain failures. Genuinely unexpected exceptions are *not* converted:
they propagate and surface as real MCP tool errors, so a bug stays visible
instead of looking like a plausible answer.

---

## Security model

The server reads only inside one configured runs root.

- A `run` identifier is a **path relative to that root** (for example
  `sample` or `2026-01/morning`). Nested layouts are supported.
- Refused before any filesystem access: non-strings, empty identifiers,
  absolute paths, and any `..` component.
- After joining, symlinks are resolved and the result must remain inside the
  resolved root, so a symlink pointing outside is refused.
- Only directories containing a `run.json` are opened.
- **An escape is indistinguishable from a missing run**: both report
  `RUN_DIR_NOT_FOUND` with the same message, so the server never reveals
  whether a path outside the root exists.
- No tool accepts a filesystem path, and no response contains an absolute
  filesystem path — path-shaped values are made run-relative or reduced to
  basenames. `list_runs` reports the dataset as a bare filename.
- The root is validated **lazily**: it may be absent or empty at startup so
  authoring discovery works before any run exists. The server never creates it,
  and a missing root cannot be used to reach anything — `resolve_run` still
  refuses every candidate and `list_runs` reports the coded
  `RUN_DIR_NOT_FOUND`.
- The three authoring-discovery tools read exactly two fixed package-internal
  assets (`observa.agent_example_path()`, `observa.agent_guide_path()`) plus the
  canonical in-memory contract. They take no path argument, import no strategy
  module and execute no user code.

There is no network listener: stdio only. That is the entire attack surface for
this MVP — no auth, TLS, or remote transport is implemented.

---

## Read-only guarantee

No tool runs a strategy, creates/edits/deletes a run, changes configuration,
adds notes, or writes anything at all. This is tested: hashing every artifact
before and after a full tool sweep must produce identical hashes and no new
files.

The authoring-discovery tools only **read** two bundled package assets, so a
sweep of all thirteen tools writes nothing and does not create the configured
runs root. None of them imports a strategy module, calls `on_bar`, runs the
Engine, or invokes `validate_strategy`.

---

## Caching and artifact changes

Loaded runs are cached in the server process, keyed by resolved run path, and
never invalidated — persisted runs are treated as immutable. If you change a
run's artifacts, **restart the server** to observe the change. There is no
watcher, no mtime polling and no background refresh.

Cache access is thread-safe, because MCP may execute synchronous tools on
worker threads.

`list_runs` deliberately does **not** populate the cache: discovery reads only
`run.json` / `metrics.json` (about 0.4 ms per run) instead of parsing full event
histories (about 100 ms and 5 MB per run).

---

## Historical compatibility

Nothing is migrated and nothing is required to be current:

- current deterministic UUIDv5 runs and historical UUIDv4 runs;
- runs from before persisted strategy reasons (no `signals` key — read as
  absent, never back-filled);
- runs from before closing-order linkage (`closing_order` is `null`);
- protective SL/TP exits;
- runs with no drawings;
- failed runs (`metrics` is `null`, partial history still available);
- runs whose dataset can no longer be verified (`ohlc` is `null` and
  `ohlc_available` is `false` — no bar is ever fabricated).

### `closing_order` is three-valued

`get_position` passes the persisted linkage through verbatim. Do not blur these:

| `closing_order` | `exit_reason` | Meaning |
| --- | --- | --- |
| dict | `Signal` | The exact canonical closing order was recorded |
| `null` | `StopLoss` / `TakeProfit` | Protective exit — **no order ever existed** |
| `null` | `Signal` | Run predates the linkage — the closing order **was not recorded** |

The server never infers it from side, quantity, timestamp, adjacency or the
opening order.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `MCP support is included with Observa, but its dependency could not be loaded` | The installation is incomplete — reinstall the official Observa release (one install includes MCP). Never use bare `pip install "observa[mcp]"`, which resolves an unrelated PyPI project |
| `RUN_DIR_NOT_FOUND` from `list_runs` or any `run` | The configured `--runs-dir` is absent or not a directory, or the `run` identifier is not relative to it — the authoring-discovery tools still work |
| Every `run` returns `RUN_DIR_NOT_FOUND` | The identifier must be relative to the configured root — check `list_runs()` |
| A run does not appear in `list_runs` | It has no `run.json`, or it lives outside the root; see the `errors` array for unreadable runs |
| Stale numbers after re-running | Restart the server (the cache is never invalidated) |
| `ohlc` is `null` | The dataset is no longer verifiable against its persisted hash; everything else still works |

---

## See also

- [`docs/STRATEGY_API.md`](STRATEGY_API.md) — the Python inspection API this
  server delegates to
- [`llms-full.txt`](../llms-full.txt) §K2 (inspection) and §K3 (MCP)
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §6c/§6d — architectural invariants
