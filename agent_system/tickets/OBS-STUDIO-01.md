# OBS-STUDIO-01 — local conversation-driven research MVP

Status: implemented on `obs-studio-mvp`; ready for review, not released.

## Authorized scope

User-approved first usable Linux/Codex Studio: create project, persistent
conversation, real Codex App Server, approve an immutable backtest request,
execute the existing engine, inspect results, restart and resume.
Include search, cancellation, streamed activity, research artifacts, fullscreen
canvas/trades, setup instructions and regression verification. Do not publish.

## Boundaries and decisions

- Rust/Python economics and the existing CLI, replay and read-only MCP remain
  authoritative and compatible.
- Python local HTTP service, SQLite WAL, React/TypeScript static frontend.
- Codex App Server stdio; native threads persisted by Codex. A provider adapter
  owns protocol details. No second agent harness or invented agent responses.
- A separate Studio MCP service submits scoped research requests. It does not
  extend the existing read-only MCP contract.
- Backtests run only after approval of snapshotted code, CSV, configuration and
  environment metadata. Linux bubblewrap isolates workers without network.
- Localhost authentication, same-origin checks and scoped MCP credentials.
- Agent-generated artifacts are labeled separately from canonical engine data.
- No economic changes; no new financial algorithms in frontend or backend.

## Acceptance / verification

Track implementation, automated tests, real execution and known limitations in
`docs/engineering/OBS-STUDIO-01.md`. A successful build alone is insufficient:
verify real Codex, an approved canonical run, browser inspection and restart.

The real workflow and native-thread resumption passed on 2026-10-21. Automated
regressions and installed-wheel execution also passed. A later fresh live run
was stopped by the Codex account usage limit before executing a backtest; the
added live-agent cancellation check remains unverified. Worker cancellation and
provider interruption protocol are covered by automated tests. See the report
for exact evidence, verification coverage and deferred features.

## Follow-up: nullable command output (2026-10-23)

User-reported command streaming disconnected with `NoneType + str` when Codex
sent `item/started` with `aggregatedOutput: null`, then an output delta. The
adapter used `dict.get(field, "")`, which handles an absent key but returns
`None` for an explicit JSON null. Treat the initial null as empty output when
appending text; retain ordered chunks and the existing display-size limit.

Two regression tests failed with the reported exception before the fix and
passed afterward. They cover null/empty/missing initial output, multiple chunks,
truncation, and a JSON-RPC reader sequence through command completion, the next
agent message and turn completion without disconnecting. All 22 Studio tests
passed with `.venv-dev/bin/python -m unittest discover -s python/tests -p
test_studio.py -v`. No engine or frontend changes, no model calls needed for
this deterministic reproduction. Restart the running Studio service to load the
fix, then reopen the saved conversation and send a new message to resume.

## Follow-up: visible stop and interrupted-session cleanup (2026-10-23)

The reported interrupted command still showed a spinner after refresh, while
the composer had switched back to Send. Stop availability now accounts for
unfinished items, approvals, experiments and turn IDs, in addition to active
conversation status. A labeled **Stop agent** control stays in the header.
Disconnected UI states explain that stopping cannot be confirmed and provide
terminal recovery instructions.

Reader failure now closes the adapter's owned process group; bounded native
interruption falls back to process termination. Stop cancels pending connection
tasks and experiments, expires permissions, marks unfinished items interrupted,
clears stale turn/error state and preserves the native thread reference. New
turns cannot start in that project while stop cleanup holds its lock. Restart
recovery also settles items from earlier already-interrupted conversations.

Added subprocess lifecycle and browser regressions, plus a real Codex browser
interruption check. See the engineering report for final verification results.

## Follow-up: replay parity and Codex chat controls (2026-10-28)

User review identified fixed-speed playback, missing indicator/drawing rendering,
weak chart focus on trade selection, and inaccessible model/mode/permission
controls. Restore these within the existing Studio and canonical replay boundary.

Implemented: replay speeds and bar stepping, independent drawing/marker/position
level toggles, follow/fit navigation, trade selection highlight and range focus.
The original drawing renderer now supports isolated chart instances and retains
its legacy global entry points. No financial calculation or engine change.

Added native model/effort and collaboration mode discovery, per-conversation
settings, slash-command UI, native automatic review and sandbox permission
presets, plus session and proposed-rule approval decisions. Full access requires
explicit user confirmation. Managed Codex restrictions are checked and the
provider remains authoritative; immutable backtest approval stays separate.
Settings changes preserve native thread IDs and are blocked during project work.
No additional agent harness, paid dependency, release or publication.

Verification and remaining boundaries are recorded in
`docs/engineering/OBS-STUDIO-01.md` and `docs/STUDIO.md`.
