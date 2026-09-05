# Observa 0.1.0 — Private MVP (Release Notes)

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

```bash
pip install observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
```

(Use the exact wheel filename you were given. A wheel file, not PyPI, is how
this private build is distributed.)

Import test:

```python
import observa
print(observa.__version__)   # 0.1.0
```

## Verified platform

| Item | Value |
| --- | --- |
| OS | Linux x86_64 (glibc >= 2.34) |
| Python | CPython 3.13 runtime-verified; abi3 metadata supports Python >= 3.10 |
| Wheel | `cp310-abi3`, `manylinux_2_34` |

Windows, macOS and Google Colab are **not** runtime-verified for this build.

## What is included

* `observa` Python API (`Config`, `Strategy`, `run`, `RunResult`, …)
* bundled deterministic sample data + a small sample strategy
* local visual replay (`observa replay <run-dir>`) — works offline; the chart
  library is bundled
* canonical artifacts per run: `run.json`, `events.jsonl`, `metrics.json`

## Getting started

Follow `docs/tester-onboarding.md` (five minutes). The same flow appears in
the README and `docs/getting-started.md`.

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

## Build (for the maintainers distributing this build)

```bash
cd python && maturin build --release   # requires Rust toolchain
# wheel written to python/target/wheels/
sha256sum python/target/wheels/observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
```
