# Observa trust audit — October 2026

Status: Phase 1 (evidence) complete; Phases 2–3 recorded in the tickets
`OBS-TRUST-01..03` and in [§7 Results](#7-results).
Auditor: Claude (coding agent) on branch `trust-audit-2026-10`.

This audit treats Observa as a backtester whose product is **trust**, for two
users: humans and AI agents. It looks for **failure classes** (ways Observa
can give a wrong or misleading answer without saying so), not individual
tickets.

Labels used throughout: **[observed]** = reproduced in this audit, with a
command or artifact; **[inferred]** = follows from code reading or
extrapolation, not executed; **[unverified]** = could not be checked here.

---

## 1. Baseline

| Item | Value |
|---|---|
| Commit audited | `c01206f7a99100a8a915314431db7d8852d52218` (master, clean tree) |
| Package version | 0.1.6 (all crates, `pyproject.toml`, `observa.__version__`) |
| Released wheel | `observa-0.1.6-cp310-abi3-manylinux_2_34_x86_64.whl`, sha256 `921a2ebd3f358941f379457c4a84d30fe57cacaab8618fb68ff1a1dcd218cd12` (GitHub release `observa-0.1.6-private-mvp`) |
| Source build | same version, built with maturin 1.x, release profile |
| Machine | Linux 6.12 x86_64 (Debian 13), CPython 3.13.5 and 3.14.7, rustc 1.97.1 |
| Container runtime | Docker CLI present, **daemon not accessible to this user** → "clean environment" = fresh venv + fresh workspace, not a container [limitation] |

Released wheel vs source checkout: every probe and benchmark below states which
it ran on. Canonical event digests from the released wheel (CPython 3.13) and
the HEAD source build (CPython 3.14) are **byte-identical** for the causality
scenario (`python/tests/test_causality.py --print-digests`) [observed], so
HEAD ≡ release economically.

Existing checks at baseline (HEAD wheel, CPython 3.13 and 3.14): 282 Rust tests
pass; 11 Python suites pass (e.g. 257 inspection checks, 177 agent-contract
checks, 33 canonical-baseline checks) [observed].

Environment finding: `cargo test --workspace` **fails to build** `pyo3-ffi`
when the default `python3` is 3.14 (pyo3 0.22.6 supports ≤3.13); it passes
with `PYO3_PYTHON=python3.13` [observed]. The abi3 wheel itself runs on 3.14.

## 2. Evidence sources

1. **Boundary probes** — `harness/audit/probe_boundary.py`, 43 probes run on
   the released wheel → `docs/audit/evidence/probes_released.jsonl`.
2. **Code reading** of the Python↔Rust boundary (`python/src/lib.rs`), the
   engine loop (`crates/observa-engine/src/engine.rs`), bar validation
   (`crates/observa-core/src/bar.rs`), CSV loading, the validator
   (`python/python/observa/validation.py`) and metrics.
3. **Scaling benchmark** — `harness/audit/bench_scaling.py` on the released
   wheel → `docs/audit/evidence/bench_released_py313.jsonl`.
4. **Cold start** — an agent given only README.md and the release wheel URL,
   in a fresh venv → `docs/audit/evidence/coldstart_session_agent_2026-10-16.md`.
   This is an **agent-performed** session (Claude Sonnet); it is **not**
   external human tester feedback.
5. **Agent evaluation** — `harness/agent_eval/` (10 fixed tasks, automatic
   graders, see [§6](#6-agent-evaluation-protocol)).
6. **External failure patterns** — backtesting.py, backtrader, vectorbt,
   NautilusTrader issues/docs, collected by a separate research agent →
   `docs/audit/evidence/external_failure_patterns.md`. Treated as leads only.
7. **Open issues #1–#9** (all filed from one downstream research project).
8. **Independent Finance/QA** golden ledgers and a differential check →
   `harness/finance/` (separate agent, see §7).

## 3. Scoring rubric

* **Severity** (S): 5 = silently wrong economics or a silently dropped risk
  control; 4 = silently wrong/misleading result without changed fills (e.g. a
  "successful" zero-trade run, a mis-scaled metric); 3 = loud blocker of a
  primary workflow; 2 = loud friction / misleading docs; 1 = cosmetic.
* **Reach** (R): 3 = every user of a primary path; 2 = a common subset; 1 = edge.
* **Frequency** (F): *O* observed in practice (filed report or eval
  trajectory), *A* anticipated (maintainers already document it as a trap),
  *U* unknown. Frequency is never estimated without evidence.
* **Priority** = S × R; F breaks ties (O > A > U).

## 4. Findings (released 0.1.6)

| ID | Finding | Kind | Evidence | S | R | F |
|---|---|---|---|---|---|---|
| S01 | Signal key `stop_loss`/`take_profit` (the names the portfolio view itself uses) silently ignored → position opens with **no stop** | silent | probe S01: `position_opened.stop_loss = null`, run completes; `lib.rs` `signal_from_py` reads only 8 keys | 5 | 3 | A (documented as TRAP in spec, guide, STRATEGY_API) |
| S02 | Bare signal dict returned from `on_bar` → ignored, zero orders | silent | probe S02; `lib.rs:784` reads only `signals` from a dict | 4 | 3 | A |
| S03 | `on_bar` returns `None` (forgotten `return`) → treated as "no action" | silent | probe S03 | 4 | 3 | A |
| S04 | Misspelled envelope `{"signal": [...]}` → zero orders | silent | probe S04 | 4 | 2 | A |
| S05 | Validator smoke tier covers 6 bars only, so a conditional signal with a bad key is never observed; `spec.json` lists `SIGNAL_FIELD_UNKNOWN` as warning-only (inaccurate for signals, accurate for envelope keys) | misleading | `validation.py:_RawObserver`, `spec.json.error_codes.warning_only` | 3 | 3 | A |
| C01 | Config **dict** typos (`spred`, `fillmode`, `slipage`) silently ignored → defaults (spread 0.0002, slippage 0.0001) applied | silent | probes C01, C09; `config_from_dict` reads known keys only | 5 | 2 | U |
| C02 | `Config` dataclass lacks `tick_size`/`pip_size` although docs list them (issue #5) | loud | `Config(tick_size=…)` → TypeError | 2 | 1 | O (#5) |
| D01 | NaN/±inf prices accepted on **both** CSV and list paths (`Bar::validate` has no finiteness check) | silent | probe B08; `nan.csv` probe; `bar.rs:104` | 5 | 2 | U |
| D02 | Python list/DataFrame path never calls `Bar::validate` → high<low, close>high, negative prices accepted | silent | probes B09–B11; `lib.rs:bars_from_py` | 5 | 2 | U |
| D03 | Epoch **milliseconds** read as seconds → year 56971, run "succeeds" | silent | probe B04 | 4 | 1 | U |
| D04 | Fractional epoch seconds floored; `True` accepted as epoch 1 | silent | `timestamp_from_py` | 2 | 1 | U |
| D05 | Timezone-less `YYYY-MM-DD HH:MM:SS` silently assumed UTC on the list path but **rejected** on the CSV path | silent / inconsistent | probe B05 vs `naive.csv` probe | 3 | 2 | U |
| D06 | Strategy-facing timestamp is normalized (`Z`→`+00:00`), differs from canonical events (`Z`) and is undocumented → string joins silently miss (issue #8) | silent | probe B01; eval T03 trajectory (agent's first run had 0 trades) | 4 | 2 | **O** (#8, eval) |
| D07 | Extra bar fields silently dropped (issue #1) | silent | probe B17 | 3 | 2 | O (#1) — feature design needed |
| P01 | `history` rebuilt as fresh list of dicts every bar → O(N²); 1k bars 1.9 s, 8k 71.8 s; 100k ≈ 3 h extrapolated | loud (impractical) | bench; `lib.rs:754` | 3 | 2 | **O** (#6, eval T04) |
| M01 | `bars_per_year` defaults to 252 regardless of `interval`; annualised return, Sharpe, Calmar mis-scaled for every non-daily run — including the **shipped demo** (8 days, +6.54 % total → "2.70 % annualised") | misleading | probes C04/C05; `runs/eurusd-demo/metrics.json`; `__init__.py:run` | 4 | 3 | O (demo, eval T07 needed discovery) |
| M02 | `bars_per_year` is not persisted anywhere, so metrics cannot be audited from artifacts | misleading | `run.json`/`metrics.json` | 3 | 3 | O |
| M03 | Declared `interval` is never checked against actual bar spacing | silent | probe C06 | 3 | 2 | U |
| Z01 | Zero-trade runs where every order was rejected look like successes: `summary()` reports no rejection count; default EURUSD contract applied to BTC prices rejects every entry for margin | misleading | probe C03; eval T06 | 4 | 2 | O (eval T06 required event reading) |
| X01 | Cold start: README links are repo-only; README does not name `agent_guide_path()`/`agent_spec()`; demo script not in wheel; `observa.samples` not importable as attribute | loud friction | cold-start log (2 × P2, 8 × P3) | 2 | 3 | O (agent session) |
| E01 | Determinism: byte-identical artifacts across repeated runs and across CPython 3.13/3.14 | — (holds) | `test_causality.py` | — | — | — |
| E02 | No lookahead under future-bar perturbation (40 random cases × 2 fill modes); negative control detects a deliberate leak | — (holds) | `test_causality.py` | — | — | — |

Notes:
* NaN at a fill bar is caught later as `order_rejected` ("entry_price must be
  finite"), and NaN/negative SL/size are rejected at order validation — the
  engine has defence in depth for *orders* but not for *data* [observed].
* Signal typos that miss a **required** key (`quantity` without `size`) are
  already loud (`STRATEGY_ERROR`) [observed]; the silent class is extra keys.
* Hash-map iteration (the NautilusTrader #3914 class) was checked: no
  `HashMap`/`HashSet` in engine code paths [observed by grep].

## 5. Failure classes, ranking and selection

| Class | Members | Priority (S×R) | Frequency | Decision |
|---|---|---|---|---|
| **FC-1 Silent intent loss at the Python boundary** | S01–S05, C01, C02 | 15 | A (documented traps) | **Fix (OBS-TRUST-01)** |
| **FC-2 Silent acceptance / reinterpretation of market data** | D01–D06 | 10 | O (#8) | **Fix (OBS-TRUST-02)**; D07 deferred to #1 |
| **FC-3 Quadratic per-bar history** | P01 | 6 | O (#6) | **Fix (OBS-TRUST-03)** — required by the completion criteria; observed blocker for intraday |
| FC-4 Mis-scaled, unauditable derived metrics | M01–M03 | 12 | O | **Deferred — needs a product decision** (see §8) |
| FC-5 Zero-trade runs look successful | Z01 | 8 | O | Deferred; partly mitigated by FC-1 (the most common causes become errors) |
| FC-6 Cold-start documentation gaps | X01 | 6 | O (agent) | Deferred; small doc fixes listed in §8 |

Why FC-1, FC-2, FC-3 and not FC-4: FC-1 and FC-2 are the only classes that can
silently change **economics** (a missing stop; corrupt prices) and both are
removable without choosing a convention. FC-4 scores high, but every fix
requires a convention the owner must choose (252 vs 365 days; session hours
vs 24 h; derive from timestamps vs from `interval`). Changing a headline metric
by default is a product decision, so this audit records it as Decision 1 with
a recommendation rather than choosing silently. FC-3 is included because it
is an observed blocker with a filed issue and explicit acceptance criteria.

### Issue mapping (verified against the tracker on 2026-10-16)

| Issue | Title (abridged) | Class | Kind | Decision |
|---|---|---|---|---|
| #1 | Release-aware external features | FC-2 (D07) | feature | Defer — needs design (vintage store) |
| #2 | Dividends and splits | — | feature | Defer |
| #3 | Benchmark rates / cash interest | FC-4-adjacent | feature | Defer |
| #4 | Multi-instrument portfolio | — | feature | Defer |
| #5 | `tick_size`/`pip_size` in Config | FC-1 (C02) | doc/API defect | **Fix in OBS-TRUST-01** |
| #6 | Quadratic history | FC-3 | performance defect | **Fix in OBS-TRUST-03** |
| #7 | USDT/USDC currency codes | — | feature (loud today) | Defer — Decision 3 |
| #8 | Timestamp format passed to `on_bar` | FC-2 (D06) | silent defect | **Fix in OBS-TRUST-02** |
| #9 | %-of-notional fees, perpetual funding | — | feature (economics) | Defer — needs Finance design |

## 6. Agent evaluation protocol

`harness/agent_eval/` — fixed before any attempt was run:

* `tasks.py` — 10 task prompts + deterministic synthetic data (seeded,
  stdlib only): SMA cross with SL/TP; two positions closed by ticket; joining
  external predictions by timestamp; a 100k-bar 1-minute run; repairing a
  broken strategy; diagnosing a zero-trade run; intraday Sharpe; a resting
  limit order; inspecting an existing run; a short breakout with SL/TP.
* `grade.py` — grades from canonical artifacts against expectations computed
  **independently from the input data and the task rule** (e.g. SMA crosses
  recomputed from the CSV; Sharpe recomputed from `portfolio_snapshot`
  equity). The grader trusts the Engine only for *when* a position was open.
* Grader self-test (`reference_solutions.py`): reference solutions PASS 9/9;
  deliberately wrong variants (SL off by 1 pip, string-keyed join, exit one
  bar late, wrong annualisation, …) FAIL 9/9 [observed]. T04 is validated on
  the fixed build (too slow on 0.1.6, which is the point).
* Agents: fresh sub-agents with only the workspace, the installed wheel and
  the shipped AGENTS.md (`AGENT_PROMPT.md`). Two arms: Claude Sonnet and
  Claude Haiku. Isolation from the source tree is by instruction, not
  enforced by a sandbox [limitation]. Same model family as the implementer
  [limitation]. One attempt per task per arm (n = 1, so differences of one
  task are within noise) [limitation].

## 7. Results

### What changed (tickets `agent_system/tickets/OBS-TRUST-01..03.md`)

* **OBS-TRUST-01** — unknown signal keys → `SIGNAL_FIELD_UNKNOWN` (with a
  suggestion); `None` / bare dict / unknown envelope keys / missing or
  non-list `signals` → `STRATEGY_RETURN_INVALID`; unknown config-dict keys →
  `CONFIG_INVALID`; `Config.tick_size` / `pip_size` added (#5);
  `strategy_name` type-checked (not recorded — decision 3).
* **OBS-TRUST-02** — non-finite prices rejected on every path; the
  list/DataFrame path runs the CSV path's bar validation; timezone-less,
  boolean and millisecond timestamps rejected with hints; aware `datetime`
  accepted; sub-second epochs kept; NaN volume = missing; strategy-facing
  timestamp documented and pinned (#8) plus `bar["timestamp_ms"]`; data
  errors carry the zero-based `row`.
* **OBS-TRUST-03** — `history` is a read-only O(1) `observa.History` view
  with list semantics (identity-stable within a bar, never leaks across bars,
  retained views never grow, GC-traversable) (#6).
* Docs/spec/template/guide regenerated or mirrored; CI and release gates run
  the new checks plus the golden ledgers.

### Evidence

| Check | 0.1.6 | Fixed build |
|---|---|---|
| `test_trust_boundary.py` (70 checks incl. 2 Hypothesis properties) | 49 fail | 70 pass |
| `test_history_contract.py` (semantics, isolation, GC, golden digest, scaling) | mutation/semantics checks fail; golden digest recorded **from** 0.1.6 | 5/5 pass; events byte-identical to the 0.1.6 digest |
| `test_causality.py` (no-lookahead perturbation, negative control, determinism) | 5/5 pass (baseline property) | 5/5 pass |
| Golden ledgers (Finance/QA, hand-computed, 616 checks) | 616/616 | 616/616 |
| Differential vs backtesting.py 0.6.6 (232 checks) | 232/232 | 232/232 |
| Finance/QA cross-build comparison, valid inputs (41 scenarios, 260 checks) | — | byte-identical events/run/metrics |
| Code reviewer's own 18-run comparison (54 files) | — | byte-identical |
| Existing suites (Rust 282→284 tests; 11 Python suites; replay JS) | pass | pass |
| Clean venv, wheel + Hypothesis only (CI-equivalent) | — | 15/15 suites pass |

Independent reviews: `docs/audit/review_code_2026-10.md` (code: approve with
changes → re-review approve; R-1 and M-6 follow-ups applied after) and
`harness/finance/FINANCE_REVIEW.md` (Finance/QA: no economic defect; approve
with changes; F1/F2/F4/F5 addressed, F3 documented). Both reviewers are
separate agents of the same model family as the implementer — independent of
the implementation, not of the model.

### Performance (`harness/audit/bench_scaling.py`, CPython 3.13, median of 3)

| Bars | 0.1.6 no-op | Fixed no-op | Fixed, reads `history[-20:]` every bar | Fixed peak RSS |
|---|---|---|---|---|
| 1,000 | 1.90 s | 0.027 s | 0.16 s | 24 MB |
| 8,000 / 10,000 | 71.8 s (8k) | 0.18 s (10k) | 1.0 s | 33 MB |
| 100,000 | ≈ 3 h (extrapolated, not run) | 1.59 s | 9.4 s | 128 MB |
| 1,000,000 | — | 15.5 s | 73 s | 1.0 GB |

Issue #6 reproduction (verbatim): 1k 0.02 s … 100k 2.07 s. Issue #8
reproduction: format pinned; joining on `timestamp_ms` matches, string join
documented as wrong.

### Agent evaluation (same 10 tasks, graders and prompt; one attempt each)

| Arm | Baseline (0.1.6) raw / infra-adjusted | Final raw / infra-adjusted |
|---|---|---|
| Claude Sonnet | 9/10 / 9/10 | 10/10 / 10/10 |
| Claude Haiku | 5/10 / 9/10 | 5/10 / 10/10 |

"Infra-adjusted" ignores failures that are only "REPORT.md missing": the
sub-agent harness refused `.md` writes for some Haiku agents (an evaluation
infrastructure artefact, not Observa); the rule is applied identically to every
arm. The only genuine failure at baseline was **T04** (100k bars could not
finish in 20 minutes in either arm); in the final build both arms finished it
in ≈ 11–12 s. Trajectory evidence: at baseline **both** arms' T03 agents first
produced a silent zero-trade run (string join on `Z` timestamps) before
recovering; in the final build both joined on `timestamp_ms` directly. A
remaining gap surfaced by Haiku T10: a drawing error on a signal path is not
caught by the 6-bar smoke validation (S05 remains).

Limits of this evaluation: n = 1 per task per arm; strong agents saturate most
tasks; same model family as the implementer; isolation by instruction only.

## 8. Deferred items and decisions

### Decisions for the owner

> **Update (0.2.0):** Decision 1 was implemented as metrics schema 2 — the
> annualisation factor is recorded, intraday bars are never annualised without
> an explicit `bars_per_year`, and missing inputs make the metric unavailable
> with a reason instead of failing the run (`docs/metrics.md`). Decision 2:
> released as 0.2.0.

1. **Intraday annualisation (FC-4, M01–M03).** Today `bars_per_year` defaults
   to 252 for every interval and is not persisted, so annualised return, Sharpe
   and Calmar are mis-scaled for every non-daily run — including the shipped
   EUR/USD demo (8 days, +6.54 % → "2.70 % annualised"). *Recommendation:*
   (a) persist the factor used in `metrics.json` immediately (no number
   changes); (b) when `interval` is not daily and `bars_per_year` is not given,
   **fail with a clear error asking for it** rather than guessing 252 or a
   24/7 calendar; (c) add a `bars_per_year` field to `Config`. *Consequence:*
   existing intraday scripts must add one argument; no metric silently changes
   meaning. Alternative: derive it from the data's timestamps (changes the
   number every intraday user sees).
2. **Version number for this release.** The changes intentionally make
   previously silent inputs fail. *Recommendation:* 0.2.0 (pre-1.0 minor bump),
   with the upgrade table in `docs/releases/observa-next-DRAFT.md`. Nothing has
   been tagged or published.
3. **`Config.strategy_name`.** Accepted (now type-checked) but not recorded;
   recording it as the strategy name would change the strategy identity hash
   (Finance/QA F4). *Recommendation:* add a separate `strategy.label` field to
   `run.json` in a run-schema bump; until then the docs say it is not recorded.
4. **Crypto currency codes (#7) and %-of-notional fees / funding (#9).** Both
   are real gaps for crypto users but change economics or accounting and need
   a Finance design; not started.

### Deferred (not selected for this round)

| Item | Why deferred | Suggested next step |
|---|---|---|
| FC-5 zero-trade runs look successful (Z01) | Most common causes now fail loudly (FC-1); the remaining cause is all-orders-rejected | Add `rejected_orders` to `summary()` / `run_summary()` and a warning when a run has 0 fills but >0 rejections |
| FC-6 cold-start doc gaps (X01) | Documentation only | README: name `agent_guide_path()` / `agent_spec()` / `ReplayServer`; mark repo-only links; ship or remove `examples/eurusd_demo.py` reference |
| Finance/QA doc defects D2–D4 | Docs disagree with deliberate code behaviour | Fix `execution-model.md` (triggered STOP fills get half spread + slippage; SL exits get half spread + slippage), retire `docs/domain/EXECUTION.md`; document the 11 gaps in `harness/finance/FINANCE_REVIEW.md` |
| Finance/QA D1 | ROUND_TRIP shows commission on both fills | Report 0 on the entry fill or document the field as "commission attributable" |
| Memory ≈ 1 KB/bar | Linear, but 1M bars ≈ 1 GB | Stream events to disk during long runs |
| Extra bar fields (#1), dividends (#2), rates (#3), multi-instrument (#4) | Features needing design | Keep as issues |
| Rust CLI bridge (`crates/observa-python`) | Not user-facing; got the unknown-key check only | Align or retire |
