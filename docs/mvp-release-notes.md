# Observa 0.1.3 — Private MVP (Release Notes)

> Status: **private MVP tester build**. Not production-ready. This build is for
> a small, invited cohort to validate the core product idea: **seeing what a
> backtest actually did, bar by bar, from the canonical event history.**

## What Observa does

Observa runs a strategy backtest once on the canonical Rust Engine and records
an ordered event history of exactly what happened — what the strategy saw,
which orders were created/pending/filled/rejected/expired, which exact
position opened and closed, why SL/TP fired (at what price), and what happened
to balance and equity each bar. It then replays that history visually so you
can inspect *why* the backtest behaved that way instead of trusting final
numbers.

## Install

Published as a private-MVP GitHub Release (prerelease) tagged
`observa-0.1.3-private-mvp`. The release workflow builds the wheel, verifies
the package version, runs the canonical deterministic baseline plus the
annotation/deterministic-identity, structured-inspection, strategy-reason and
MCP smoke checks, records the SHA-256, and uploads the wheel together with the
example scripts.

The published wheel and its SHA-256:

Wheel URL: `https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl`
SHA-256: `PENDING` — published by the release workflow with the 0.1.3 asset;
read the exact value from the GitHub Release page before installing.

0.1.3 is the current tester build. Do **not** `pip install observa` (an
unrelated PyPI package owns that name).

MCP support is an **optional extra**. The extra always attaches to a wheel
reference, never to a bare package name:

```bash
# core wheel (zero third-party dependencies):
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl"

# same wheel + the official MCP SDK:
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"

# from a downloaded wheel file:
python -m pip install "./observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"
```

Real-data example dependency: `python -m pip install yfinance pandas`.

**Notebook users:** restart the notebook kernel after installing/replacing
Observa before `import observa`.

Import test:

```python
import observa
print(observa.__version__)   # 0.1.3
```

## Verified platform

| Item | Value |
| --- | --- |
| OS | Linux x86_64 (glibc >= 2.34) |
| Python | CPython 3.13 runtime-verified; abi3 metadata supports Python >= 3.10 |
| Wheel | `cp310-abi3`, `manylinux_2_34` |

Windows, macOS and Google Colab are **not** runtime-verified for this build.

## What is new in 0.1.3

### A. Structured run inspection: `observa.inspect_run(...)`

A persisted run is now a first-class Python object. `observa.inspect_run(dir)`
eagerly parses the canonical artifacts, validates them, and returns a
`PersistedRun` with indexed lookups:

| Surface | Purpose |
| --- | --- |
| `meta` / `metrics` | run metadata and canonical metrics |
| `events()`, `event(seq)` | the canonical event history, in canonical order |
| `bar(index)` | OHLC plus the decisions, reasons and drawings for that bar |
| `positions()`, `position(id)` | position summaries and full lifecycles |
| `order(seq)` | one order, including the position it opened or closed |
| `trades()`, `rejections()` | canonical trade and rejection histories |

Lookups are backed by indexes built once at parse time, so inspecting a run is
cheap and deterministic. Bar attribution uses the canonical chronology buckets
— the same bucketing the engine used when it recorded the events. Inspection is
strictly read-only: it never re-runs a strategy and never writes to a run
directory.

### B. Strategy decision reasons are persisted

A signal may now carry an optional human-readable reason. Reasons are recorded
on the canonical `strategy_decision` event as
`signals: [{signal_index, reason}]`, so replay and inspection can show *why*
each signal fired rather than only that it fired. Reasons are capped at 1024
bytes per reason; an over-long reason is rejected with the machine-readable
code `STRATEGY_REASON_TOO_LONG`. Reasons are descriptive only — they never
influence order creation, fills, pricing, SL/TP, portfolio accounting, metrics
or chronology.

### C. Exact closing-order linkage

When a position is closed by an explicit trading ticket, the exact canonical
order that closed it is now recorded as `PositionClosed.order_seq` and
navigable in both directions:

```python
run.position(position_id)["closing_order"]        # the closing order, or null
run.order(order_seq)["position_id"]               # the position it closed
```

Two precisions matter:

* **A closing order is recorded whenever one exists.** Explicit-ticket closes
  carry it.
* **Protective SL/TP exits do NOT have synthetic closing orders.** A stop-loss
  or take-profit exit is not a ticket and no order is invented for it; those
  closes report `closing_order = null` by design.
* **Historical Signal closes created before this linkage existed may also
  report `closing_order = null`**, because the linkage was simply not recorded
  in those artifacts. The inspector never guesses one.

Inconsistent or dangling linkages are refused eagerly with
`RUN_ARTIFACTS_INVALID` rather than resolved heuristically.

### D. Read-only MCP inspection server

Observa now ships an MCP server so an external agent can interrogate persisted
runs without learning the artifact formats:

```bash
observa mcp --runs-dir runs/
# equivalently:
python -m observa.mcp_server --runs-dir runs/
```

```jsonc
// generic MCP client configuration (stdio)
{ "command": "observa", "args": ["mcp", "--runs-dir", "/abs/path/to/runs"] }
```

Ten read-only tools are exposed: `list_runs`, `get_run_summary`, `list_events`,
`get_event`, `get_bar`, `list_positions`, `get_position`, `get_order`,
`list_trades`, `list_rejections`.

It is a thin adapter over `observa.inspect_run(...)` and
`observa.run_summary(...)`: it never runs a strategy, never writes to a run
directory, and never infers anything. Transport is **stdio only** — there is no
HTTP or SSE server. The server is scoped to a single runs root; runs are
addressed by their path relative to it, escape attempts are refused, and
answers never expose absolute filesystem paths. All human-facing output goes to
stderr, so stdout carries only protocol traffic. Full reference and security
model: `docs/MCP.md`.

### E. Optional `observa[mcp]` dependency

The MCP server lives behind an optional extra, so the base package keeps its
zero-dependency install:

```
Requires-Dist: mcp>=2.2,<3 ; extra == 'mcp'
```

The base wheel declares **zero unconditional runtime dependencies**; installing
it without the extra pulls in no MCP stack at all, and `import observa` never
loads the MCP SDK. `observa mcp` without the extra fails cleanly with the exact
install hint instead of a traceback.

### F. MCP CI and release gates

Branch CI and the release workflow both gate on the MCP contract. The release
workflow installs the **exact wheel it is about to publish** with the `[mcp]`
extra in an isolated venv and requires the 107-check MCP contract suite to pass
before the GitHub Release step — which remains the final step — can run.

### G. Historical-run compatibility

Every improvement above is additive and backward-compatible. Runs persisted by
0.1.0–0.1.2 still load, inspect and replay with no migration and no rewriting:

* pre-reason runs simply expose no `signals` key;
* pre-closing-link runs report `closing_order = null` rather than a guess;
* historical UUIDv4 position ids remain readable, and new runs use UUIDv5.

## Intentionally deferred

Not in this build:

* a shaded **band** primitive (multi-point shaded region)
* **arbitrary multiple** panes (only one secondary pane is supported)
* **MCP over HTTP/SSE**, remote or multi-user MCP hosting (stdio only)
* **cloud** execution/hosting
* **AI chat** inside the product
* **optimization** / parameter search
* **live trading**

## What is included

* `observa` Python API (`Config`, `Strategy`, `run`, `RunResult`, …)
* structured run inspection (`observa.inspect_run`, `observa.run_summary`)
* read-only MCP inspection server (optional `observa[mcp]` extra, stdio only)
* bundled deterministic sample data + a small sample strategy
* local visual replay (`observa replay <run-dir>`) — works offline; the chart
  library is bundled
* canonical artifacts per run: `run.json`, `events.jsonl`, `metrics.json`
* strategy annotations, continuous series and one secondary pane
* persisted per-signal strategy reasons
* exact closing-order linkage where a canonical closing order exists
* byte-deterministic canonical artifacts

## Getting started

Two quickstart paths:

* **A (bundled sample):** `python examples/quickstart.py`
* **B (real EUR/USD data):** `python -m pip install yfinance pandas` then
  `python examples/ema_observa.py` (one self-contained file).

Full docs: `docs/tester-onboarding.md`, README, `docs/getting-started.md`.

## Known limitations (summary)

Full list: `docs/known-limitations.md`. The two most likely to matter during
testing:

* Bar-based execution (no ticks/partial fills/liquidation modeling).
* During replay, a resting LIMIT/STOP shows `pending` status but not the
  requested trigger/limit price (the canonical event schema does not carry it
  yet). The replay never guesses the price.

## Reporting issues

Use the feedback template: `docs/mvp-feedback.md` (fields + categories), or
open an issue using the `MVP feedback` issue template. Include the diagnostic
snippet from `docs/tester-onboarding.md` §Diagnostics when reporting failures.

## Build (contributors / maintainers only — end users never need this)

```bash
python -m pip install maturin          # requires Rust toolchain
cd python && maturin build --release   # wheel written to python/target/wheels/
sha256sum python/target/wheels/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl
```

Publishing a tester build: push an `observa-<version>-private-mvp` tag; the
`release-wheel` workflow builds the wheel, verifies the version, runs the
deterministic canonical regression baseline plus the annotation/deterministic-
identity, structured-inspection, strategy-reason and MCP smoke checks, records
the SHA-256 and uploads the wheel plus the example scripts as a prerelease.
Then update the install URL + SHA-256 in README / getting-started /
llms-full.txt / tester-onboarding.

## Previous releases (historical)

Observa 0.1.2 — Private MVP remains published and unchanged:

Wheel URL: `https://github.com/ErickNgumo/observa/releases/download/observa-0.1.2-private-mvp/observa-0.1.2-cp310-abi3-manylinux_2_34_x86_64.whl`
SHA-256: `b4c62f0e280fed133e89e5fd1ddbd18cee4fae6c106c831795e1d449c9674d34`

### What is new in 0.1.2

#### A. Strategy annotations are now real and persisted

Strategies can return an optional `drawings` list alongside their signals.
Annotations are **descriptive only** — they never influence order creation,
fills, spread/slippage, SL/TP, margin, portfolio accounting, metrics or
chronology. They are recorded on the single canonical timeline as
`drawings_emitted` events, so replay reconstructs them from canonical history
(no second timeline, no separate `drawings.jsonl`).

Supported public primitives:

| Primitive | Purpose |
| --- | --- |
| `series` | continuous per-bar values (line or histogram), price pane or a separate pane |
| `hline` | horizontal level (POC / VAH / VAL / support / resistance) |
| `line` | straight segment between two points (trend line, channel edge) |
| `rectangle` | price zone (FVG, order block, value area) with optional lifecycle |
| `region` | time window (session, news window, research window) |
| `marker` | strategy marker (signal fired, rejected signal, anomaly) |
| `label` | text callout (above / below / left / right) |

Strategies use `action: "add" | "update" | "remove"` to manage lifecycle. A
strategy that returns no drawings adds **zero** events, so the canonical
no-drawing baseline is unchanged.

#### B. Continuous series can render

`series` primitives carry a value per bar and render as a normal continuous
line (or histogram), for example EMA, VWAP, rolling values, z-score, spread,
or sigma bands. Gaps are handled honestly: a missing value is a gap, never
zero or an interpolated value.

#### C. One secondary strategy pane is available

A `series` may declare `pane: "separate"` to render below the price pane.
This supports studies with a different scale (z-score, spread, oscillator,
volume-like histogram). Exactly one secondary pane is supported; it is created
on demand and released when no annotation series uses it, so normal usage
never leaves an empty pane behind.

#### D. Invalid drawings now fail with machine-readable codes

A malformed annotation fails the run with a coded, actionable error instead of
silently disappearing. Codes are exposed as `exc.code` with structured
`exc.details`, and cover: `DRAWING_TYPE_INVALID`, `DRAWING_FIELD_MISSING`,
`DRAWING_VALUE_INVALID`, `DRAWING_ID_INVALID`, `DRAWING_ACTION_INVALID`,
`DRAWING_PANE_INVALID`, `DRAWING_TIME_INVALID`, `DRAWING_REFERENCE_INVALID`,
`DRAWING_LIMIT_EXCEEDED`.

A drawing timestamp must name a bar that has **already been replayed**: a
future bar is rejected even though the Engine holds the whole dataset, because
that would be an information oracle into the unseen future. `time_end: null`
on a rectangle means "extend right as replay advances" and stays valid.

#### E. Position IDs for new runs are deterministic UUIDv5 values

Position identity no longer uses random UUIDs. A new position id is a UUIDv5
value derived from a fixed Observa namespace and the position's run-local
ordinal (1, 2, 3 …). The ordinal advances only when a position is actually
created, so rejected entries, failed margin checks, invalid orders and closes
never consume one.

The identifier stays a UUID: the same type, the same wire shape, still an
opaque string to strategies, the Python API and the replay frontend. Explicit
ticket closes continue to work unchanged.

#### F. Identical deterministic runs now produce byte-identical artifacts

For the same dataset, config and strategy, a repeated run now produces
byte-identical `events.jsonl`, `run.json` and `metrics.json` — with no
normalization or ignored fields — subject only to user-controlled metadata
such as a different `dataset.source` path string.

This makes runs directly comparable: position *k* in run A is the same ordinal
as position *k* in run B, so run diffs contain only real behavioural
differences.

#### G. Historical UUIDv4 runs remain readable

Runs persisted by 0.1.0/0.1.1 contain random UUIDv4 position ids. They still
load and replay with no migration and no rewriting: the wire type is unchanged
and the loader accepts any UUID version. New runs simply use UUIDv5.



Observa 0.1.1 — Private MVP remains published and unchanged:

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.1-private-mvp/observa-0.1.1-cp310-abi3-manylinux_2_34_x86_64.whl"
```

SHA-256: `9cb10ee386c41b6b8fe5b0ba553894d4a7ff3cafb74ff69b83ae0d3a65a26cf8`

0.1.1 added the agent/notebook interface (`observa.replay(..., block=False)`,
`ReplayServer`, `result.summary()`, `observa.run_summary()`, machine-readable
`exc.code`/`exc.details`) and a free-port default for `observa replay`; there
were no engine or economic changes.

Observa 0.1.0 — Private MVP remains published and unchanged:

```bash
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.0-private-mvp/observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl"
```

SHA-256: `8367263b786243e0fd89d289cb8a9df1cf1e0ec961316697c95d36f2605fc23c`

The 0.1.0 example assets still print the old fixed `localhost:7878` replay
hint, which matches the 0.1.0 wheel.
