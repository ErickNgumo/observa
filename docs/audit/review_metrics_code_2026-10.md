# Code review — metrics schema 2 (release 0.2.0)

Reviewer: independent senior code reviewer · 2026-10-16 · branch `trust-audit-2026-10`
Scope: the uncommitted working-tree changes on top of `0229eb24`: the Rust metrics, the
persistence/binding/CLI wiring, the replay metrics panel, the tests, the fixtures and the docs.
Separate files that are also untracked are **not** in scope: `harness/finance/metrics/*`,
`CHANGELOG.md` and `docs/releases/observa-0.2.0.md`. They belong to the parallel Finance/QA
review and the release notes.

## Verdict: **APPROVE WITH CHANGES**

The metric arithmetic is correct in every case I checked. The economics are untouched:
`events.jsonl` and `run.json` are byte-identical to the released 0.1.6 wheel. Old schema-1 runs
still load everywhere. I found no blocker in the product code.

These items must be done before tagging:

1. **M1:** CI is red. The canonical metrics digest is stale in the current tree.
2. **M2:** the agent-eval Sharpe grader now rejects correct schema-2 output.
3. **m1–m4:** minor robustness and safety fixes that take one line each. They are listed below.

### The tree changed while I reviewed it

The implementer changed `evaluation.rs`, `metrics.js`, `docs/metrics.md`, the tests and the
fixtures while I was reviewing. They were applying the Finance/QA items C1–C3 and C8: a tighter
daily band, a 252/365 calendar check, `warnings`, the leverage rule when equity is ≤ 0, a
break-even tolerance and `cost_scope`. Several findings from my first pass were already fixed
in the later version. For example, 12-hour and 2-day bars labelled `1d` used to get B = 252;
now they are refused.

**This report describes the snapshot taken at 22:01 EAT. I rebuilt the wheel from that snapshot
and re-ran every check.** The sha256 of the main files:

| File | sha256 (prefix) |
|---|---|
| `crates/observa-metrics/src/evaluation.rs` | `81ab785d…` |
| `crates/observa-engine/src/persistence.rs` | `691e732a…` |
| `python/src/lib.rs` | `6b7501cc…` |
| `python/python/observa/static/js/metrics.js` | `5657d4c5…` |
| `python/tests/test_metrics_fixtures.py` | `3cc1399a…` |
| `docs/metrics.md` | `4fb5e841…` |

If any of these files has changed since, re-check M1 and m1 first.

## What I ran (snapshot above, fresh wheel built with maturin into my own venv)

| Check | Result |
|---|---|
| `PYO3_PYTHON=python3.13 cargo test --workspace` | all pass (incl. evaluation unit tests, persistence 20, runtime 35, annotations 8, strategy_reason 14) |
| CI Python scripts (test_observa, annotations, ai_interface, onboarding_ai, demo, inspection 257, strategy_reason, trust_boundary, history_contract, causality, agent_contract 177) | all exit 0 |
| `harness/finance/golden_ledgers.py` | 616 passed, 0 failed |
| `python/tests/test_metrics_fixtures.py` | 75 passed, 0 failed |
| `python/tests/test_canonical_baseline.py` | **exit 1 — 36 passed, 1 failed (`metrics digest stable`)**, see M1 |
| `python/tests/test_mcp.py` | 149 passed, 0 failed (on the final snapshot too) |
| JS: replay, drawings, metrics_panel, workspace | all pass |
| 0.1.6 wheel vs fixed wheel, 3 strategies (canonical EMA 15m; mixed market/limit/stop/SL/TP/hedged/explicit closes in BAR_CLOSE 1h and NEXT_BAR_OPEN daily) | `events.jsonl` and `run.json` **byte-identical** 6/6 (re-run on the final snapshot) |
| Independent Python re-implementation (from the test file) on the two mixed runs above | 32/32 metrics match on each; every null has a reason |
| Edge probes (`probes/edge.py`) | see findings and the "verified" section |
| Real Chromium (playwright) replay: schema-2 run (883 trades), 20k-trade run, legacy 0.1.6 run, failed run, crafted `metrics.json`; desktop 1440×900 and mobile 390×844; all 8 themes | no console errors, no horizontal overflow, no NaN/undefined; see m1 and m2 |

The scripts and outputs are in `/tmp/claude-1000/-home-erick-Documents-observa/8e8c655e-9ac3-4519-a485-898ac80f66b3/scratchpad/review2/`
(`probes/*.py`, `probes/*.js`, `out2_*.log`, `shots/*.png`).

---

## Findings

### Major

**M1 — The canonical metrics digest is stale in the current tree, so CI fails.**
`python/tests/test_canonical_baseline.py:90`.
The `warnings` and `assumptions.cost_scope` keys are new and change `metrics.json`. The pinned
digest was not updated after that change.
```
$ venv/bin/python python/tests/test_canonical_baseline.py
FAIL metrics digest stable :: 1211eff1d5d26d0b2980959dd4f0673ea28c0dd19aa0604f57d540bc72f04f83
36 checks passed, 1 failed            (exit 1)
```
Fix: once the schema-2 key set is frozen, re-pin the digest and say in the commit that it
changed. `docs/engineering/TESTING.md:107-116` still lists the 0.1.6 values: Sharpe
−0.4797, Calmar −0.1185 and digest `6c23dc6c…`. Update that table in the same change. This is
probably just in progress, but a release must not be tagged in this state.

**M2 — The agent-eval grader for T07 now rejects correct schema-2 Sharpe values.**
`harness/agent_eval/grade.py:292-311`.
`_sharpe()` builds returns from snapshot to snapshot (n−1 returns). Schema 2 adds the first
return from the starting balance (n returns), as `docs/metrics.md` specifies. The grader's
tolerance is 1e-6 relative, so every correct T07 run now fails:
```
$ venv/bin/python probes/grade_t07.py
grade.py expected -8.140856251765497 schema-2 got -8.138141512688101 rel diff 0.00033347 passes 1e-6: False
```
Fix: prepend `S` (`Config.starting_balance`) to the equity series in `_sharpe`, or read the
expected value from the documented formula. Then re-run the eval reference solutions. The
product code is correct; the harness is out of date. This is a "must fix before the eval suite
is used on 0.2.0" item.

### Minor

**m1 — A crafted `metrics.json` can inject HTML attributes into replay (script runs on hover).**
`python/python/observa/static/js/metrics.js:159`.
`style="flex:' + v + '"` interpolates the raw JSON value `r[p[0]]`. A string value passes the
`v <= 0` check, because a comparison with NaN is false.
`metrics.json` is not parsed into a typed struct before it reaches replay, unlike events. I
replaced `commission_cost` with `1" onmouseover="window.__pwned=1" x="` in a copied run
directory:
```
$ .venv-dev/bin/python probes/xss.py <chrome>
attrs: ['class', 'style', 'onmouseover', 'x', 'title']
window.__pwned after mouseover: 1
```
The other injected strings were escaped correctly: an `<img onerror>` in an `unavailable`
reason and in `assumptions.currency` did not execute.
Severity is minor because it needs a tampered run directory, and the old `renderMetrics`
already put `r.total_trades` and similar values into the page raw (not a regression). It
should still be closed now.
Fix: `var v = Number(r[p[0]]); if (!Number.isFinite(v) || v <= 0) return '';`. More generally,
coerce every numeric field with `Number.isFinite` before use, or reject a non-numeric metrics
object in `replay::load_persisted_run`.

**m2 — The closed-trade chart freezes the main thread for large runs.**
`metrics.js:127-149`.
Each `<rect>` gets a `<title>` built through `fmtNum` → `toLocaleString`, which is slow. With
20,000 trades, `renderMetrics` takes **2.4–2.7 s** in Chromium; 2.58 s of that is
`tradeOutcomeChart` and only 18 ms is the rest of the panel. `renderMetrics` runs at load and
again every time replay renders the final bar (`events.js:116`). At 600 px wide, 20,000 bars
are each 0.03 px, so the chart carries no visual information at that size.
```
with chart ms: 2680.8   tradeOutcomeChart only ms: 2579.5   without chart ms: 17.8   (19,999 trades)
```
Node: 1k trades 333 ms, 20k 3.9 s, 100k 20 s.
Fix: when there are more than about 600 trades, draw one bar per pixel bucket (min and max of
the canonical values in the bucket, with no new financial figure), or skip the per-rect
`<title>`. Also cache one `Intl.NumberFormat`. Cache the chart HTML per report as well.

**m3 — Gaps in `bars_per_year` validation.**
`python/src/lib.rs:1815-1830`.
I ran each of these:
* `bars_per_year=1e-300` is accepted. Then `years` is about 3e302 and the run reports
  **`annualised_return_pct = 0.0`** as a real value, with the note "bars_per_year = 0". A tiny
  invalid factor silently turns into "0 % per year".
* `bars_per_year=1e300` is accepted. Sharpe is −1.4e149, and the `unavailable` reason prints a
  300-digit number.
* `bars_per_year=True` is accepted as `1.0`, because a Python bool extracts as f64.
* `config={"bars_per_year": nan}` together with `run(..., bars_per_year=252)` is **accepted**.
  The NaN comparison in the conflict check is false, so the invalid config value is silently
  ignored.
* The public Rust API `persist_completed_run` / `derive_metrics_json` does not validate at all.
  By inspection (I did not run this), `Some(0.0)` gives `years = inf`, which passes the
  `y < 1` check and reports CAGR `0.0` and Sharpe `0.0`.

Fix: validate both inputs separately before the conflict check. Reject bools. Require a
plausible range, e.g. `1 ≤ B ≤ 31_557_600` (one-second bars). Repeat the check in
`resolve_annualisation` or `derive_metrics_json` so the Rust API cannot return a fake 0 %.

**m4 — The legacy notice overstates what 0.1.6 did.**
`metrics.js:177-179`.
The notice says annualised figures "assumed 252 bars per year whatever the bar interval". That
is true only for Python runs that left the default. 0.1.6 accepted `run(..., bars_per_year=…)`,
and the agent eval did exactly that (`252*288`). The 0.1.6 CLI hard-coded `4*24*252 = 24192`.
Fix: "…annualisation assumptions were not recorded (the Python API used 252 unless
`bars_per_year` was passed; the CLI used 24 192)…".

**m5 — Several documents still describe the first heuristic.**
* `llms-full.txt:449`: "Daily bars default to 252…"
* `python/python/observa/__init__.py:120` and `:210`: "None uses 252 for daily…"

The current code also infers **365** for daily bars on every calendar day, and refuses
annualisation for other densities and for spans shorter than four weeks with odd calendars.
Agents read `llms-full.txt`. Fix: use the `docs/metrics.md` wording in all three places.

**m6 — `bars_per_year` is recorded only in `metrics.json`.**
`run.json` and `inspect_run` do not show an explicit factor. A run's metrics therefore cannot be
re-derived from `run.json` + `events.jsonl` alone. Finance raised this as C4. I agree, with low
priority.

**m7 — The CLI cannot annualise intraday runs.**
`crates/observa-cli/src/main.rs:697,723`.
The CLI used to hard-code 24192 and now passes `None`, with no `--bars-per-year` flag. CLI
intraday runs therefore always show annualised metrics as unavailable. That is honest but a
regression in what the CLI can do, and it is not mentioned in the docs. Also, `detect_interval`
looks only at the first two bars, so daily data that starts with a two-week holiday gap is
labelled `1w` and then refused. That is conservative and acceptable, but worth a line in the
docs.

### Nits

* **n1** `evaluation.rs:503-510`: if trades exist but none has a known entry bar,
  `avg_holding_bars` gives the reason "no closed trades", which is wrong. The engine cannot
  produce that state today. Use "entry bar unknown for all trades".
* **n2** `evaluation.rs:173` with `None => true`: with fewer than three bars, the spacing check
  is skipped and the default B = 252 applies. Two hourly bars labelled `1d` got 252. This is
  harmless, because nothing annualised can be produced from fewer than 30 returns, but the note
  then claims a daily calendar.
* **n3** `metrics.js:171`: `(r.warnings || []).filter` throws if `warnings` is not an array.
  It did with a hand-edited report:
  `THROWS (r.warnings || []).filter is not a function`. Use `Array.isArray`. Likewise, a
  non-string `unavailable[key]` would throw in `reason.charAt`. The JS test stubs `escapeHtml`
  with a `String(s)` wrapper, which is more lenient than the real function
  (`events.js:455`, `s.replace`). Use the real function in the test.
* **n4** Sharpe and Expectancy appear twice: in the Overview and again in Risk or Trades. This
  is deliberate, but it costs space on mobile.
* **n5** The sample strip's "1.4 years of data" uses calendar days / 365.25, while annualisation
  uses `n / B`. For gappy data the two disagree with no explanation. Finance C2 is now partly
  handled by the density check.
* **n6** `metric-scope` badges are 7.5 px and chip text is 9.5 px. Check the text size against
  the a11y guidelines.

---

## Verified as correct (by running, not by reading)

* **Formulas.** I ran the independent re-implementation on 2 extra runs (hedged, stop/limit
  entries, SL and TP exits, both fill modes; 81 and 99 trades) and it matched exactly.
  Finance's pre-registered harness (564 checks) agrees with this.
* **Edge cases.**
  * 1 bar: the engine refuses it in config validation (`dataset.start must be earlier`), so
    metrics never see n = 1.
  * Flat equity: Sharpe and Sortino are unavailable with "zero" reasons and volatility is 0.
  * Negative equity: return ratios are unavailable, drawdown is above 100 %, leverage is
    unavailable, and a warning is shown. In the mixed daily run equity reached −2952 with 18
    open positions and later recovered.
  * Weekly `1w` gives 52.
  * Weekly data labelled `1d`, daily data labelled `1w`, 12-hour and 2-day bars labelled `1d`,
    and 500 ms bars are all refused with the observed spacing.
  * `24h` is treated as intraday and gets no default.
  * Daily data with a 600-day gap (182 bars per calendar year) is refused.
  * Calendar-daily data gets 365.
  * `"252"` given as a string is rejected with `CONFIG_INVALID`.
  * NaN, inf, 0 and negative values are rejected in both places (test G), and conflicting
    values are rejected.
* **Execution invariance.** Byte-identical `events.jsonl` and `run.json` against 0.1.6 (above).
  `derive_metrics_json` only reads `result.events/trades/fills/bars/final_state`.
  `persist_completed_run` builds the `run.json` object exactly as before.
* **Determinism.** The baseline test's "repeated run reproduces metrics" check passes. All maps
  are `BTreeMap` or serde `Map`; there is no wall clock and no hashing.
* **`RunResult.metrics` equals the persisted `metrics.json`** (test H).
* **Schema-1 compatibility.**
  * `inspect_run`, `run_summary` and `replay_payload` load the committed 0.1.6 run.
  * The MCP functions (`list_runs`, `get_run_summary`) work on the legacy run, a schema-2 run
    and a failed run together (`metrics: null` for the failed one).
  * In Chromium, the legacy run shows the legacy notice and the "(legacy)" labels.
  * No Python package code reads specific metric keys. The only consumers I found that assume
    numbers are the harnesses (`grade.py`, M2; `probe_boundary.py`, informational).
* **Frontend.**
  * No financial computation: the panel formats report values; the trade chart only scales
    canonical `position_closed.net_realized_pnl` values; the cost bar uses report values.
  * Reasons, notes, currency and interval strings are escaped. I tried `<img onerror>` in
    three places and none executed (only m1 did).
  * A failed run shows "No completed-run metrics available."
  * No overflow on mobile.
  * All 8 themes render, including paper and snow (light). The amber "Not annualised" chip and
    the "Read with care" notice are readable on snow (`shots/nofactor-snow.png`).

## Not verified

* Provenance of `python/tests/fixtures/legacy_run_0_1_6`. Its numbers are consistent with the
  0.1.6 formula (`1.0757^(252/600) − 1 = 3.11 %`), but I did not regenerate it.
* The MCP stdio server presentation beyond calling the tool functions directly.
* Windows and macOS; browsers other than Chromium; screen readers.
* The released-wheel comparison for the CLI binary path (`observa-cli` was not run end to end).
* The Rust `Some(0.0)` behaviour in m3 was derived by reading the code, not executed.
* Any change made to the files after the 22:01 snapshot.

---

## Re-review (2026-10-16, 22:20 EAT)

I re-ran everything on a wheel that I built myself from the working tree at 22:20 EAT, using
`maturin build --release` and installing it into `review2/venv`. I did not use the shared
`venv-dev`. I hashed the files I reviewed (sha256 prefixes below); if any of them changes,
this section no longer covers it.

| File | sha256 (prefix) |
|---|---|
| `evaluation.rs` | `5b57fc46` |
| `persistence.rs` | `691e732a` (unchanged) |
| `python/src/lib.rs` | `89af6832` |
| `metrics.js` | `c40ae635` |
| `helpers.js` | `b8e83df5` |
| `events.js` | `08760158` |
| `metrics_panel.test.js` | `c898d8ef` |
| `test_canonical_baseline.py` | `6d36586e` |
| `grade.py` | `7930120e` |
| `docs/metrics.md` | `758e7195` |

### Suites (all run on the rebuilt wheel)

| Check | Result |
|---|---|
| `cargo test --workspace` | all pass |
| CI Python scripts: test_observa, canonical_baseline, annotations, ai_interface, onboarding_ai, demo, inspection, strategy_reason, trust_boundary, history_contract, causality, agent_contract | all exit 0 |
| `test_canonical_baseline.py` | **37 passed, 0 failed** |
| `test_metrics_fixtures.py` | 75 / 0 |
| `harness/finance/golden_ledgers.py` | 616 / 0 |
| `test_mcp.py` | 149 / 0 |
| JS: replay, drawings, metrics_panel (now 7 groups), workspace | all pass |
| 0.1.6 wheel vs rebuilt wheel, same 3 strategies as before | `events.jsonl` and `run.json` **byte-identical 6/6** |

### Status of each finding

| ID | Status | Evidence |
|---|---|---|
| M1 digest / CI | **Resolved** | Baseline passes 37/0. The digest is pinned to `1211eff1…`. `TESTING.md:110-116` now shows the schema-2 values and digest, and explains the 0.1.x numbers. |
| M2 T07 grader | **Resolved** | `_sharpe(eq, ppy, start)` now prepends the starting balance taken from `run.json` → `config.account.starting_balance`. Re-run of my probe: expected −8.138141512688122, got −8.138141512688101, relative difference 2.6e-15, passes. |
| m1 attribute injection | **Resolved** | Same crafted `metrics.json` in Chromium. The string `commission_cost` segment is no longer rendered. The only `on*` attribute inside `#metrics-grid` is the panel's own `BUTTON[onclick=inspectMaxDrawdown()]`. No `<img>` elements; `__pwned`, `__pwned2` and `__pwned3` stay unset after dispatching `mouseover`. `escapeHtml` now coerces with `String()` (`helpers.js:42`); `metricText` and `costChart` coerce with `Number` and check `isFinite`. |
| m2 chart performance | **Resolved** | Chromium, 19,999 trades: full render **138 ms** (was 2,681 ms); `tradeOutcomeChart` 103 ms (was 2,580 ms). Re-rendering the same report takes **0 ms** (guarded by `data-rendered`). The chart is now 2 `<path>` elements and 0 `<rect>`s. No page errors. |
| m3 `bars_per_year` validation | **Resolved** | Rejected with `CONFIG_INVALID`: 1e-300, 0.5, 31,622,401, 1e300, NaN, inf, `True` (as an argument, in a config dict and in `Config()`), `"252"`, NaN in config with argument 252, and −1 in config with argument 252. Accepted: 1, 31,622,400, 252 given twice. `resolve_annualisation` also refuses out-of-range explicit values (`evaluation.rs:85-95`; I read this, I did not run it from Rust). Nit: the rejection message prints the full decimal expansion of 1e300. |
| m4 legacy wording | **Mostly resolved (nit remains)** | The notice now says "the annualisation factor was not recorded. Unless one was passed explicitly, annualised figures used 252…". It still does not mention that persisted runs from the 0.1.6 dev CLI used 24,192. The CLI is not shipped, so I accept this. |
| m5 docs drift | **Resolved** | `llms-full.txt:449` and `__init__.py:120,212` describe the 252/365 calendar rule. |
| m6 factor not in `run.json` | **Declined, documented. Accepted.** | `docs/metrics.md` §"Where the factor is recorded" gives the reason: the factor does not affect the economics, and it is exposed through `metrics.json`, `inspect_run`, `run_summary` and MCP. |
| m7 CLI has no factor | **Declined, documented. Accepted.** | The same docs section says the CLI is development-only and not shipped. |
| n1 holding-bars reason | Resolved | "the entry bar is unknown for every closed trade" (`evaluation.rs:535`). |
| n2 too few bars | Resolved | Note: "daily interval: 252 trading days per year (too few bars to check the spacing or calendar)". |
| n3 JS robustness and test stub | Resolved | `Array.isArray(r.warnings)`; the test loads the real `helpers.js` `escapeHtml`. **Mutation check:** I ran the new `metrics_panel.test.js` against the metrics.js from my first review. The hostile-report, no-re-render and 20,000-trade groups all **fail** there ("reason.charAt is not a function", "re-render skipped", "render took 3325 ms"), so these tests really discriminate. |
| n4 duplicate cards | Not changed | Accepted as a design choice. |
| n5 calendar vs `n/B` years | Addressed | The strip now says "calendar span". |
| n6 font sizes | Resolved | Badge 8.5 px, chips 10.5 px (10 px on mobile). |

### Warnings notice in the browser

I checked it in Chromium at 1440×900 and 390×844 on two runs.

* **15-minute run without a factor:** "Read with care · Not annualised: intraday interval
  '15m'…" (`shots3/nofactor-desktop.png`).
* **Daily NEXT_BAR_OPEN run where equity fell to −2,952:** "Equity fell to or below zero; no
  margin call is modelled…", with B = 365 and the label "default for 1d"
  (`shots3/blown-mobile.png`).

The notice is escaped and wraps without horizontal overflow at both widths. I saw no console
or page errors on any of the seven runs: schema-2, 20k trades, legacy, failed, crafted,
no-factor and blown.

The annualisation probes give the same results as in the first review: 12-hour, 2-day,
mislabelled weekly or daily, 500 ms and gappy daily data are refused; calendar-daily data
gets 365; weekly data gets 52.

### Updated verdict: **APPROVE**

Every major and minor finding is resolved, or declined with a documented reason that I accept.
Two cosmetic nits remain (m4: the CLI is not mentioned; m3: a long number in the error
message). Neither blocks 0.2.0.

Still not verified, as in the first review: where the legacy fixture came from,
non-Chromium browsers and other platforms, and the Rust-only path of `resolve_annualisation`
(read, not executed).

### Addendum, 22:26 EAT

`evaluation.rs` changed again at 22:25:19, after the re-review build. Its sha256 is now
`5a17f2a9`. I rebuilt the wheel from it and re-ran these checks:

| Check | Result |
|---|---|
| `cargo test -p observa-metrics` | 27 passed |
| `test_canonical_baseline.py` | 37 / 0 |
| `test_metrics_fixtures.py` | 76 / 0 |
| `golden_ledgers.py` | 616 / 0 |
| `events.jsonl` and `run.json` vs 0.1.6 | byte-identical 6/6 |
| `bars_per_year` probes | same results as above |
| T07 grader probe | passes |

The verdict stays **APPROVE**. I did not re-run the browser or MCP checks for this
change, because it touches only the Rust metrics file. `metrics.js` and `lib.rs` are unchanged
(`c40ae635`, `89af6832`).
