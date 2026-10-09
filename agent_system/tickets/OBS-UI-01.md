# OBS-UI-01 — Replay Workspace Redesign

Status: visually approved by the user; finalized for merge to master. Feature branch: obs-ui-01-replay-workspace.

Scope: the user-approved replay workspace redesign; no economics, strategy,
canonical reducer, or persistence changes. Explicit trade/chart interactions in
this ticket supersede the historical MVP exclusion. Merge to master authorized by the user after visual review. Do not release.

## Inspection findings

- Installed replay serves `python/python/observa/static` and `/api/replay`.
- Vanilla JavaScript, existing bundled Lightweight Charts v5; no build step.
- `events.js` loads bars/events/metrics, `replay-core.js` folds canonical history
  through a selected bar, and rendering consumes the resulting account,
  positions, orders and closed trades. Reducer remains untouched.
- `charts.js` owns charts; `events.js` unconditionally scrolls to position zero
  after every render, overriding user navigation.
- `panels.js` already has session-stored resize/collapse/tab state, pointer and
  keyboard handlers. CSS contains a stray brace before Trade Log styles and
  Inspector lacks a bounded height. Improve these instead of replacing them.
- Existing investigation overlays connect drawdown, candles, equity and trades.
- Metadata: replay run.symbol already exists; persisted
  config.dataset.interval is a string but is not forwarded by the adapter.
  Add optional presentation metadata only. Never infer interval from bar gaps.
- Metrics are the canonical full-run report; account is selected-bar state.
  Clearly distinguish these scopes. No new financial calculations.

## Implementation / verification

See docs/engineering/OBS-UI-01-report.md for final checks and review artifacts.

Final evidence: 39 browser checks and 13 real demo screenshots; canonical baseline,
replay/annotation, engine and server/CLI regressions pass. Merge to master authorized by the user after visual review. Do not release.

Final merge verification: replay (17 groups), annotations (12 groups), workspace tests,
demo (29), canonical baseline (33), API/server/CLI (76), and browser interaction
checks (39) passed. Approved screenshots preserved without regeneration.
