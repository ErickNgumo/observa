# OBS-AI-02 Required-Fixes Report

**Ticket:** OBS-AI-02 — Strategy Annotations (independent-QA required fixes)
**QA verdict addressed:** PASS WITH REQUIRED FIXES
**Branch:** `obs-ai-02-strategy-annotations`
**Base commit (reviewed by QA):** `6b663878`
**Fix commit:** `70a15e4b` — *OBS-AI-02 fixes: painter contract, future-bar times, docs accuracy*
**Version:** 0.1.1 (unchanged; no bump requested)

> **OBS-AI-02 fixes ready for QA re-check: YES**
> **Merge now: NO**
> **Create 0.1.2 release now: NO**
> **Begin OBS-AI-03 now: NO**

The four required fixes are implemented, tested at every layer, and verified in
a real browser against the built wheel served from a fresh virtualenv. The
canonical no-drawing baseline is unchanged. Nothing was merged and nothing was
published.

---

## 1. Ticket, branch, status

Independent QA reviewed `6b663878` and returned **PASS WITH REQUIRED FIXES**
with four findings. All four are now closed:

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| HIGH-1 | High | Continuous series exist in chart state but do not paint | **Fixed** |
| HIGH-2 | High | `pane="separate"` creates pane 1 but never paints | **Fixed** |
| MEDIUM-3 | Medium | Future-bar drawing timestamps accepted | **Fixed** |
| MEDIUM-4 | Medium | Docs say legacy `style` is ignored, but it maps to `line_style` | **Fixed** |

Anchoring the two High findings: they were **not two defects**. They were one
defect with two visible symptoms (§3).

## 2. Fix summary

| Finding | Change | File |
| --- | --- | --- |
| HIGH-1 / HIGH-2 | The bottom-zOrder primitive pane view now returns a no-op `draw` alongside `drawBackground`, satisfying the Lightweight Charts 5.0.9 renderer contract | `python/python/observa/static/js/drawing-renderer.js` |
| HIGH-2 (secondary) | The secondary pane is released once no strategy series uses it, so normal usage cannot leave an orphan pane | `python/python/observa/static/js/drawing-renderer.js` |
| MEDIUM-3 | `validate_drawing_times` rejects any drawing timestamp later than the bar currently being processed | `crates/observa-engine/src/engine.rs` |
| MEDIUM-4 | `style` documented as a **deprecated alias that is honoured**; the genuinely-ignored legacy fields listed explicitly | `docs/STRATEGY_API.md`, `llms-full.txt` |

No engine semantic, economic, or canonical-ordering behaviour changed. A
no-drawing strategy still emits **zero** `drawings_emitted` events (§10).

## 3. HIGH-1 and HIGH-2 — one root cause, not two

### What QA saw

- Series had entries in chart state, but the price pane rendered nothing.
- `pane="separate"` produced a real pane 1 (correct height, correct series
  assignment) that also rendered nothing.

### The actual cause

Lightweight Charts **5.0.9** (the bundled standalone build) calls a pane view
renderer's `draw()` **unconditionally** and `drawBackground()` only when it
exists. The bundled source, verified in
`python/python/observa/static/vendor/lightweight-charts.standalone.production.js`:

```js
class Rt { nt(t,i,s){ this.th.draw(t, Tt) }
           ih(t,i,s){ this.th.drawBackground?.(t, Tt) } }
```

The strategy primitive's bottom-zOrder view returned **only** `drawBackground`.
Every render pass therefore threw `TypeError: this.th.draw is not a function`
from inside the library's own render loop. That exception aborts the whole pass,
so **every** series in **every** pane stopped painting — which is exactly the
two High symptoms. It also explains why the defect looked like a pane bug: the
pane was built correctly and then never painted.

### Why QA's `lastValueVisible` lead was a red herring

The earlier bisect that implicated `lastValueVisible: false` was confounded: the
renderer contract failed in both arms. A controlled A/B/C bisect isolated the
real variable — with the primitives attached: EMA `0 px`, z-score `0 px`, and
**2 uncaught exceptions**; with the primitives detached: EMA `745 px`, z-score
`10074 px`. Detaching the primitives, not changing series options, restored
painting. That is why the fix does **not** hardcode `lastValueVisible` — the
flag was never the cause.

### The fix

The bottom view now satisfies the contract, with the contract quoted in the
code so the requirement is not lost:

```js
return {
  draw: function () {},
  drawBackground: function (target) { primitive.draw(target, true); }
};
```

### Verification

- `no chart-library exceptions during render (root-cause regression)` — PASS
- `A price-pane EMA line paints` — PASS
- `B histogram series paints` — PASS
- `C separate-pane z-score paints` — PASS

## 4. HIGH-2 — the pane itself

The pane was already being created and assigned correctly; it only needed the
renderer contract above. The bundled v5 pane API was re-verified against the
**bundled** library rather than newer or older documentation:

| API | Occurrences in bundled 5.0.9 |
| --- | --- |
| `panes` | 9 |
| `addPane` | 1 |
| `removePane` | 1 |
| `getSeries` | 2 |

Browser evidence: `C2 exactly two panes with usable heights`, `C3 price series
stay in pane 0, secondary series in pane 1`, `C4 price series sit ABOVE the
secondary pane` — all PASS.

A second, smaller defect in the same area is also fixed: toggling the
annotations off left an empty pane 1 behind. `drawingReleasePaneIfEmpty()`
removes the pane when no strategy series uses it, guarded so an unsupported or
failing removal can never break the chart. Browser: `G3 no orphan secondary
pane after hiding` — PASS.

## 5. MEDIUM-3 — future-bar drawing timestamps

### The defect

Drawing timestamps were validated for **membership in the dataset** only. Because
the Engine holds the whole dataset, a strategy could name a bar it had never
seen — an information oracle into the unseen future, and a violation of the
"future data must be structurally inaccessible" invariant.

### The fix

`validate_drawing_times` now also rejects any timestamp **later than the bar
currently being processed**:

```rust
if parsed.timestamp() > current_ts {
    return Err(EngineError::StrategyFailure { /* code: DRAWING_TIME_INVALID */
        details: json!({ "bar_index": …, "drawing_id": …, "field": …,
                         "value": …, "current_bar_timestamp": current_ts }) });
}
```

`time_end: null` is deliberately **not** a timestamp and remains valid: it means
"extend right as replay advances", and it names no bar. Hints in the Rust test
suite cover both directions; `time_end: None` regions and rectangles continue to
work (the human-review run relies on it — §11).

### Coverage — all four required cases

| Case | Meaning | Result |
| --- | --- | --- |
| N | current bar | accepted |
| N−1 | earlier bar | accepted |
| N+1 | next bar (exists in dataset) | rejected `DRAWING_TIME_INVALID` |
| N+50 | far future (exists in dataset) | rejected `DRAWING_TIME_INVALID` |

Both future cases use timestamps that **do exist** in the dataset, proving the
rejection is about the future and not about existence.

- Rust: `annotations.rs` — `future_bar_drawing_timestamps_are_rejected`
  (N/N−1 accepted; N+1, N+50, and a marker, line x2, and region end rejected).
- Python: `test_annotations.py` — checks **15c–15g**, run against the installed
  wheel; 15f asserts the error details name `current_bar_timestamp`, so the
  failure is actionable.

## 6. MEDIUM-4 — documentation accuracy

The docs claimed `style` was ignored. It is not: it is accepted as a
compatibility alias of `line_style`. Both documents are corrected and now
separate honoured aliases from genuinely-ignored fields.

`docs/STRATEGY_API.md`:

> **`style` is a deprecated compatibility alias for `line_style`.** It is
> honoured, not ignored.

`llms-full.txt`:

> `style` is a deprecated ALIAS for `line_style` (it IS honoured).
> `persist` / `fill_price` / `extend` / `bg_color` are accepted but IGNORED.

The claim was verified against the running code, not just re-worded:

```
persisted spec : {'action': 'add', 'color': '#d29922', 'id': 'poc',
                  'label': None, 'line_style': 'dashed', 'price': 1.0972,
                  'type': 'hline', 'width': 1}
style alias honoured (line_style == 'dashed'): True
legacy key absent from canonical spec        : True
```

`persist`, `fill_price`, `extend` and `bg_color` are listed as accepted and
ignored, matching the implementation.

## 7. Files changed

```
crates/observa-engine/src/engine.rs                |  32 ++-   MEDIUM-3
crates/observa-engine/tests/annotations.rs         | 189 +++-  MEDIUM-3 tests
docs/STRATEGY_API.md                               |  23 ++-   MEDIUM-4
llms-full.txt                                      |   5 +-    MEDIUM-4
python/python/observa/static/js/drawing-renderer.js|  39 ++-   HIGH-1/HIGH-2
python/tests/drawings.test.js                      |  27 ++    renderer contract test
python/tests/test_annotations.py                   |  54 ++    Python 15c-15g
python/tests/make_annotation_demo.py               | 177 ++    human-review run
8 files changed, 535 insertions(+), 11 deletions(-)
```

`git diff --stat` in the report above is exactly `git show --stat 70a15e4b`.
The generated run directory `runs/annotation_demo` is deliberately **not**
committed: it is a build artifact reproducible from the committed generator with
one command (§11).

## 8. Test evidence

All suites were run against the **final candidate wheel** in a fresh virtualenv
unless noted.

| Suite | Result |
| --- | --- |
| `cargo test --workspace` | **245 passed / 0 failed** |
| `python/tests/test_annotations.py` | **59 checks / 0 failed** (5 new: 15c–15g) |
| `python/tests/test_canonical_baseline.py` | **33 checks / 0 failed** |
| `python/tests/test_observa.py` | **15/15 passed** |
| `python/tests/test_ai_interface.py` | **76 checks / 0 failed** |
| `python/tests/test_onboarding_ai.py` | all checks passed |
| `python/tests/replay.test.js` | **16/16** groups passed |
| `python/tests/drawings.test.js` | **11/11** groups passed |
| Browser verification (headless Chrome, CDP) | **27/27 checks passed** |

`drawings.test.js` gained a contract test that asserts **every** pane view
renderer implements `draw()`. This is the regression guard for HIGH-1/HIGH-2:
the specific class of defect that blanked the chart now fails a unit test
instead of silently aborting a render pass.

## 9. Browser verification — findings A–J

Headless Chrome 151.0.7922.169 over CDP, viewport 1600×1100, device scale 1.
Every check is programmatic pixel analysis of the composited screenshot
(the verifying model has no image input, so no check rests on visual
impression — the PNGs are retained for human review).

**Served from the shipped artifact:** the replay servers were started from a
**fresh virtualenv** containing only the final wheel, so this exercises the
built product, not the development tree.

| # | Check | Result |
| --- | --- | --- |
| 1 | demo run loaded | PASS |
| 2 | **no chart-library exceptions during render (root-cause regression)** | PASS |
| 3 | **A** price-pane EMA line paints | PASS |
| 4 | **A2** price-pane VWAP series present | PASS |
| 5 | **B** histogram series paints | PASS |
| 6 | **C** separate-pane z-score paints | PASS |
| 7 | **C2** exactly two panes with usable heights | PASS |
| 8 | **C3** price series stay in pane 0, secondary series in pane 1 | PASS |
| 9 | **C4** price series sit ABOVE the secondary pane | PASS |
| 10 | **D** rectangle paints | PASS |
| 11 | **E** strategy markers present | PASS |
| 12 | **F** labels paint | PASS |
| 13 | legend lists the series labels | PASS |
| 14 | **G** toggle off hides annotation series | PASS |
| 15 | **G2** canonical execution markers survive the toggle | PASS |
| 16 | **G3** no orphan secondary pane after hiding | PASS |
| 17 | **H** toggle on restores the identical annotation pixels | PASS |
| 18 | **J** forward playback advances the bar | PASS |
| 19 | **I** backward seek restores the same frame (pixel-level) | PASS |
| 20 | **I2** seek restores identical series and primitives | PASS |
| 21 | **I3** no exceptions after seeking | PASS |
| 22 | lifecycle: removed zone is gone after its remove event | PASS |
| 23 | labels run loaded | PASS |
| 24 | **F2** all four label positions paint | PASS |
| 25 | **F3** above paints above below | PASS |
| 26 | **F4** left paints left of right | PASS |
| 27 | **F5** left/right are NOT rendered like above/below | PASS |

**27 browser checks passed, 0 failed.**

### Two harness defects corrected during this pass

Both earlier "failures" were faults in the verification harness, and both were
corrected rather than papered over — the harness now measures the right thing.

1. **Right label reported 0 px.** The harness rendered bar 31 while the label
   anchored at bar 30, so the right-positioned label correctly drew past the
   right edge of the viewport. Rendering bar 80 (anchor well inside the view)
   paints all four positions. Measured label boxes, chart-relative pixels:

   | Position | Pixels | x range | y range |
   | --- | --- | --- | --- |
   | above `#ff00ff` | 109 | 1332–1373 | 264–282 |
   | below `#00ffff` | 118 | 1331–1374 | 298–316 |
   | left `#ffff00` | 97 | 1313–1344 | 281–299 |
   | right `#ff8800` | 107 | 1361–1399 | 281–299 |

2. **Backward-seek "different frame".** The check compared PNG *byte length*
   (99200 vs 99192), which is not a fidelity measure. Replaced with a real
   pixel diff. Result: whole-frame delta **34 px of 1,760,000 (0.0019 %)**.
   Every differing pixel is inside `HEADER#toolbar` (§12), confirmed by
   `document.elementFromPoint` at each differing coordinate and by a
   region-restricted diff.
   
   Cropping both captures to the `#chart` rectangle (0, 66, 1600×817) and
   diffing with the **browser's own PNG decoder** — no hand-rolled decoder in
   the path — gives **0 differing pixels across 1,307,200 compared pixels**.
   The chart, including every annotation, is therefore bit-identical whether
   it is reached by forward playback or by backward seek, and the residual is
   entirely outside the chart.

## 10. Canonical no-drawing baseline — the gate

The baseline is the non-negotiable gate and is **unchanged** in every value:

| Quantity | Expected | Observed |
| --- | --- | --- |
| bars | 1500 | 1500 |
| canonical events | 4862 | 4862 |
| trades | 47 | 47 |
| orders | 88 | 88 |
| fills | 95 | 95 |
| open positions | 1 | 1 |
| final balance | `7718.000000000193` | matches |
| final equity | `7737.0000000002065` | matches |

`test_canonical_baseline.py` asserts these values plus a metrics digest
(`6c23dc6c…`) and reported **33/33**.

Independently confirmed that a no-drawing strategy adds **zero**
`drawings_emitted` events, so annotations cost a strategy that does not use them
exactly nothing:

```
drawings_emitted events in no-drawing canonical baseline: 0
total canonical events: 4862
{'run_started': 1, 'strategy_initialized': 1, 'bar_processed': 1500,
 'strategy_decision': 1500, 'portfolio_snapshot': 1500, 'order_created': 88,
 'order_pending': 88, 'order_filled': 88, 'position_opened': 48,
 'position_closed': 47, 'run_completed': 1}
```

The `fills` metric counts **fill records** (`len(result.fills)` = 95), while
`order_filled` counts **order-status transition events** (88) — the pre-existing
orders/fills asymmetry, unchanged by this work and asserted by the passing
baseline test.

Annotations also remain order-neutral and economics-neutral: the Rust ordering
is `bar_processed → strategy_decision → drawings_emitted → order_created`, and
`test_annotations.py` checks X/X2/X3 assert that an annotated run and an
otherwise identical quiet run produce identical economics.

## 11. Build artifact and human-review run

**Final candidate wheel**

```
python/target/qa/final-wheels/observa-0.1.1-cp310-abi3-manylinux_2_34_x86_64.whl
sha256 9dbac2afcca72250cb1554e26a6b0e31df5e207590980f0341f79d81ad735cc8
```

Built with `maturin build --release` from `70a15e4b`. Verified inside the
artifact (not merely in the tree) that the renderer fix and the pane-release
helper are both present in the bundled `observa/static/js/drawing-renderer.js`.
Installed into a **fresh** virtualenv (Python 3.14.7), where it reports version
`0.1.1`, exposes `replay_payload`, and passes the annotation and baseline suites.

**Human-review run (offline, deterministic, bundled sample)**

```bash
python python/tests/make_annotation_demo.py
observa replay runs/annotation_demo
```

The CLI prints the URL it binds; press Play and use the **Annotations** button.

Contents of `runs/annotation_demo` (200 bars, 200 annotated bars, 807 canonical
events, 0 closed trades, 1 open position):

| Kind | Count |
| --- | --- |
| series `ema_10`, `vwap` (price pane) | 2 |
| series `zscore`, `delta` (separate pane) | 2 |
| `hline` level | 1 |
| rectangle zone (`add` at bar 20, `remove` at bar 60) | 1 + 1 |
| markers (every 30 bars) | 7 |
| labels (above / below / left / right) | 4 |

It exercises every fixed code path: continuous series in both panes, a
separate pane, a primitive with a real lifecycle, markers, and all four label
positions — with no network access and no wall-clock dependence.

## 12. Residual notes, scope audit, and gates

### Residual notes

1. **Random `position_id` UUID in persisted runs (pre-existing, out of scope).**
   Two runs of the demo differ in exactly **one** of 807 event lines: the
   `position_id` of the single opened position. All 200 `drawings_emitted`
   payloads are byte-identical. The UUID comes from `Uuid::new_v4()` in the
   engine's portfolio/run identity (introduced with the position-lifecycle
   work), is unrelated to annotations, and does not touch economics — counts,
   balances and the metrics digest all reproduce exactly. It is a genuine
   determinism observation for Leadership, but it predates OBS-AI-02, is outside
   the four required fixes, and touches economic identity, so it should get its
   own ticket with Finance/QA verification rather than be folded in here.
2. **Toolbar text anti-aliasing (verification noise, not a product defect).**
   The whole-frame seek delta is 31–34 px of 1,760,000 (0.0019 %). Every
   differing pixel lies in `HEADER#toolbar` — `playback-controls`,
   `#speed-select`, `#status-bar` (`#stat-balance`), `theme-control` — with
   values differing by **±1 in a single colour channel** on text glyphs, i.e.
   browser subpixel rasterisation between two screenshots. The chart canvas
   differs by **0 pixels**. This is why the harness now measures pixels in the
   chart region rather than PNG byte length.
3. **Primitive insertion order after a backward rebuild (cosmetic).**
   The primitive *set* is identical after a forward walk and a backward seek;
   only object key order differs. It produces no measured pixel difference
   beyond the toolbar noise above. Noted for completeness; no action taken,
   since normalising z-order is outside this ticket's scope.
4. **`serde_json` 1-ulp reload drift (pre-existing).** `events.jsonl` reloads
   exactly; a payload value can differ by 1 ulp (`1.0995` vs
   `1.0995000000000001`) with no visible effect. Unchanged by this work.

### Scope audit

- No merge, no publish, no tag, no version bump.
- `master` untouched (`0a49d11c`).
- OBS-AI-03 not started.
- No economic, execution, portfolio, metrics, or chronology change.
- Annotations remain descriptive only: they never influence orders, fills,
  spread, slippage, SL/TP, margin, portfolio, metrics, or ordering.
- No new public primitive was added; no `band`; `bar_color` remains accepted but
  not promoted.

### Gates

> **OBS-AI-02 fixes ready for QA re-check: YES**
> **Merge now: NO**
> **Create 0.1.2 release now: NO**
> **Begin OBS-AI-03 now: NO**

The candidate wheel is built and its SHA is recorded. Release and merge remain
Leadership decisions to be taken after QA re-checks `70a15e4b`.
