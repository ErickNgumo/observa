# Independent code review — OBS-TRUST-01 / -02 / -03 (2026-10 trust audit)

Reviewer: independent review agent (did not author the change).
Branch: `trust-audit-2026-10`, uncommitted working tree on top of `c01206f7`.
Date: 2026-10-16.

## 0. What was reviewed (important)

The working tree was **modified while this review was in progress**. Between my
first pass and my second pass, `python/src/lib.rs` (History cache, `__copy__` /
`__deepcopy__` / `__reduce__`, `sequence` flag, NaN-volume-as-missing,
`strategy_name` recording reverted), `crates/observa-data/src/csv_reader.rs`
(NaN volume) and the tests changed. Every verdict and reproduction below was
re-run against the **second** state:

| file | sha256 (reviewed state) |
| --- | --- |
| `python/src/lib.rs` | `7e86885b6b0857cd80a187084c00a7a037db4eece486cc4727ed0d5394e368ce` |
| `crates/observa-core/src/bar.rs` | `538235f12622ce6a8799ff6844d0bbac8c4c8f3eb8167bded50e6e8d3cc2f8fd` |
| `crates/observa-data/src/csv_reader.rs` | `0eda63ffae969bd934725fb35eb030ae99c5604971876158bdf191c01a9f405a` |
| `python/python/observa/validation.py` | `0dce86a0fbc798101e2fb0b6ff2a6de45562d24a9fc0cbdcb9ca3937e2481237` |
| `python/python/observa/__init__.py` | `93f968c34947d73c53689bec868285397a59ed57d0349be90124c93adcc7c846` |

I rebuilt the wheel from that tree myself (`maturin build --release`); its
`_observa.abi3.so` sha256 is `b3978308…72d93`, identical to the one installed
in `venv-dev`, and the Python package files in the wheel, in `venv-dev` and in
the repo are identical. Any later edit invalidates this review.

The task summary given to me claimed "`strategy_name` is honoured". **That is
not true of the reviewed state**: it was reverted (see N-3), and the ticket now
says so.

## 1. Verdict

**Approve with changes.** No blocker. No finding changes economics, and none
makes a run silently produce a wrong result. Everything listed in §3 is minor or
a nit: four doc/validator text mismatches, two robustness issues in the new
`History` class (a cycle leak and a lock held across Python calls), and small
`list`-compatibility gaps. Fix the minors before release. The nits are optional.

Economics are unchanged for valid inputs. I ran 18 independent runs (3 of my own
strategies × 3 datasets × 2 configs) on this build and on the released 0.1.6
wheel. All 54 artifact files (`events.jsonl`, `run.json`, `metrics.json`) are
byte-identical. Finance/QA sign-off is still required because OBS-TRUST-02 is
`financial: true`, and one canonical-output change for valid input exists (C-1).

## 2. Test results I actually ran (reviewed state unless noted)

Interpreter: CPython 3.13.5 (`venv-dev`); the pandas probes ran on CPython 3.14 (scratch venv, same wheel).

| suite | result |
| --- | --- |
| `cargo test --workspace` (`PYO3_PYTHON=python3.13`) | exit 0, 284 passed, 0 failed |
| `python/tests/test_trust_boundary.py` | 69 passed, 0 failed |
| `python/tests/test_history_contract.py` | 4 passed, 0 failed (scaling 40k/10k ratio ≈ 4.1) |
| `python/tests/test_causality.py` | 5 passed, 0 failed |
| `python/tests/test_agent_contract.py` | 177 passed, 0 failed |
| `python/tests/test_canonical_baseline.py` | 33 passed, 0 failed |
| other suites (`test_ai_interface`, `test_annotations`, `test_demo`, `test_deterministic_identity`, `test_inspection`, `test_observa`, `test_onboarding_ai`, `test_strategy_reason`) | all pass |
| `test_mcp.py` | 149 passed, 0 failed |
| `harness/finance/golden_ledgers.py` | 616 passed, 0 failed |
| new tests against **released 0.1.6** | `test_trust_boundary`: 18 passed / 49 failed (expected: these are the regressions it guards). `test_history_contract --print-golden`: the digest `a2c8a3f0…64a7` matches 0.1.6, so the golden is genuine. `test_causality`: 5/5 |

Every shipped example strategy passes `observa validate-strategy --smoke`: `examples/*.py`, `examples/ai_starter/strategy.py`, the bundled samples and `_agent/example_strategy.py`.

Scratch scripts: `/tmp/claude-1000/-home-erick-Documents-observa/8e8c655e-9ac3-4519-a485-898ac80f66b3/scratchpad/review/`. The `probe_*.py` files there are the reproductions referenced below.

## 3. Findings

### Minor

**M-1 — Reference cycles through the new `History` cache are never collected (memory leak).**
`python/src/lib.rs:809-815` (`HistoryView { cache: Mutex<BTreeMap<usize, Py<PyDict>>> }`)
and `:1011-1017` (`HistoryIter { view: Py<HistoryView> }`). Both pyclasses hold
strong Python references but implement neither `__traverse__` nor `__clear__`, so
the cyclic GC cannot see the references. A cycle such as view → cached dict →
view leaks permanently. 0.1.6 used a plain list and collected it.
Repro (`probe_cache.py`: on bar 3, `d = h[1]; d["cycle"] = h; d["m"] = Marker()`; then `gc.collect()` twice after the run):
```
venv-dev    : Marker in cyclic history collected after run: False
venv-rel313 : Marker in cyclic history collected after run: True
```
The pattern is rare. If it happens on every bar it leaks one growing view per bar, which is O(N²) memory.
Fix: implement `__traverse__` / `__clear__` on `HistoryView` (visit cached dicts) and `HistoryIter` (visit `view`). Alternatively make the cache non-owning.

**M-2 — The store read lock is held while calling the Python C API (`bar_dict`).**
`python/src/lib.rs:823-826`: `let store = self.store.read()?; bar_to_py_dict(py, &store[i])?`.
`bar_to_py_dict` allocates Python objects. On CPython < 3.12 an allocation can
run the cyclic GC inline, which runs arbitrary finalizers, which can release the
GIL. Suppose a background thread is iterating a retained view and is in that
state. The main thread then takes the GIL and calls `history_view()` →
`store.write()` (`:767`) while still holding the GIL. The writer blocks on the
reader and the reader blocks on the GIL: **deadlock**. The insert at `:827-830`
can also drop a displaced `Py<PyDict>` while holding the cache mutex.
I could **not reproduce** it on 3.13. `probe_deadlock.py` (a reader thread plus
finalizers that sleep, `gc.set_threshold(1,1,1)`) completed every time. 3.12+
defers GC to the eval breaker, and no 3.10 or 3.11 interpreter was available.
The wheel is `abi3` for ≥3.10.
Fix: copy the `Bar` out under the lock (`let bar = store[i].clone(); drop(store);`), then build the dict.
For the cache, use `entry(i).or_insert(...)`. Or, because every access already
holds the GIL, drop the OS locks entirely: a non-`frozen` pyclass with
`RefCell`, or `GILProtected`.

**M-3 — Validator messages still describe the old lenient engine, contradicting the new contract** (acceptance criterion 4).
`python/python/observa/validation.py:305` (docstring: "including silently ignoring malformed shapes"),
`:451-452` ("None is ambiguous and is silently ignored by the engine"),
`:461-463` ("the engine only reads the 'signals' key, so nothing was executed").
Repro:
```
$ observa validate-strategy none_ret.py --smoke --json   # on_bar returns None on bar 3
 ERR STRATEGY_RETURN_INVALID | on_bar returned None; return [] for 'no action' — None is ambiguous and is silently ignored by the engine
$ observa validate-strategy drawonly.py --smoke --json   # returns {"drawings": []}
 ERR STRATEGY_RETURN_INVALID | ... the engine only reads the 'signals' key, so nothing was executed. ...
```
Fix: reword the messages to "the engine rejects this with STRATEGY_RETURN_INVALID".

**M-4 — Docs promise `exc.details["row"]` for CSV data errors; the CSV path has no details.**
`docs/data-format.md:33-34` and `llms-full.txt:380-381` ("the error names the row (`exc.details["row"]`)").
The CSV path goes through `data_err` (`python/src/lib.rs:68-75`), which passes `details=None`.
Repro (`probe_csv.py` + one-liner):
```
observa.run(observa.Strategy(), "nan_close.csv")  ->  ValueError DATA_INVALID {}
   message: "invalid data: Bar validation failed at row 2: Price field 'close' must be a finite number, got NaN"
```
The CSV row is also 1-based (file line, header = 1), while the list path is a 0-based index.
Fix: map `DataError::InvalidBar { row, .. }` to `details={"row": row}` and document the base, or narrow the doc to list inputs.

**M-5 — Docs say NaN volume is rejected; the reviewed code accepts it as "missing".**
`docs/data-format.md:29-30` ("volume, when present, finite and non-negative. NaN/inf are rejected") and
`llms-full.txt:380` ("volume finite and non-negative"). The code now filters NaN
volume to `None` on the dict path (`lib.rs:624`), the sequence path (`lib.rs:645`)
and the CSV path (`csv_reader.rs:122`).
Repro: CSV `nan_vol` → `OK`. A DataFrame with a NaN volume → `OK (..., None)`.
I agree with the behaviour: NaN is pandas' missing marker and volume has no economic role.
Fix: update the two docs. The Rust test `non_finite_volume_fails_validation` covers only `Bar::validate`, so also add a loader-level test pinning NaN→`None` and inf→`DATA_INVALID`.

**M-6 — `strategy_name` is allow-listed but silently ignored and not type-checked.**
`python/src/lib.rs:1793-1795` (NOTE comment, value never read); listed in
`CONFIG_FIELDS` (`:85-93`) and documented as a public field (`docs/execution-model.md:90`, `llms-full.txt:397`).
Repro (`probe_cfg.py`):
```
{"strategy_name": "MyName"} -> OK, run_started strategy_name='S'
{"strategy_name": 5}        -> OK   (0.1.6 behaviour; the first build of this change raised CONFIG_INVALID)
```
This is the "accepted and silently ignored" class that FC-1 exists to remove.
The revert is justified: recording the value changes `params_sha256` (ticket
OBS-TRUST-01, F4). But users get no signal.
Fix: at least validate the type, and state "accepted, not yet recorded" in `Config` and the docs. Alternatively emit a warning.

**M-7 — `bar["timestamp"]` format is documented as `[.fff]`, but it can carry 6 or 9 fractional digits.**
`contract.py` / `spec.json` / `docs/data-format.md:36-37` / `docs/strategy-contract.md` / the authoring guide.
Repro (`probe_ts.py`):
```
'2024-01-01T00:00:00.123456789Z' -> '2024-01-01T00:00:00.123456789+00:00'
datetime(..., 123456, tz=utc)    -> '2024-01-01T00:00:00.123456+00:00'
```
Issue #8 was about exact string joins, so the documented format should be exact.
Fix: document "`.fff`, `.ffffff` or `.fffffffff` (chrono `to_rfc3339`, `AutoSi`)" or normalise to milliseconds. `timestamp_ms` is fine.

### Canonical-output change for previously-valid input (needs Finance/QA ack, not a defect)

**C-1 — Fractional epoch-second inputs now keep sub-seconds.** This changes canonical
timestamps compared with 0.1.6, which floored them.
Repro (`probe_ts.py`):
```
1704067200.5 : dev '2024-01-01T00:00:00.500+00:00'   rel '2024-01-01T00:00:00+00:00'
0.9999999    : dev '1970-01-01T00:00:01+00:00'       rel '1970-01-01T00:00:00+00:00'
```
Rounding to the microsecond is correct, including the carry case and negative
values (`-0.5` → `…23:59:59.500`). This is intended (D-finding), but runs over
such data no longer reproduce 0.1.6 artifacts. Two bars within the same second
that 0.1.6 rejected as non-increasing are now accepted. The engine's drawing-time
set (`engine.rs`, `bar_times` built from `.timestamp()` seconds) and the replay
chart (second resolution) were already exposed to this through fractional ISO
strings. I did not test those interactions.

### Nits

* **N-1** `python/src/lib.rs:772` — the `store.clear()` branch is unreachable today, because `PyStrategy` is created per run; I verified that two runs of the same instance give correct, independent histories (`probe_rerun.py`). If it were ever reached, views retained from before the clear would panic on `store[i]`, since their `len` exceeds the store length. Remove it, or replace the store with a fresh `Arc` instead of clearing.
* **N-2** `lib.rs:847` — `history == tuple(...)` returns `True`; `list == tuple` is `False` in Python.
* **N-3** `lib.rs:881` — `history[10**20]` raises `TypeError`; a list raises `IndexError` (`probe_history.py`, 24 mismatches, all this case). All other index, slice (every start/stop/step combination including huge, negative and zero-step), `index(start, stop)`, `count`, `reversed`, `in`, `+` and `==` cases match `list` exactly.
* **N-4** `History` lacks `*`, ordering comparisons and JSON serialisation. `json.dumps(history)` raises `TypeError`. These are acceptable for "list-like, not a list", but list them in the migration notes next to `isinstance(history, list)`.
* **N-5** `{"drawings": [...]}` without `signals`, `{}` and `{"signals": None}` were accepted by 0.1.6 and now fail with `STRATEGY_RETURN_INVALID`. This is consistent with the documented rule, but the ticket's Compatibility section mentions only bare dicts and `None`. Add these cases there.
* **N-6** `[None]` (a non-dict signal) still fails with the generic `STRATEGY_ERROR`, while the validator reports `STRATEGY_RETURN_INVALID` for the same input. The validator also accepts `"drawings": None`, which the engine rejects with `DRAWING_TYPE_INVALID`. Both are pre-existing.
* **N-7** `lib.rs:419-424` — if both `params` and `strategy_params` are given, `strategy_params` is silently ignored. This is pre-existing, but it is the FC-1 class.
* **N-8** Timestamp messages: a tz with a seconds offset (`+05:00:30`, from `datetime` with historical LMT zones) gives a generic "cannot parse". `pd.NaT` gives `"NaTType does not support utcoffset"` with no hint. `"2024-01-01T00:00"` without seconds gets no timezone hint. Epoch-millisecond values below `1e11`, which cover dates 1970-01-01 to 1973-03-03, are still read as seconds; that is inherent to the threshold and fine.
* **N-9** `docs/data-format.md:36-40` — a paragraph is inserted inside the "Requirements" bullet list, so the "strictly chronological" and "rows used exactly" bullets now read as if they belong to the strategy-facing paragraph.

## 4. Verified correct

* **History semantics** (`probe_history.py`, `probe_cache.py`, `probe_rerun.py`)
  * Slices match `list` for every start, stop and step in [-15..15], `None` and ±10²⁰, and always return a `list`. `h[::0]` raises `ValueError`.
  * Indexing matches for all in-range and out-of-range ints, `bool` and `numpy.int64`. Non-int indices raise `TypeError`.
  * `iter`, `reversed`, `in`, `index(v, start, stop)` and `count` match `list` with 0 mismatches over 396 combinations. `==` / `!=` work with lists and views, including reflected `list == view`, and `+` works in both directions.
  * `copy.copy`, `copy.deepcopy`, `pickle` and `.copy()` return lists (pickle round-trips as `list`). `pd.DataFrame(history)` → `(10, 7)`, and `np.array(history)` → `(10,)` object array.
  * `isinstance(h, Sequence)` is True and `isinstance(h, list)` is False. Mutators are absent and item assignment/deletion raise.
  * A retained view never grows. Edits are visible within the bar (`h[0] is h[0]`, as in 0.1.6), and the next bar's view starts from fresh dicts.
  * The views of a first run stay intact after a second run of the same instance, and the second run's histories are correct.
* **History scaling.** It is linear: a window-20 strategy took 1.6 s for 20k bars and 6.8 s for 100k bars. Build 1 (no cache) and the reviewed build are equivalent (50k bars: 4.10 s vs 4.39 s, best of 3).
* **History store vs Engine.** The store cannot diverge from the Engine's history in practice. The Engine's history is a run-local append-only `Vec` (`engine.rs:479-485`), and `history_view` appends exactly the missing suffix. The Engine aborts on the first strategy error, so the early returns that skip `bar_index += 1` cannot leave inconsistent state.
* **Return shapes and signal keys** (`probe_returns.py`, 0.1.6 vs dev side by side)
  * Valid forms are still accepted: `[]`, list, envelope with or without `drawings`, `list` / `dict` subclasses, `OrderedDict` signals, and `None` values for optional fields.
  * These now fail at the right `bar_index`: `None`, a bare dict, unknown envelope keys, a missing or non-list `signals`, tuples, generators, unknown or non-string signal keys (with `signal_index` and a suggestion such as `stop_loss`→`sl`, `qty`→`size`, `Stop_Loss`→`sl`).
* **Config allow-list.** It covers every key `observa.Config().to_dict()` can emit, including `tick_size`, `pip_size`, `order_model`, `strategy_source` and `dataset_source`. Typos fail with a suggestion (`spred`→`spread`, `order_model.markt`→`order_model.market`). A non-dict `order_model` still fails with `CONFIG_INVALID`, and non-string keys fail. A zero or negative `tick_size` / `pip_size` is rejected by `cfg.validate()`.
* **Timestamps** (`probe_ts.py`, `probe_csv.py`, `probe_pandas.py`)
  * Still accepted, as before: `Z`, `+00:00`, `+03:00`, the space-separated CSV form, fractional seconds up to ns, lowercase `t`/`z`, and epoch ints and floats.
  * Newly accepted: aware `datetime`, aware `pandas.Timestamp` (UTC and Europe/Berlin), and `Decimal`.
  * Newly rejected with hints: timezone-less strings, naive `datetime` / `pandas.Timestamp`, `bool` (0.1.6 accepted `True` as 1970-01-01T00:00:01), `NaN` epochs (0.1.6 accepted them as 1970-01-01), and epoch ms.
  * The CSV path rejects NaN/inf prices (0.1.6 accepted them) and still rejects timezone-less timestamps.
* **Determinism and economics.** 54/54 artifact files are byte-identical to 0.1.6 across fills (`next_bar_open` / `bar_close`), commission, spread/slippage, SL/TP, limit/stop orders, ticket closes, drawings, and CSV and list inputs. The history-contract golden digest is the genuine 0.1.6 value.
* **Doc mirrors.** `docs/agent/strategy-authoring.md` matches the bundled `_agent/strategy-authoring.md` exactly. The AGENTS template body is mirrored verbatim in `AGENTS.md` and `examples/ai_starter/AGENTS.md`. `test_agent_contract` (generated docs and spec consistency) passes.

## 5. Not verified

* CPython 3.10/3.11 (none available), so the M-2 deadlock was not reproduced. Other platforms were not tested either.
* Free-threaded CPython was not tested; it does not apply to the `abi3` wheel.
* The `observa-python` crate's new unknown-key check (`crates/observa-python/src/signal.rs`) is covered only by `cargo test`. I did not exercise it through a CLI run.
* Replay and frontend behaviour with sub-second bar timestamps (C-1).
* The CI workflow edits were read but not executed in GitHub Actions.

## 6. test_mcp

`python/tests/test_mcp.py` on the reviewed build exited 0 with 149 checks passed, 0 failed (125.5 s). It also passed on the first build: 149/0.

## 7. Re-review of the fixes (2026-10-16, second pass)

Scope: only the fixes for M-1…M-7 and the nits N-2/N-3. I changed no tracked
files. Reviewed state:

| file | sha256 |
| --- | --- |
| `python/src/lib.rs` | `3d3c79838336d696dcd3154c1ac8b74ea97ecf09c3d7e1d5c1036cdbf701c8c7` |
| `python/python/observa/validation.py` | `b973fc078e5f7bcd86498c203cbfc666377bd729eb04fad2f5c8fd863869e6a5` |
| `crates/observa-data/src/csv_reader.rs` | `0eda63ff…` (unchanged since the first pass) |

I rebuilt the wheel myself. Its `_observa.abi3.so` sha256 is `742b079e…7edf`,
identical to the one installed in `venv-dev`, and the installed Python files
match the tree. The source hashes were re-checked after all runs and were
unchanged.

**Suites run on this state (CPython 3.13.5):**
- `cargo test --workspace`: 284 passed, 0 failed.
- `test_trust_boundary`: 70/0. `test_history_contract`: 5/0. `test_causality`: 5/0. `test_agent_contract`: 177/0. `test_canonical_baseline`: 33/0.
- `test_observa`, `test_annotations`, `test_strategy_reason`, `test_inspection`, `test_deterministic_identity`, `test_ai_interface`, `test_demo` and `test_onboarding_ai` all pass. `golden_ledgers`: 616/0.
- `test_mcp` was not re-run this pass; it passed 149/0 on the previous state.
- Economics: my 18-run differential (`probe_econ.py`) is again 54/54 files byte-identical to 0.1.6.

| finding | status | evidence (actually run) |
| --- | --- | --- |
| **M-1** cycle leak | **Resolved** | `__traverse__`/`__clear__` are implemented on `History` (`lib.rs:1050-1066`) and `HistoryIter` (`:1096-1105`). `probe_fix3.py` builds four cycles: view→dict→view, dict→`iter()`→view, dict→`reversed()`→view, and dict→strategy→view. After `gc.collect()`: `collected: {'view': True, 'iter': True, 'rev': True, 'strat': True}`. A view→view cycle on every bar for 3000 bars retains 54.6 KB after GC (traced). New regression check: `test_history_contract.py:164-200`. |
| **M-2** lock held across Python calls | **Resolved (by inspection; not reproducible here)** | `bar_dict` (`lib.rs:843-866`) clones the `Bar` under the read lock and releases it before `bar_to_py_dict`. The displaced cache entry is dropped after the mutex guard, since the temporary guard ends with the `let previous = …` statement. The remaining lock regions do no Python allocation: the cache lookup does only `clone_ref`, and `history_view`'s write lock only extends a `Vec<Bar>`. `__traverse__` uses `try_lock`; contention there could only under-report references, which makes an object look alive (a leak, never a use-after-free). `probe_deadlock.py` ×3 completed in 0.9 s. As before, no 3.10/3.11 interpreter was available to run the original hazard. |
| **M-3** stale validator text | **Resolved** | `validate-strategy --smoke` now prints "on_bar returned None (is a return statement missing?); … the engine rejects None" and "a dict without a 'signals' key; the engine rejects it". No "silently ignored" / "only reads the 'signals' key" message text remains; the only hit is a historical comment at `validation.py:487`. |
| **M-4** CSV `details["row"]` | **Resolved, with one residual nit (R-1)** | `probe` over 8 CSVs: NaN close and inf high → `{'row': 0, 'line': 2}`; bad price and non-monotonic timestamps → `{'row': 1, 'line': 3}`; timezone-less (both forms) and short record → `{'row': 0, 'line': 2}`. The new check is `test_trust_boundary.py:242-243`. |
| **M-5** NaN-volume docs | **Resolved** | `docs/data-format.md:29-31` and `llms-full.txt:380-381` now say NaN volume is treated as missing. This matches runtime: `nan_vol.csv` → OK, DataFrame NaN volume → `None`. |
| **M-6** `strategy_name` | **Partially resolved** | The type check works: `5`, `b"x"` and `["a"]` → `CONFIG_INVALID`, while `"MyName"` and `None` → OK (new check `test_trust_boundary.py:152`). The value is still not recorded: `Config(strategy_name="X")` → `run_started.strategy_name == 'S'`, which the coordinator accepts as an owner decision. The "accepted but not recorded" caveat exists only in `docs/releases/observa-next-DRAFT.md:21` and the ticket. It is missing from the user-facing places: the `Config` field (`__init__.py:120`), `docs/execution-model.md:90`, `llms-full.txt:399`, and the authoring guide (`strategy-authoring.md:155`). Every shipped example still passes `strategy_name="…"` as if it named the run. Add the caveat there. |
| **M-7** timestamp format docs | **Resolved** | `spec.json:8`, `contract.py:156`, `STRATEGY_API.md:91`, `llms-full.txt:97`, `strategy-contract.md:33`, `data-format.md:38-40` and the authoring guide now say `[.f…]` (fraction only when non-zero; data-format adds 3, 6 or 9 digits). This matches the observed output in `probe_ts.py`. The authoring-guide mirrors are identical. |
| **N-2** `history == tuple` | **Resolved** | `h == tuple(ref)` → False, `h != tuple(ref)` → True, and `h == list` → True (new check `test_history_contract.py:100`). |
| **N-3** huge int index | **Resolved** | `10**20`, `-10**20`, `2**63` and `-(2**63)-1` → `IndexError` (same as `list`); `1.5` and `"0"` → `TypeError` (same as `list`). |
| **C-1** sub-second epochs | Accepted by Finance/QA per the coordinator (`harness/finance/FINANCE_REVIEW.md`); I did not re-assess it. | — |

**R-1 (nit, new): `details["line"]` is wrong when the CSV contains blank lines.**
`lib.rs:678-698` derives `line` from the reader's `row`, which is the record index + 2 (`csv_reader.rs:100-102`). The `csv` crate skips blank lines, so after a blank line `line` is no longer the file line.
Repro: `blank_line.csv` has the header, a valid row, an empty line, then `close=NaN` on file line 4. Result: `DATA_INVALID {'row': 1, 'line': 3}` and the message text says "row 3".
`row` (zero-based data row) is correct. `line` and the message are off by the number of blank lines above. Quoted multi-line fields would shift it the same way.
Fix: take the position from `csv::StringRecord::position().line()` or `csv::Error::position()`. Otherwise, document `line` as "header + data-record index", not the file line. The message text still says "row N" with N 1-based, while `details["row"]` is 0-based. Consider rewording the message to "line N".

**Re-review verdict: approve.** M-1, M-2, M-3, M-4, M-5 and M-7 are resolved, along with N-2 and N-3. M-6 is partially resolved: the type check is done, but the "not recorded" caveat is still missing from the user-facing `Config` docs and the examples. That doc change is small and can land with the release notes. R-1 is a nit.
