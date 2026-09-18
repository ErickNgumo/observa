# Observa 0.1.2 — Private MVP (Release Notes)

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
`observa-0.1.2-private-mvp`. The release workflow builds the wheel, verifies
the package version, runs the canonical deterministic baseline plus the
annotation and deterministic-identity smoke checks, records the SHA-256, and
uploads the wheel together with the example scripts.

The exact wheel URL and SHA-256 for 0.1.2 are recorded here once the release
asset has been published by that workflow:

<!-- The two lines below are replaced with the real published values. -->
Wheel URL: `PENDING_RELEASE_WHEEL_URL`
SHA-256: `PENDING_RELEASE_SHA256`

Until that asset exists, the current installable tester build is 0.1.1 — see
*Previous releases* below. Do **not** `pip install observa` (an unrelated PyPI
package owns that name).

Real-data example dependency: `python -m pip install yfinance pandas`.

**Notebook users:** restart the notebook kernel after installing/replacing
Observa before `import observa`.

Import test:

```python
import observa
print(observa.__version__)   # 0.1.2
```

## Verified platform

| Item | Value |
| --- | --- |
| OS | Linux x86_64 (glibc >= 2.34) |
| Python | CPython 3.13 runtime-verified; abi3 metadata supports Python >= 3.10 |
| Wheel | `cp310-abi3`, `manylinux_2_34` |

Windows, macOS and Google Colab are **not** runtime-verified for this build.

## What is new in 0.1.2

### A. Strategy annotations are now real and persisted

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

### B. Continuous series can render

`series` primitives carry a value per bar and render as a normal continuous
line (or histogram), for example EMA, VWAP, rolling values, z-score, spread,
or sigma bands. Gaps are handled honestly: a missing value is a gap, never
zero or an interpolated value.

### C. One secondary strategy pane is available

A `series` may declare `pane: "separate"` to render below the price pane.
This supports studies with a different scale (z-score, spread, oscillator,
volume-like histogram). Exactly one secondary pane is supported; it is created
on demand and released when no annotation series uses it, so normal usage
never leaves an empty pane behind.

### D. Invalid drawings now fail with machine-readable codes

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

### E. Position IDs for new runs are deterministic UUIDv5 values

Position identity no longer uses random UUIDs. A new position id is a UUIDv5
value derived from a fixed Observa namespace and the position's run-local
ordinal (1, 2, 3 …). The ordinal advances only when a position is actually
created, so rejected entries, failed margin checks, invalid orders and closes
never consume one.

The identifier stays a UUID: the same type, the same wire shape, still an
opaque string to strategies, the Python API and the replay frontend. Explicit
ticket closes continue to work unchanged.

### F. Identical deterministic runs now produce byte-identical artifacts

For the same dataset, config and strategy, a repeated run now produces
byte-identical `events.jsonl`, `run.json` and `metrics.json` — with no
normalization or ignored fields — subject only to user-controlled metadata
such as a different `dataset.source` path string.

This makes runs directly comparable: position *k* in run A is the same ordinal
as position *k* in run B, so run diffs contain only real behavioural
differences.

### G. Historical UUIDv4 runs remain readable

Runs persisted by 0.1.0/0.1.1 contain random UUIDv4 position ids. They still
load and replay with no migration and no rewriting: the wire type is unchanged
and the loader accepts any UUID version. New runs simply use UUIDv5.

## Intentionally deferred

Not in this build:

* a shaded **band** primitive (multi-point shaded region)
* **arbitrary multiple** panes (only one secondary pane is supported)
* **MCP** integration
* **cloud** execution/hosting
* **AI chat** inside the product
* **optimization** / parameter search
* **live trading**

## What is included

* `observa` Python API (`Config`, `Strategy`, `run`, `RunResult`, …)
* bundled deterministic sample data + a small sample strategy
* local visual replay (`observa replay <run-dir>`) — works offline; the chart
  library is bundled
* canonical artifacts per run: `run.json`, `events.jsonl`, `metrics.json`
* strategy annotations, continuous series and one secondary pane
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
sha256sum python/target/wheels/observa-0.1.2-cp310-abi3-manylinux_2_34_x86_64.whl
```

Publishing a tester build: push an `observa-<version>-private-mvp` tag; the
`release-wheel` workflow builds the wheel, verifies the version, runs the
deterministic canonical regression baseline plus the annotation and
deterministic-identity smoke checks, records the SHA-256 and uploads the wheel
plus the example scripts as a prerelease. Then update the install URL +
SHA-256 in README / getting-started / llms-full.txt / tester-onboarding.

## Previous releases (historical)

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
