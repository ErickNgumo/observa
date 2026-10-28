# Observa Studio — local prototype

Studio is the conversation-first research interface on the `obs-studio-mvp`
development branch. It uses your installed Codex CLI and the existing Observa
engine. It is not published or hosted.

## Setup on Linux

Prerequisites:

- Python 3.10–3.13 with virtualenv support for source builds; Rust/Cargo to build
  the local engine. The existing PyO3 version does not build directly with
  Python 3.14. A built ABI3 wheel also passed the Studio tests on Python 3.14.
- Node.js 22.18+ and npm to build the frontend and run its tests.
- `bwrap` (bubblewrap), available through Linux distribution packages.
- Codex CLI **0.154.0** is the verified App Server version. Authenticate with
  `codex login` before starting Studio. Use your existing account; Studio does
  not collect API keys or implement another authentication flow. See the
  [official Codex CLI documentation](https://developers.openai.com/codex/cli/).

From the repository root:

```bash
python3.13 -m venv .venv-studio
source .venv-studio/bin/activate
python -m pip install 'maturin>=1.5,<2'
npm ci --prefix studio
npm run build --prefix studio
maturin develop --release --extras studio --manifest-path python/Cargo.toml
observa studio
```

`observa studio` opens a browser and prints a local launch link. If needed, use
`observa studio --no-browser` and open that link yourself. It contains a local
session token in the URL fragment; the application exchanges it for an HttpOnly
cookie and removes it from the address bar. Do not share the launch link.

Optional arguments:

```bash
observa studio --port 8766 --data-dir /path/to/private/studio-data --no-browser
```

Only `127.0.0.1` is supported. One Studio process can own a data directory at a
time. Restart with the same directory to retain research. Node is needed for
building, not for running a built installation.

**Do not run `pip install observa`.** The public PyPI package is unrelated. Use
this repository's build. To build a local wheel, first build the frontend, then
run `maturin build --release --manifest-path python/Cargo.toml`. Install the
resulting wheel with its `[studio]` extra. No release or upload is needed.

## First research session

1. Create a project. Leave the directory field blank for a dedicated folder, or
   select an existing directory containing trusted strategy source and CSV data.
2. Start a conversation. For example:

   > Create a moving-average strategy using the bundled sample data. Explain
   > your assumptions, use interval 15m, and prepare a backtest for my approval.

3. Review Codex file or command permissions in chat. File permissions show the
   proposed changes. Studio's own scoped research tools are enabled; a backtest
   always requires a separate **Approve & run** decision.
4. Inspect the strategy and configuration in the backtest approval card. The
   approval binds the copied code, data and configuration, not mutable project
   files. Declining does not execute or import the strategy.
5. Choose **Explore result** to inspect canonical metrics, equity, price replay,
   trades, orders and evidence. Selecting a trade opens price replay, highlights
   its duration and markers, and focuses its canonical entry/exit bars. Expand the canvas or trade explorer for more room.
6. Continue discussing the result. Codex can publish labeled research plots,
   tables and notes alongside the engine result.
7. Close the browser or stop Studio. Reopen with the same data directory, select
   the conversation and send another message. Studio resumes the native Codex
   thread. History is searchable across projects.

**Stop agent** in the conversation header interrupts Codex and cancels active
experiments in that conversation. A stop control also appears beside the
composer. Stop remains available when unfinished tool activity survives an
error or a browser refresh. If Codex cannot acknowledge interruption, Studio
terminates its owned process instead. The button shows **Stopping…** until
cleanup finishes. Backtests also have their own cancel button. Interrupted work
is never automatically rerun after a restart; request a new experiment explicitly.

If the browser says **Connection lost**, it cannot confirm whether the agent is
running or stop an unreachable service. Press Ctrl+C in Studio's terminal if it
is still running, launch `observa studio` again, and open the **new launch link**
printed there. Refreshing an old address is insufficient if the port or session
token changed. Saved conversations remain available. Restart recovery marks
stale tool activity as interrupted rather than leaving a spinner running.

`@sample` selects the bundled 200-bar sample. `@demo` selects the longer bundled
dataset. Both are historical fixtures, not live market feeds. For your own data,
place a CSV in the project and name its relative path. Declare the interval and
execution assumptions. Annualised metrics remain unavailable when the engine
lacks sufficient information; Studio does not fill in missing metrics.

## Replay and Codex controls

Price replay includes **0.5×, 1×, 2×, 5×, 10× and Max** playback, first/last
and single-bar stepping, follow/pan and fit controls. Toggle strategy drawings,
execution markers and open-position entry/SL/TP levels independently. Indicators
use the strategy's recorded `drawings` series, including a separate indicator
pane. They are revealed only through the replay cursor. A historical run that
did not record indicator values cannot display them retrospectively; ask Codex
to emit the series and prepare a new backtest. The original replay stays linked.

Type `/` in chat to see Studio commands, or click the settings beneath the
composer. These are client controls backed by native Codex App Server APIs:

| Command | Behavior |
| --- | --- |
| `/model` | Select an available model and supported reasoning effort from your installed Codex. |
| `/mode` | Select native Default or Plan mode. Switch back to Default to implement a plan. |
| `/permissions` | Choose the permission policy below. |
| `/status` | Show saved settings, current status and native thread ID. |
| `/stop` | Stop active research in this conversation. |
| `/new` | Create a conversation in the current project. |
| `/help` | List these commands. |

Settings are saved per conversation and apply to the next message. Stop active
research before changing them. Changing settings resumes the same native thread;
it does not erase history. Managed Codex requirements remain enforced. Unknown
slash commands display help instead of being submitted as agent prompts.

Permission choices:

- **Ask before commands** (default): Codex's untrusted-command approval policy.
- **Ask when needed**: routine workspace work proceeds; broader access asks you.
- **Approve for me**: native Codex automatic review handles eligible requests.
- **Read only**: inspect files; writes and broader operations require approval.
- **Automatic within sandbox**: no prompts; operations outside the sandbox fail.
- **Full access**: unrestricted filesystem/network access without command
  approvals, requiring an explicit confirmation in the settings dialog.

Approval cards show the native choices offered for that request: allow once,
allow for the session, decline, cancel the turn, or save a proposed command/network
rule. Review the displayed rule before saving it. Automatic review is provided by
Codex, not an Observa decision algorithm. It requires a compatible installed CLI.
Studio's **Approve & run** gate for snapshotted backtests remains separate under
all presets. These controls do not embed the CLI terminal or every CLI slash
command (for example `/login`, `/compact`, skills and plugin management).

## Storage and permissions

The default data directory is `$XDG_DATA_HOME/observa/studio`, or
`~/.local/share/observa/studio`. It contains SQLite application history and
`experiments/<id>/snapshot` / `experiments/<id>/output/run` directories. Projects
created by Studio live in the sibling `projects` directory. Native Codex thread
history and credentials remain in Codex's own configured storage.

Back up the Studio directory, project directories and native Codex history to
preserve both evidence and resumable agent sessions. Keep snapshots in their
original locations: the existing replay loader verifies the recorded CSV source
path and identity. Moving the data directory is not a supported relocation
workflow yet.

Studio requires same-origin authenticated requests and rejects arbitrary Host
headers. Its MCP credential grants only conversation-scoped research operations;
it cannot approve requests, create projects or inspect other conversations.

By default Codex uses **workspace-write** and **untrusted-command approval**,
with network disabled for sandboxed commands and no writable `/tmp` exception.
The permission presets above explicitly change this policy for the conversation;
Full access removes Codex sandbox restrictions. This is Codex's normal local coding permission model: it can read
files allowed by its native sandbox, and asks before broader operations. Project
selection is not a complete confidentiality boundary for Codex reads. Review
any request for additional filesystem or network access. Inherited user MCP
servers are disabled for Studio threads; the user's configuration is not edited.

Backtest workers have a separate, narrower Linux sandbox: only runtime
directories and the approved snapshot are readable, only the experiment output
and scratch space are writable, and networking is disabled. Credentials are
removed from the worker environment. Workers have memory, file-size and a
10-minute execution limit; Studio fails closed if bubblewrap cannot start.
These protections are for trusted research code, not a hardened multi-user
service for adversarial programs. Do not expose Studio to the network.

Local-first means application data and execution stay on this machine. Prompts,
tool outputs and relevant source context are sent to the model service used by
your configured Codex account. Studio adds no hosting service or paid dependency.

## Research artifacts

Codex receives four Studio MCP tools: `get_project_context`, `prepare_backtest`,
`get_experiment`, and `publish_artifact`. The ordinary `observa mcp` server remains
read-only and unchanged.

`prepare_backtest` accepts a project-relative strategy file, optional class name,
CSV or `@sample`/`@demo`, `observa.Config` fields and explicit support files. It
waits for approval and actual completion. Local imports must be included as
support files; installed dependencies must already exist in Studio's Python
environment. Environment versions and file hashes are recorded. Studio does not
automatically install dependencies or create a locked environment per run.

`get_experiment` returns canonical metrics, trades and rejections. Pass an exact
`position_id` for its orders, fills, reasons, costs and annotations.

`publish_artifact` accepts JSON with `title`, `description`, `experiment_ids` and:

```json
{
  "title": "Recorded trade P&L",
  "description": "Values copied from this experiment's canonical closed trades.",
  "experiment_ids": ["<experiment-id>"],
  "kind": "plot",
  "mark": "scatter",
  "x_label": "Trade index",
  "y_label": "Net realised P&L",
  "data": [{"x": 1, "y": 0.84}]
}
```

The example number illustrates the schema; agents must populate actual data
from the referenced evidence. Supported plot marks are `line`, `scatter`, `bar`
(including pre-binned histograms), and `heatmap` (with a numeric `value` per
point). Hover points for their values. Other formats are
`{kind:"table", columns:[...], rows:[[...]]}` and
`{kind:"markdown", text:"..."}`. Artifacts are labeled **agent-generated
interpretations**, even when they cite engine results. Arbitrary HTML and script
artifacts are not accepted. Limits: 2 MiB per artifact, 10,000 points/rows.

## Compatibility and current limits

- Existing Python, CLI, read-only MCP and `observa replay` workflows are intact.
  The research canvas reuses the original annotation renderer and also links
  to the original replay.
- Linux and Codex only. Other providers can implement the adapter boundary later;
  provider thread IDs are intentionally not portable between agents.
- One active agent turn per project. No simultaneous editing agents in a project.
- CSV datasets up to 256 MiB; source snapshots up to 20 MiB and 100 explicitly
  selected files. The canvas loads one run's replay payload in memory; very large
  datasets need future paging/downsampling work.
- No downloads, environment provisioning, optimisation scheduler, cross-run
  comparison workspace, live trading, cloud sync, image/HTML artifacts, terminal
  emulator, or generic MCP elicitation forms in this MVP.
- Keep Codex installed and authenticated to resume native sessions. History and
  saved results remain browsable without an active agent connection.
- Codex App Server is an evolving interface. Other versions are not yet verified;
  protocol errors are surfaced, not replaced with mocked responses.

## Verification

```bash
python -m pip install httpx playwright hypothesis  # development-only checks
python -m playwright install chromium
python -m unittest discover -s python/tests -p test_studio.py -v
npm test --prefix studio
npm run build --prefix studio

# Makes real model calls on your existing account and approves only the
# controlled test strategy and its backtest. No mocked agent interactions.
python harness/studio_review.py --real-codex --out /tmp/observa-studio-review

# Stop/refresh/disconnect browser regression with disposable subprocesses.
python harness/studio_stop_review.py --out /tmp/observa-studio-stop
# Optionally also start and interrupt one real Codex turn:
python harness/studio_stop_review.py --out /tmp/observa-studio-stop-live --real-codex

# Annotated real-engine replay, slash settings from the installed Codex, and
# optional live turns exercising mode/permission changes and native resume.
python harness/studio_controls_review.py --out /tmp/observa-controls --real-codex
```

The real-browser harness checks project creation, native permissions, snapshot
approval, actual engine output, replay, fullscreen trade inspection, artifacts,
search, service restart and native thread resumption. It saves evidence and
screenshots in its output directory. See
[implementation and verification notes](engineering/OBS-STUDIO-01.md).
