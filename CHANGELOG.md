# Changelog

Release notes with full details live in `docs/releases/`. Wheels are attached
to the GitHub releases (`observa-<version>-private-mvp`).

## 0.2.0 — 2026-10-16

Trustworthy results: loud failures instead of silent ones, fast long runs, and
strategy metrics that state their assumptions. Execution and economics are
unchanged for valid inputs. Contains intentional contract tightenings — see
the upgrade table in [docs/releases/observa-0.2.0.md](docs/releases/observa-0.2.0.md).

- Metrics schema 2 (`docs/metrics.md`): no guessed annualisation for intraday
  bars (`bars_per_year`), returns over < 1 year not annualised, undefined
  metrics `null` with a reason, recorded assumptions and sample sizes, new
  risk / trade / exposure / cost metrics, fixes to the return base and
  break-even trades.
- Replay metrics view redesigned: grouped figures, total vs annualised labels,
  sample and assumption strip, unavailable reasons, trade-outcome chart, cost
  breakdown, legacy-run labelling, mobile layout.
- Unknown signal/config keys and malformed `on_bar` returns fail with
  `SIGNAL_FIELD_UNKNOWN` / `STRATEGY_RETURN_INVALID` / `CONFIG_INVALID`.
- Market data validated identically on all input paths; timezone-less and
  millisecond timestamps rejected; `bar["timestamp_ms"]` added (#8).
- `history` is a read-only O(1) view: 100k bars in ~2 s (#6).
- `Config.tick_size` / `pip_size` (#5).

## 0.1.6 — 2026-10-09

Replay workspace redesign. See [docs/releases/observa-0.1.6.md](docs/releases/observa-0.1.6.md).

## 0.1.5 — 2026-09-21

Integrated user-facing product experience and a bundled real EUR/USD demo.

## 0.1.4 — 2026-09-19

Private MVP tester release.

## 0.1.3 — 2026-09-19

Private MVP tester release.
