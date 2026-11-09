# OBS-STUDIO-02-00 — integrate and verify the Studio baseline

Status: baseline integration verified with a live-account limitation.
Parent: [OBS-STUDIO-02](OBS-STUDIO-02.md).

The user authorized implementation of the delivery architecture and verified
pushes to the primary branch (`master`). Integrate the existing six Studio
commits without changing economics. Add CI gates for frontend build/tests,
installed Studio tests and chart/browser execution. Keep provider-account tests
opt-in; run the live Codex acceptance locally and report any account blocker.

Acceptance: existing Rust/Python/legacy JS regressions, Studio service and worker
tests, frontend tests/build and a real-engine browser run pass. Record live Codex
research/restart/cancellation evidence or the precise external blocker. No release
tag, installer publication or website deployment.

Verification on 2026-11-09: Rust workspace tests passed; all 14 existing Python
suites passed (including 149 MCP checks), and the independent golden ledgers
passed 616 checks. Studio passed 35 tests; frontend passed 13 tests and its
production build; all four legacy JavaScript suites passed. Chromium passed
18 real-engine chart checks and six stop/reconnect checks with real disposable
subprocesses. Local logs: `runs/studio-02-verification/`.

Fresh native Codex 0.154.0 authored a strategy, requested file approval, prepared
an approved 15m sample backtest, completed its canonical one-trade result and
published a sourced plot. Browser replay/inspection and persisted history after
service restart passed. The next native resume turn reached Codex but failed
with the account's usage-limit response. Live resume completion and the final
live stop step remain blocked by that allowance; prior acceptance evidence is
retained under `docs/engineering/obs-studio-01/`. No model retry loop, paid credit
purchase or fabricated success was used.

CI now builds Studio before wheel packaging and checks its installed service,
real sandboxed workers, charts and cancellation. Ubuntu CI's disposable runner
enables user namespaces when AppArmor restricts them; no product sandbox policy
is weakened. Hosted CI execution is reported separately from these local results.
