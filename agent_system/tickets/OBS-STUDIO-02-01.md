# OBS-STUDIO-02-01 — native agent boundary and durable provider identity

Status: implemented and verified; live inference resume remains account-limited.
Parent: [OBS-STUDIO-02](OBS-STUDIO-02.md).

Extract the existing Codex orchestration behind a small explicit registry and
protocol. Route session, settings and approval operations by persisted provider;
keep native approval semantics and one active turn per project. Expose installed
providers and a bounded, non-inference readiness probe. Derive frontend labels
and available settings from the selected provider. Only Codex is enabled until
another real adapter meets its acceptance gate.

Replace schema-version resets with ordered transactional migrations and a
SQLite backup before upgrade. Preserve legacy Codex thread IDs, settings,
search, timestamps and experiments; refuse newer database schemas.

Acceptance: old Codex lifecycle regressions, malformed/unsupported providers,
cross-provider project locks, migration rollback/backup/future-schema refusal,
metadata probing, and real-browser native settings/restart checks. No changes to
financial semantics, provider global credentials or execution sandbox policy.

Implemented explicit registry/Agent protocol, provider-routed lifecycle/settings,
unsupported-provider rejection and readable unsupported-provider history. Native
permission validation remains in the Codex adapter boundary. The UI's new-agent
selector, labels and command availability use provider metadata. Only Codex is
registered. Check agent connection uses account/read, never a model turn.

SQLite schema 2 adds missing legacy provider identities without changing native
thread IDs or record timestamps. Upgrade uses a private consistent backup and
transactional migrations; future schemas are refused without changing the file.

Verification: 46 Python Studio tests, 13 frontend tests and production build
passed. Browser checks against the real installed Codex verified native catalog,
account probe, permission confirmation and settings persistence across refresh;
real-engine charts and subprocess stop/reconnect checks also passed. Logs under
`runs/studio-02-verification/provider*`. Transport doubles exist only in tests.
Live inference acceptance remains limited by the account condition in milestone 0.
