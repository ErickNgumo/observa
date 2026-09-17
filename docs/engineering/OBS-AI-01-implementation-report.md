# OBS-AI-01 — Agent-Ready Core Interface: Implementation Report

Branch: `obs-ai-01-agent-ready-core` (pushed to `origin`, not merged)
Base: `master` @ `c189441a1a69a2f3ff45dc329306b08d0bafc336`
Role: implementation agent. Status: **ready for QA review**.

## 1. Ticket and scope

Make Observa easy for coding agents and notebooks without changing the
canonical engine: one programmatic replay entry point, a non-blocking server
handle, automatic free ports, machine-readable result summaries, and
machine-readable error codes on the existing exception classes.

Explicitly out of scope (and not implemented): MCP, chatbot, cloud,
orchestration, parameter optimization, frontend/drawing redesign, live
trading, remote replay, authentication, PyPI publishing.

## 2. Commit map

| commit | content |
| --- | --- |
| `f1bf76e2` | machine-readable error codes + `RunResult.summary()` (Rust binding) |
| `91a62f5f` | `observa.replay(...)` entry point, `ReplayServer`, CLI auto/strict ports, `run_summary()` |
| `7223c0e2` | `python/tests/test_ai_interface.py` (76 checks) + CI wiring |
| `1010fe4c` | README / getting-started / CURRENT_STATE / llms-full.txt / examples / prompt docs |

No merge to `master`; no force-push.

## 3. Deliverables

1. `observa.replay(run_dir_or_result, *, port=None, block=True, open_browser=False)`
   — the single canonical programmatic replay entry point.
2. `ReplayServer` for `block=False`: `.url`, `.port`, `.run_dir`,
   `.is_running`, idempotent `.stop()`, context manager, daemon thread.
3. Automatic free port (`port=None` → bind port `0`) with no TOCTOU probe;
   explicit ports are strict.
4. CLI `observa replay <dir>`: auto port by default, `--port N` strict,
   concise coded error + exit `2` on collision, prints the actual URL, never
   opens a browser.
5. `result.summary()` and `observa.run_summary(run_dir)`.
6. `exc.code` / `exc.details` on the existing exception classes and
   `observa.error_code(exc)`.

## 4. Replay entry-point contract

`python/python/observa/__init__.py::replay`:

* `RunResult` overload is detected via `artifact_dir`/`summary`; an
  unpersisted result raises `ValueError` with code
  `REPLAY_RUN_NOT_PERSISTED` (message points at `output=`/`result.save`).
* A path-like argument is treated as a run directory.
* `port` is validated (`int`, `1..65535`) → `ValueError` code
  `REPLAY_PORT_INVALID` with `details["port"]`.
* `block=True` keeps the historical blocking behavior and returns `None`.
* `block=False` returns a running `ReplayServer`.
* `open_browser=False` by default; a browser is opened only when requested.

## 5. Non-blocking server

`python/python/observa/replay.py::ReplayServer` wraps a `ThreadingHTTPServer`
on a daemon thread named `observa-replay`. `stop()` is idempotent and joins
with a timeout; `__exit__` calls `stop()`; `is_running` is false after stop.
`run_dir` is the resolved absolute path (stable regardless of cwd).

Fail-fast before binding any socket: missing `run.json` →
`FileNotFoundError` `REPLAY_RUN_NOT_FOUND`; missing `events.jsonl` →
`ValueError` `REPLAY_ARTIFACTS_INVALID`.

## 6. Port semantics

* `port=None`: `ThreadingHTTPServer(("127.0.0.1", 0), ...)` — the OS assigns
  the port atomically, so concurrent servers cannot collide and no
  probe-then-bind race exists. The actual port is read back from
  `server_address`.
* Explicit `port`: `EADDRINUSE` becomes `OSError` with
  `code="REPLAY_PORT_IN_USE"` and `details={"port": N}` and a message that
  recommends `port=None`. Replay never silently falls back to another port.

## 7. CLI

`python/python/observa/cli.py` (`observa = observa.cli:main`):

* `--port` default is `None` (auto); this is an intentional, documented
  behavior change from the old fixed 7878.
* Busy explicit port → one-line stderr message + hint, no traceback, exit `2`.
* Missing/invalid port value and out-of-range ports → exit `2`.
* The bound URL is printed with `flush=True` so it is visible when stdout is
  piped (agent/notebook capture).
* No browser is opened.

## 8. Result summaries

`RunResult.summary()` returns exactly:
`status, artifact_dir, total_bars, trades, open_positions, final_balance,
final_equity, events, metrics, dataset_source, run_schema_version`
(`status` is `"completed"` for a `RunResult`; there is no `RunResult` for a
failed run). Arrays are summarised by count only — no duplication.
`metrics` is produced by the unchanged `metrics_value` formula, now memoised
in `metrics_cache: RefCell<Option<Value>>` so repeated reads do not recompute.

`observa.run_summary(run_dir)` reads only `run.json` and `metrics.json`:
missing directory/`run.json` → `RUN_DIR_NOT_FOUND`; unreadable JSON →
`RUN_ARTIFACTS_INVALID`; failed runs report `status="failed"`, `error`, and
`metrics=None`/`trades=None`.

## 9. Error codes

Attached to the existing classes (no new hierarchy, no message parsing):
`CONFIG_INVALID`, `DATA_INVALID`, `DATA_FILE_NOT_FOUND` (`details.path`),
`STRATEGY_ERROR` (`details.message`, `details.bar_index` when known),
`ENGINE_ERROR`, `RUN_OUTPUT_EXISTS` (`details.path`), `RUN_PERSIST_FAILED`,
`RUN_DIR_NOT_FOUND` (`details.path`), `RUN_ARTIFACTS_INVALID`
(`details.path`), `REPLAY_RUN_NOT_FOUND` (`details.path`),
`REPLAY_ARTIFACTS_INVALID` (`details.path`, `details.line` for a bad
`events.jsonl` line), `REPLAY_PORT_IN_USE` (`details.port`),
`REPLAY_PORT_INVALID` (`details.port`), `REPLAY_RUN_NOT_PERSISTED`.

Class preservation: missing data stays `FileNotFoundError`, existing output
stays `FileExistsError`, config/port errors stay `ValueError`, port collision
stays `OSError`. `observa.error_code(exc)` returns `.code` or `None`.
`/api/replay` failures return JSON `{error, code, details}` with status 500.

## 10. Rejections are still events

No rejection path was converted to an exception. Invalid SL/TP, oversized
quantity and insufficient margin remain canonical `order_rejected` events in
`result.events`; the run completes. Verified by test I in the new suite.

## 11. Files changed

* `python/src/lib.rs` — coded error mapping, `strategy_err`, `summary()`,
  metrics cache, `save(py, …)`.
* `python/python/observa/errors.py` (new) — `ERROR_CODES`, `error_code`,
  `coded`.
* `python/python/observa/replay.py` — `ReplayServer`, `_bind`, `serve`,
  fail-fast artifact checks.
* `python/python/observa/cli.py` — auto/strict ports, coded concise errors.
* `python/python/observa/__init__.py` — `replay()`, `run_summary()`, exports.
* `python/tests/test_ai_interface.py` (new) — 76 checks.
* `.github/workflows/ci.yml` — runs the new suite.
* Docs: `README.md`, `docs/getting-started.md`, `docs/CURRENT_STATE.md`,
  `docs/tester-onboarding.md`, `llms-full.txt`, `prompts/implement-strategy.md`,
  `examples/{quickstart,ema_observa,rsi_mean_reversion,ai_starter/*}`.

## 12. Test evidence

| command | result |
| --- | --- |
| `cargo test --workspace` | 228 passed, 0 failed |
| `cargo build --workspace` | ok |
| `node python/tests/replay.test.js` | 16/16 groups |
| `.venv-ai/bin/python python/tests/test_observa.py` | 15/15 |
| `.venv-ai/bin/python python/tests/test_ai_interface.py` | 76 checks, 0 failed |
| `.venv-ai/bin/python python/tests/test_onboarding_ai.py` | all checks pass |

The new suite runs against the installed candidate wheel and covers: free-port
and concurrent servers, coded collision, lifecycle/idempotent stop, port reuse
after stop, missing/incomplete artifacts, unpersisted result, `summary()`
shape and value parity with getters, `run_summary()` for completed/failed/
missing/malformed runs, all error codes, rejection-as-event, CLI auto + busy +
free explicit ports, and the notebook non-blocking flow.

Local environment note: the default `python3` here is 3.14, newer than
PyO3 0.22.6's maximum. `cargo test`/`cargo build` were run with
`PYO3_PYTHON=/usr/bin/python3.13` (CI pins 3.12). `maturin build` uses abi3
and is unaffected.

## 13. Non-regression: canonical economics equivalence

`git diff` touches no file under `crates/` — the engine, execution, portfolio,
events, persistence and metrics crates are byte-identical.

Stronger check: a wheel built from the pre-change binding
(`git show HEAD:python/src/lib.rs`) was compared against the candidate wheel
for a canonical run — `data/EURUSD_M15.csv`, `SampleEma`,
`NEXT_BAR_OPEN`, spread `0.0002`, slippage `0.0001`, commission `7.0`
`ROUND_TRIP`, interval `15m`:

* `run.json` — byte-identical
* `metrics.json` — byte-identical
* `events.jsonl` — identical after normalising only per-run UUID identity
  fields (`position_id`/`ticket`); 4883 lines both,

  sha256(normalised) = `58ba370fa34d4eb7af9cc765ab6a2dc4dddfc75831d1c72b663d8e83de32fc4f`

Recorded canonical values after OBS-AI-01:

* 1500-bar `data/EURUSD_M15.csv`: 1500 bars, 4883 events, 47 trades, 1 open,
  `final_balance 8867.996326446711`, `final_equity 9046.968551635922`
* bundled 200-bar sample, same config: 200 bars, 623 events, 2 trades, 1 open,
  `final_balance 12484.0`, `final_equity 13068.99999999999`
  (`fill_mode=BAR_CLOSE` instead gives 618 events — count is config-dependent)

QA note: the scalar baseline carried over from earlier sessions
(1500 bars / 4877 events / 47 trades / `final_balance 8689.465385437186`)
could not be re-derived here; its exact command/config is not recorded
anywhere in the repository. The base-vs-candidate artifact equivalence above
is the stronger and reproducible regression evidence; QA should confirm which
command produced the old scalar before treating it as a gate.

## 14. Build artifact

Candidate wheel built locally only (no publish, no release change):

```
python/target/wheels/observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl
sha256 3554708d7c7f5c8b98b9559df3c9569028c4527fda259b1e053a820db150c4ab
```

This SHA is **new** and intentionally differs from the existing release asset
`observa-0.1.0-private-mvp` (asset sha256
`8367263b786243e0fd89d289cb8a9df1cf1e0ec961316697c95d36f2605fc23c`).
The release and its tag (`observa-0.1.0-private-mvp` @ `ce2b625e`) were not
modified, and no PyPI publish was performed.

## 15. Scope audit

In scope and done: programmatic replay entry point, non-blocking server,
auto/strict ports, blocking preservation, CLI behavior, result/run summaries,
error codes, docs, tests, CI, local candidate wheel.

Not done (out of scope): MCP server, chatbot interface, cloud/remote replay,
orchestration, optimization, frontend redesign, live trading, auth, PyPI
publish, merging the branch.

Canonical invariants preserved: single engine loop, canonical events as
authoritative history, EventSeq/artifact schemas unchanged, economics
unchanged, order rejections remain events.

## 16. Risks / follow-ups

1. **CLI default-port change** (7878 → auto) is a visible behavior change;
   it is documented, and `--port 7878` still works but is now strict.
2. **Example/release divergence**: the immutable release asset
   `ema_observa.py` still prints the old fixed `http://localhost:7878` hint;
   the repository copy now points at the URL the CLI prints. A future release
   asset refresh should pick this up.
3. **Metrics caching** stores one derived `serde_json::Value` per result;
   values are identical to the uncached formula (verified by parity tests).
4. **`run_summary` key set** includes `error` in addition to the
   `summary()` keys; documented in the docstrings.
5. The old scalar baseline noted in §13 needs a recorded command before it can
   be used as a QA gate.

Notebook/agent readiness: **YES**.
Ready to merge: **NO** (requires QA).
Proceed to OBS-AI-02: **NO** (waiting for QA outcome).
