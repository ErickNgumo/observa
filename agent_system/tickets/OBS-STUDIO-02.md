# OBS-STUDIO-02 — multi-agent Studio and local delivery architecture

Date: 2026-11-09.
Status: implementation in progress; see milestone tickets below.

## Request

Define the architecture the implementation agent will follow for additional
coding agents, a terminal-free Linux launcher, an installer and a website that
opens the local application. The user permits pushes to the primary GitHub
branch. No release or public deployment has been requested.

## Deliverable

[Implementation architecture](../../docs/STUDIO_ARCHITECTURE.md) defines ownership,
adapter capabilities, native session identity, execution approvals, lifecycle,
storage/migrations, setup, packaging, deep links, verification and sequencing.
The canonical engine and existing public Python/CLI/MCP/replay contracts remain
unchanged. Proposed internal interfaces are explicitly not current public APIs.

## Baseline and primary branch

- `obs-studio-mvp` at `88ee0b4d` contains the working Codex Studio prototype.
- GitHub's default branch is `master`, verified at `4c5dbe93` before this work.
- There is no remote `main` branch. Use `master` as the user's primary-branch
  target without creating or renaming branches on GitHub.
- This documentation increment is isolated from the six Studio runtime commits.
  Their integration and fresh verification form milestone 0.

## Milestones

- [x] 0: Integrate Studio baseline and CI checks; [verification and live-account limitation](OBS-STUDIO-02-00.md).
- [x] 1: [Provider-aware adapter boundary, controls and persistence migration](OBS-STUDIO-02-01.md).
- [x] 2: [Local launcher and single-instance lifecycle](OBS-STUDIO-02-02.md).
- [ ] 3: [Claude native adapter and real lifecycle verification](OBS-STUDIO-02-03.md).
- [ ] 4: Private Linux installer and clean-machine acceptance.
- [ ] 5: Website/deep-link implementation; deployment separately authorized.
- [ ] 6: Cursor Agent and DeepSeek Harness compatibility and integrations.

Create a scoped implementation ticket for each milestone; update this checklist
only when its acceptance evidence exists. Narrow implementation details after
testing the installed provider interfaces and package environment. Unsupported
capabilities must remain explicit; do not invent provider feature parity.

## Architecture verification

Inspected Studio service, Codex adapter, SQLite store, CLI lifecycle, canonical
guide, architecture/scope documents and CI/release triggers. The plan calls out
current Codex coupling, schema-version migration work, native process ownership
and the separate Studio backtest approval boundary. Docs-only changes require
link/format/diff review, not new runtime test claims. Runtime implementation and
live additional-agent verification remain outstanding.
