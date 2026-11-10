# OBS-STUDIO-02-02 — Linux desktop launcher

Status: implemented and verified, 2026-11-10.
Parent: [OBS-STUDIO-02](OBS-STUDIO-02.md).

Implement an application-menu entry using the installed Python runtime and
existing browser interface. Start or reopen one service per data directory;
private Unix socket control, same-user peer checks, retained data lock, bounded
readiness checks, single-use launch tokens and an authenticated Quit action.
Handle simultaneous launch, stale sockets, restart and missing GUI shell PATH.
Accept only `observa://open` and its equivalent trailing slash normalized by
Linux GIO. Reject parameters, fragments and other paths. No website deployment.

The private prototype may use the current development environment and installed
Codex. Public installer and terminal-free provider setup are later milestones.
Verify actual subprocess and browser behavior without touching user research.

## Delivered

- Installed-runtime `observa-studio` entry point and managed Linux desktop entry;
  absolute interpreter, no activated shell, terminal or repository cwd required.
- Single service per research directory, using its existing flock and an owned,
  private Unix socket with same-user peer checks. Repeated launches obtain fresh
  URLs; stale owned sockets recover without killing unrelated processes.
- Readiness checks, bounded retries and private rotating startup diagnostics;
  Zenity Retry/Close recovery dialog when available. Browser closing leaves work
  running; authenticated Quit stops owned agents/workers through existing cleanup.
- Five-minute single-use bootstrap tokens, separate HttpOnly session cookie,
  unchanged Host/Origin/CSRF protection. Website links contain no credentials.
- GIO adds a trailing slash to authority-only URIs: accept that equivalent form,
  while rejecting query strings, fragments, commands and non-root paths.
- Existing CLI launch, research storage, provider settings and engine behavior
  remain intact. No inference requests are needed to launch or browse history.

## Verification

Local evidence under `runs/studio-02-verification/` (ignored; private test logs):

- `launcher-tests.log`: all 55 Studio tests passed. New tests start actual
  service subprocesses and cover concurrent clicks, fresh/replayed/expired
  tokens, authenticated Quit and CSRF, saved history after restart, SIGKILL crash
  recovery with interrupted activity, occupied port, stale socket and unsafe
  runtime/control-file rejection. The nine launcher tests passed again after
  the GIO compatibility fix (`launcher-final-tests.log`).
- `launcher-frontend.log`, `build-launcher.log`: 13 frontend tests and production
  TypeScript/Vite build passed.
- `launcher-browser/verification.json`: six desktop/browser checks passed with
  real `gio launch`, `desktop-file-validate`, isolated XDG storage and
  `PATH=/usr/bin:/bin`. The registered handler opens/reopens one service, removes
  the bootstrap URL, preserves a project/conversation across Quit/relaunch and
  reports no JavaScript errors. The browser-open hook captures the local URL for
  Playwright; no native agent interaction is mocked. Screenshots inspected.
- `launcher-charts/verification.json`: 18 real-engine/replay checks passed;
  `launcher-stop/verification.json`: six stop/refresh/disconnect checks passed
  with owned disposable subprocesses. No new model turn was required; account
  limitations from milestone 0 remain separate from launcher verification.
- Added desktop/browser regression to installed-wheel CI. The preceding baseline
  and provider commits both passed hosted CI, including Rust/Python/legacy replay
  checks. Financial code was not changed by this milestone.

Installed and validated the shortcut at
`~/.local/share/applications/org.observa.Studio.desktop`, registered for
`x-scheme-handler/observa`. An older service still holds the user's default data
lock; it was left untouched. Close that old instance once before using the icon.

Follow-up, 2026-11-10: the user authorized restarting the idle installation after
seeing the startup-error dialog. Its log contained only data-directory ownership
conflicts. Shut down the identified service through its private control socket,
waited for process exit, and restarted through the installed launcher's runtime.
Authenticated `/api/state` confirmed the saved project and five conversations;
another launcher invocation opened the browser and reused the same service.
Dismissed the identified stale error dialog. No research records were deleted or
resubmitted. Hosted CI passed for launcher commit `ff88cbc5` and documentation
commit `5027cf66`.

## Limits and next milestone

The prototype shortcut depends on this checkout's `.venv-dev` runtime and built
assets. It is not the self-contained installer. Zenity is optional for this
development launcher; the eventual installer must provide its GUI prerequisites.
Application icon/deep-link launching has been verified with a captured browser
dispatch and real headless Chromium, not every desktop/browser distribution.
Claude Code integration is next, followed by installer clean-machine acceptance;
no agent installation, published package or website deployment is included here.
