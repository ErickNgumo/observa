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
