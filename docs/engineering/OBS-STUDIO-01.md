# OBS-STUDIO-01 — implementation and verification

Date: 2026-10-21. Branch: `obs-studio-mvp`. Local prototype, not released or
published. [Setup and usage](../STUDIO.md).

## Delivered behavior

Studio opens with a new conversation interface: projects and searchable history
in the sidebar, streamed Codex responses and tool activity in chat, explicit
permission cards, and a resizable research canvas. Conversations, experiment
metadata, artifacts and presentation history persist in SQLite. Reopening a
conversation resumes its native Codex thread rather than replaying prompts.

Codex creates strategy files through its normal tools and submits backtests
through a separate Studio MCP service. The user reviews copied source,
configuration and data identity before approving execution. Full snapshot files
can be downloaded from the review card, including support files and source too
long for the inline preview. The approved snapshot runs through the existing
Observa validator and Rust/Python engine in a Linux bubblewrap worker. The chat
displays actual job states and canonical results; failed runs do not get invented
metrics. Stop controls interrupt the provider and cancel active workers.

The canvas presents canonical metrics, price/equity charts, replay, positions,
orders and trade events. Both the canvas and trade explorer expand to fullscreen.
Trade selection can jump to its entry/exit bar. The original replay remains
accessible, including its existing drawing controls. Typed agent-generated
plots, tables and Markdown notes appear in chat and the canvas with explicit
interpretation labels and experiment references.

## Implementation boundaries and trade-offs

| Component | Responsibility |
| --- | --- |
| `python/python/observa/studio/app.py` | Authenticated loopback API, SSE, application lifecycle and scoped research endpoints |
| `store.py` | SQLite WAL records, durable event cursors and FTS5 history search |
| `codex.py` | Native App Server JSON-RPC transport, thread resume, streaming, approvals and interruption |
| `research_mcp.py` | Four conversation-scoped research tools; separate from the unchanged read-only MCP server |
| `experiments.py` / `worker.py` | Snapshot and approval binding, Linux isolation, actual canonical execution and inspection |
| `studio/src/` | React/TypeScript chat and research presentation; existing replay reducer and Lightweight Charts |

This is a local Python service with compiled static assets, avoiding a desktop
shell, Node runtime service, database server or new agent framework. The Codex
adapter owns provider-specific protocol details; no unused generic provider
hierarchy was introduced. Additional adapters will require their own protocol
and permission implementation. Thread identifiers are provider-specific.

The Rust engine, signal contract, financial calculations, event history and
existing replay/inspection APIs are unchanged. Studio UUIDs and SSE cursors are
application metadata, never economic ordering inputs. Generated artifacts are
not accepted as replacements for canonical metrics.

Approval binds SHA-256 hashes of copied source, explicit support files, CSV,
resolved configuration and recorded environment versions. Project edits after
approval preparation do not change the experiment. Snapshots are not full
environment lockfiles: dependencies must already be installed, and environment
provisioning is deferred. Snapshots retain absolute dataset provenance paths, so
relocating the data directory is not yet supported.

Loopback requests require the launch-session cookie, exact Host/Origin checks
and a write header. The bootstrap token is removed from the URL after exchange.
Research MCP credentials cannot approve execution or access other conversations.
Codex runs with native workspace-write/untrusted-command permissions; inherited
MCP servers are disabled for Studio threads without changing user configuration.
Codex's native read permissions are broader than the selected project. Workers
have narrower read-only runtime/snapshot mounts, writable output/scratch,
sanitized environment, no network, and resource/time limits. This is a
single-user trusted-code application, not an adversarial multi-user sandbox.

## Verification results

All listed tests were executed locally. Unit tests use protocol captures where
appropriate; production responses and the live acceptance run use real Codex.

| Verification | Result |
| --- | --- |
| Rust workspace, locked/offline | 292 tests passed |
| Existing Python regression scripts | All 15 passed; external installed-interface smoke also passed |
| Finance golden ledgers | 616 checks passed |
| New Studio suite | 20 tests passed against the installed wheel outside the repository |
| Legacy browser logic | Replay (17 groups), drawings (12), metrics (7), workspace all passed |
| Studio frontend state/formatting | 3 tests passed |
| TypeScript and Vite production build | Passed; five bundled static files included in wheel |
| Production npm dependency audit | No known vulnerabilities reported at verification time |
| Clean local wheel installation | Passed; no Python cache files included |
| Installed wheel in Chromium | Project/conversation creation, auth, draft preservation, no runtime errors, clean shutdown with active SSE passed |

The Studio suite covers durable history/search/cursors, path confinement,
stream reconciliation, exact approval decisions, unresolved/expired provider
requests, disconnection, interruption acknowledgment versus actual completion,
restart recovery, scoped credentials, artifact validation and snapshot downloads.
Worker tests run real bubblewrap subprocesses: immutable input approval,
deterministic repeated canonical events/metrics, local support imports,
validation failure, queued/running cancellation, and unavailable host files,
credentials and network.

Rust verification used:

```bash
PYO3_PYTHON=/usr/bin/python3.13 cargo test --workspace --locked --offline
python -m unittest discover -s python/tests -p test_studio.py -v
node --test python/tests/replay.test.js python/tests/drawings.test.js \
  python/tests/metrics_panel.test.js python/tests/workspace.test.js
npm test --prefix studio
npm run build --prefix studio
```

The host default Python 3.14 initially failed the existing PyO3 source-build
version check. Selecting Python 3.13 resolved the build without engine changes.
The resulting ABI3 wheel was installed into a clean Python 3.14 environment and
passed all 20 Studio tests, including real engine execution. Installed-browser
testing found and fixed a Ctrl-C traceback: Uvicorn re-raises SIGINT after
graceful shutdown. Final shutdown with a live SSE connection took 0.315 seconds.

### Real Codex research and restart

Verified with installed `codex-cli 0.154.0` and the existing authenticated account.
Codex generated a strategy, received native file permission, submitted its
backtest, waited for explicit snapshot approval, inspected the real result and
published a sourced scatter plot. The strategy enters after three prior bars
and closes the exact position ticket after eight, once only, on the bundled
200-bar dataset with interval `15m` and default costs.

Canonical experiment `283fccd1acdf4d83ad1a1c8a03e68906` returned final equity
`10000.84`, net profit `0.8400000000001455`, one closed trade, no remaining open
positions, costs `0.4`, and no rejected orders. These are fixture results for
integration verification, not evidence of investment merit. Unavailable metrics
stay unavailable; small nonzero drawdown is not rounded into a false zero.

The initial live run produced the approved experiment and plot. Browser testing
then exposed a chart autosizing feedback loop that prevented stable replay
interaction; fixing the chart container height resolved it. The subsequent
`--review-existing` acceptance pass verified chart playback, backward replay,
trade inspection/fullscreen, the original replay, artifact presentation, search,
mobile layout and no browser errors. It stopped/restarted Studio and received a
new real response on the **same native thread**, without creating a new run.

Evidence: [real workflow checks and canonical metrics](obs-studio-01/real-workflow.json),
[regression record and wheel hash](obs-studio-01/regressions.json),
[installed browser checks](obs-studio-01/installed-wheel.json),
[final Studio test output](obs-studio-01/studio-tests.txt).

Screenshots: [snapshot approval](obs-studio-01/02-approval.png),
[research canvas](obs-studio-01/03-results.png),
[fullscreen trades](obs-studio-01/04-trades-fullscreen.png),
[resumed conversation](obs-studio-01/07-resumed.png),
[mobile](obs-studio-01/08-mobile.png).

The evidence JSON preserves original local run paths and provider IDs for
traceability. Raw server logs containing launch credentials are not included.

### Remaining live verification limit

A later fresh acceptance run reached Codex and surfaced the account's **usage
limit** before preparing any experiment. No credits were purchased, plan changed
or successful result fabricated. The additional live-agent cancellation step
added to the harness was therefore not reached. Cancellation is covered by
automated interruption-protocol and actual worker-kill tests, but that new live
browser step still needs a run after the account allowance becomes available.
The successful research/resume evidence above predates this additional attempt;
the report does not claim a fresh final-version acceptance pass from start to end.

## Deferred scope

Linux/Codex only; one active turn per project. Other agents, per-run environment
locking, relocation, dataset paging, optimization scheduling, cross-run
comparison, generic MCP forms, image/HTML artifacts, terminal emulation, cloud
sync and live trading are deferred. Codex must be installed/authenticated with
available account allowance for new turns. Saved history and results remain
browsable without model execution. Detailed size/resource limits and local
permission boundaries are in [STUDIO.md](../STUDIO.md).

## Follow-up fix — command output streaming, 2026-10-23

A user moving-average research request exposed a valid pending command item
with `aggregatedOutput: null`. The adapter attempted `None + delta` on the first
output chunk, exiting its JSON-RPC reader with the reported connection error.
The fix in `studio/codex.py` treats absent/null initial output as empty text when
appending deltas. It preserves the existing command-output display limit and
uses the final completed item as authoritative. The
[App Server event contract](https://learn.chatgpt.com/docs/app-server#events)
describes optional aggregated output and ordered command-output deltas.

Two new regression tests reproduce the original failure, then pass with the
fix: nullable/empty/missing initial output with chunk ordering and truncation;
and an actual adapter JSON-RPC reader consuming start, deltas, completion, a
subsequent assistant message and turn completion without disconnecting. All
**22 Studio tests passed** in the development environment. This follow-up did
not rerun the live model/backtest acceptance workflow or change the engine.
Existing saved history is retained; restart Studio and send a new message in
the affected conversation to resume using the corrected adapter.

## Follow-up fix — stop controls and stale activity, 2026-10-23

The conversation status alone controlled the original icon-only stop button.
After a protocol error, the conversation could be interrupted while tool items
still said running, hiding Stop and preserving stale spinners on refresh. The
failed reader also left its App Server process alive. A disconnected browser
could not distinguish that stale presentation state from continuing execution.

The header now has a labeled **Stop agent** button, enabled for unfinished
turns, items, approvals or experiments. The composer retains a stop control.
Offline presentation identifies unknown status, stops animating stale tool
activity and explains terminal recovery. A failed stop request explicitly says
it could not confirm cancellation. The UI only returns from **Stopping…** after
the API has completed cleanup.

Native interruption has a bounded timeout and falls back to terminating the
adapter's owned process group. Unexpected reader failure closes that process
instead of leaving it unmanaged. Cleanup clears incomplete tool activity and
pending permissions, while preserving completed history and native thread IDs.
Startup also repairs stale items belonging to previously interrupted/error
conversations. A per-conversation stop lock keeps competing turns out of the
project until process cleanup finishes. No engine semantics changed.

Final verification passed:

- **28 Studio tests**, including actual subprocess termination on reader failure,
  broken interrupt transport, dead readers, pending connection cancellation,
  stale-state recovery and project exclusion during cleanup.
- **4 frontend tests**, including stop availability after errors and refresh.
- TypeScript check and Vite production build; the checkout's bundled UI was rebuilt.
- Chromium browser regression for refresh, mobile visibility, actual subprocess
  stopping, persisted stopped state and failed-stop/reconnect behavior.
- **Real Codex browser cancellation**: started a native turn, clicked Stop,
  confirmed the App Server process exited, the turn cleared, and the native
  thread ID remained. No backtest or file edit was requested in this check.
  This completes the live cancellation check deferred by the earlier quota limit.

`harness/studio_stop_review.py` uses isolated temporary application data and a
disposable subprocess for failure scenarios; `--real-codex` additionally checks
one actual Codex turn. The original backtest acceptance harness now selects the
labeled Stop button. Evidence: [browser checks](obs-studio-01/stop-verification.json),
[mobile Stop control](obs-studio-01/stop-mobile.png),
[state after Stop](obs-studio-01/stop-after.png).

For an old disconnected tab, restarting Studio and opening its newly printed
launch link is necessary; refreshing an obsolete port/session cannot load the
new backend. Existing projects and conversations are retained.

## Follow-up — replay parity and native chat controls, 2026-10-28

Studio now renders recorded strategy series (price and separate pane), regions,
lines, labels, bar colors and markers through the same renderer as the original
replay. Refactoring the renderer into chart-owned instances preserves the legacy
entry points and avoids cross-chart cleanup. Canonical execution markers and
open-position entry/SL/TP levels have independent visibility controls. Replay
speed, single-bar/first/last stepping, following and fit controls are restored.
Selecting a trade opens replay at its canonical exit (entry for open positions),
focuses its bar range and highlights its markers and duration. Backward seeking
rebuilds recorded drawing state without exposing later indicator samples.

The `/` menu and composer settings expose native model/effort choices,
Default/Plan collaboration modes and permission presets. `model/list`,
`collaborationMode/list` and `configRequirements/read` discover the installed
provider's options. Models are not hardcoded. `thread/start` / `thread/resume`
and `turn/start` carry selected settings; changes close only an idle adapter and
resume the same thread on the next message. A separate metadata connection does
not interrupt research. Settings persist in the existing conversation record.

Native decisions include once/session scopes, cancellation and exact proposed
command/network rule amendments. Decisions not offered by Codex are rejected.
Automatic review uses `approvalsReviewer: auto_review` and Codex's guardian
feature with on-request approval, rather than an application approval algorithm.
The sandbox-only automatic policy uses `never`; full access is separately
confirmed. Managed requirements can disable choices and Codex enforces them at
runtime. Studio's snapshot approval gate remains mandatory for its backtest tool.
See the [App Server contract](https://learn.chatgpt.com/docs/app-server) and
[permission modes](https://learn.chatgpt.com/docs/permission-modes); protocol
schemas from installed Codex 0.154.0 were checked as the integration baseline.

Limits: this is not an embedded Codex terminal or complete CLI-command mirror.
Login, compaction, skills/plugin management and generic interactive MCP forms
remain outside this UI. Existing runs without recorded indicator series cannot
acquire them retroactively. Research instructions now ask Codex to emit series
when developing indicator strategies. Large-run rendering still uses in-memory
payloads and full drawing folds; paging/downsampling remains deferred.

Verification for this follow-up:

- **35 Studio tests passed**, including native decision scopes/rules, managed
  permission restrictions, explicit full-access confirmation, model/effort/mode
  validation, persisted settings, concurrent project activity checks and metadata
  connection isolation. Existing real-worker/determinism/cancellation checks pass.
- **6 frontend tests passed**; TypeScript and production build passed.
- Legacy replay **17 groups**, drawings **13 groups**, metrics **7 groups** and
  workspace checks passed. The new drawing test verifies chart-instance isolation.
- Chromium exercised an actual isolated engine run emitting a moving average,
  separate histogram, region, line and signal marker. Speed, backward seeking,
  trade focus, fullscreen, drawing toggles and the original replay passed.
- Native Codex **0.154.0** supplied the real model/mode catalog. Two actual model
  turns passed: Plan with automatic reviewer configured, then Default with the
  sandbox-only automatic policy. The latter resumed the same native thread after
  settings changed. Browser refresh retained settings; no experiment duplicated.
  These small turns requested no privileged operation, so they verify native
  configuration acceptance/resume, not an automatic review verdict. Full access
  was tested for mandatory confirmation and protocol mapping, never enabled live.
- The existing Stop browser harness passed all six refresh/disconnect/subprocess
  checks after these changes. Browser runs reported no JavaScript errors.

Evidence: [live controls verification](obs-studio-01/controls-verification.json),
[trade highlight and indicators](obs-studio-01/trade-highlight.png),
[native settings](obs-studio-01/codex-controls.png),
[slash menu](obs-studio-01/slash-menu.png), and
[mobile controls verification](obs-studio-01/controls-mobile-verification.json). Reproduce with
`harness/studio_controls_review.py --real-codex --out <directory>`.
No Rust/Python financial semantics changed; the full Rust workspace and financial
ledger suites were not rerun for this presentation/provider-control follow-up.
Restart Studio and open its new launch link to load the rebuilt local assets.

## Follow-up — compact markers and integrated inspection, 2026-10-31

The built-in chart markers imposed a minimum shape size, which became especially
intrusive with enlarged selected markers and persistent text. Studio now uses a
small chart primitive that reads the current time-scale spacing on each draw.
Glyphs range from 2 to 8 CSS pixels, stay the same size on selection, and group
same-candle/same-shape overlaps. Selection uses color and the existing shaded
trade window; a thin dashed connector joins the recorded entry and exit. Marker
text moves into the candle tooltip, with all events retained in the bar inspector.

Candle hover displays UTC timestamp, OHLCV, exact samples from the folded drawing
series, strategy markers and canonical executions at that bar. Indicator gaps
are never filled or interpolated. Legend entries provide pane/help tooltips.
Account hover displays canonical equity and balance; balance can be toggled, and
the engine's recorded maximum-drawdown interval can be highlighted/focused after
replay reaches its end. Symbol, interval and price precision use persisted run
metadata. No economics are computed by this work.

Both original-replay links are removed from Studio. Drawing, replay navigation,
trade focus/fullscreen, balance/equity and drawdown inspection live in the current
chart. The standalone replay and compatibility route remain available to existing
callers; the browser regression still checks them directly.

Verification: 9 frontend tests passed (including marker rendering/grouping across
zoom and exact indicator samples), TypeScript and Vite production build passed,
legacy replay (17 groups), drawing renderer (13 groups), metrics (7 groups), and
workspace checks passed. Chromium passed 13 checks against an actual isolated
engine run with recorded SMA/histogram/annotation data. Tooltip values were
compared to the run's replay payload, and no browser exceptions were reported.
No provider/backend or engine change; no model calls or full engine-suite rerun
were needed for this chart-only follow-up.

Evidence: [chart verification](obs-studio-01/chart-polish-verification.json),
[hover details and compact markers](obs-studio-01/chart-tooltip.png).
Reproduce with `harness/studio_controls_review.py --chart-only --out <directory>`.
