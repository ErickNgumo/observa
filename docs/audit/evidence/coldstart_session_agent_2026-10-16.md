# Observa cold-start log

Material: README.md only. Environment: python3.13 venv in this directory. Wall clock 12:47:18 -> 12:49:12.

## Step 1 - read README (12:47:18 - ~12:47:23)
Command: `date +%T && ls -la && cat README.md`
Output: README with install, demo, strategy, inspection, replay sections.
Friction: README links to ~10 docs (docs/getting-started.md, docs/strategy-contract.md, ...) and `examples/eurusd_demo.py`, none of which are available to a wheel-only user (README says "lives in the repository"). The wheel-only user cannot follow them. README never mentions that the strategy guide/spec ship inside the package or how to reach them (`observa.agent_guide_path()`, `observa.agent_spec()`); it only says "Observa ships ... strategy instructions, a working example, a machine-readable description" with no function names.

## Step 2 - create venv and install (12:47:23 - 12:48:17)
Commands:
`python3.13 -m venv venv` (12 s)
`./venv/bin/python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.6-private-mvp/observa-0.1.6-cp310-abi3-manylinux_2_34_x86_64.whl"`
Output: `Successfully installed ... mcp-2.3.0 ... observa-0.1.6 ...` (~42 s, dependencies from cache/network).
Friction: none. README says `python -m pip` assuming an active venv, which the README does not mention creating; I used the venv python directly. Minor (P3): no venv hint.

## Step 3 - discover API (12:48:24 - 12:48:30)
Commands: `./venv/bin/python -c "import observa; print([n for n in dir(observa) ...])"`, `./venv/bin/observa --help`, then `observa.agent_guide_path()` / `agent_example_path()`; read the guide from site-packages.
Output: CLI help lists replay, mcp, agent-spec, validate-strategy. dir() shows agent_guide_path, agent_spec, etc.
Friction:
- I had to guess `dir(observa)` to find the guide; README names no function. `observa agent-spec` appears in `--help` but README does not mention it.
- `observa.samples` is not available as an attribute after `import observa` (AttributeError) although the README uses `from observa.samples import EmaCrossover`. That form (a submodule import) works; only attribute access fails. I did not need it (P3).
- README documents `EmaCrossover` sample, but I wrote my own as asked; I never tried it.
- The packaged guide says `docs/execution-model.md`, `llms-full.txt` for deeper reference: not shipped, unreachable.
- The guide said "or the same wheel with `[mcp]`" in section 12 which conflicts with the README ("no extra needed"). Minor inconsistency.
- Good: the guide was clear on lists-not-dicts, `close` needing a ticket, `position_id`, lowercase directions, warm-up guard.

## Step 4 - write strategy.py and run.py (12:48:30 - 12:48:40)
Wrote `strategy.py` (EMA 12/26 computed incrementally on bar["close"]; long 1 lot on cross up when flat; close with exact ticket on cross down) and `run.py` (README pattern: demo_data_path, Config, output="runs/ema-cross").
Friction: I had to decide EMA seeding (first close; 26-bar warm-up guard) - not in any doc, my assumption. The README strategy example has no EMA/indicator helper and no close example (it defers to the unreachable docs); I got the close syntax from the packaged guide.

## Step 5 - validate (12:48:40 - 12:48:41)
Commands: `./venv/bin/observa validate-strategy strategy.py --json` and `... --smoke --json`
Output: `"valid": true, "errors": [], "tiers_run": ["A","B","C"]`, exit 0 both; smoke ran 6 bars, 0 signals.
Friction: none. Output is clear.

## Step 6 - run (12:48:45 - 12:48:46)
Command: `./venv/bin/python run.py`
Output: `{'status': 'completed', 'artifact_dir': 'runs/ema-cross', 'total_bars': 600, 'trades': 11, 'open_positions': 1, 'final_balance': 10559.0, 'final_equity': 10731.0, 'events': 1895, 'metrics': {...total_return_pct 7.31, max_drawdown_pct 6.19, win_rate_pct 27.27, profit_factor 1.75, sharpe 0.68}}`
Run time under 1 s.
Friction:
- `result.summary()` returns a dict that print() dumps on one very long line, unreadable (P3).
- `trades: 11` counts closed trades and `open_positions: 1` is separate; `final_equity` (10731) differs from `final_balance` (10559) because of an open position at the end of data. The README and summary do not explain this; I worked it out. (P3)
- Default Config applies spread 0.0002, slippage 0.0001, commission 0 (found in run.json); README example uses commission=7.0 and does not state the defaults. Not a defect, but results depend on defaults I only learned by reading run.json. (P3)
- `dataset_source` in summary is an absolute site-packages path; fine.

## Step 7 - inspect (12:48:52 - 12:48:58)
Command: `./venv/bin/python inspect_it.py` (observa.inspect_run("runs/ema-cross"): trades(), rejections(), positions(open=True))
Output: 11 trades (3 winners, 8 losers, net rows e.g. bar 38: buy 1.15453 -> 1.1536, -93.0; best +893 at bar 587); rejections: `[]`; one open position (opened bar 589 at 1.16842, 1.0 lot) still open at the end. Final balance 10559.00, final equity 10731.00.
Friction: trade rows have `bar_index` but no entry/exit timestamps and no opening reason (the strategy `reason` is in events only); `trades()` entries lack the reason I recorded, and README does not show how to get decisions/reasons from Python. (P3). Floating-point noise in pnl (-93.00000000000975) (P3).
Also: sell exit price mirrors 1.1536 repeatedly - plausible given spread/slippage rounding; not investigated.

## Step 8 - replay (12:48:58 - 12:49:12)
Commands: `./venv/bin/observa replay runs/ema-cross --port 8765 > replay.log 2>&1 &` ; `curl http://127.0.0.1:8765/` -> 200; stopped with `pkill -f "observa replay runs/ema-cross"`; curl afterwards -> 000 (stopped).
Output: "Replaying canonical run: ... Open http://127.0.0.1:8765 in your browser".
Friction: `observa replay` blocks the terminal; there is no documented non-blocking CLI flag, so I backgrounded it from the shell (the `ReplayServer` class exists in dir(observa) but README does not document it). I did not open a browser, so I only confirmed HTTP 200 for `/`, not that the UI renders. My pkill pattern also matched and killed my own shell wrapper (exit 144); my mistake, not Observa's.

## Result
Succeeded. Total elapsed from first command (12:47:23, venv creation) to inspected result (12:48:58): about 1 min 35 s of wall-clock (12:47:18 to 12:49:12 including README reading and replay check: ~1 min 54 s). Active human-equivalent effort is larger because I had to read the packaged guide.

## Friction summary

| # | Category | Severity | Expected | Actual | Recovered alone |
|---|----------|----------|----------|--------|-----------------|
| 1 | DOCUMENTATION | P2 | README (the only material) to be enough to write a close-on-signal strategy; linked docs reachable | All doc links (strategy-authoring, strategy-contract, execution-model, getting-started...) and `examples/eurusd_demo.py` are repo-only; wheel user cannot open them. README example has no close/ticket example | Yes, via guesses of `dir(observa)` and `agent_guide_path()` |
| 2 | DOCUMENTATION | P2 | README names the in-package guide/spec/example entry points | Says "Observa ships ... strategy instructions, a working example, a machine-readable description" but gives no function names (`agent_guide_path`, `agent_example_path`, `agent_spec`, `observa agent-spec`) | Yes |
| 3 | DOCUMENTATION | P3 | README demo (`python examples/eurusd_demo.py`) works for a pip user | File not in the wheel; user must use the second code snippet | Yes |
| 4 | DOCUMENTATION | P3 | README/guide consistent about MCP extra | Packaged guide section 12 says "or the same wheel with `[mcp]`"; README says no extra | Yes (ignored) |
| 5 | INSTALLATION | P3 | README mention creating/activating a venv | `python -m pip` with no env guidance | Yes |
| 6 | OTHER | P3 | `observa.samples` accessible after `import observa` | AttributeError on attribute access (`from observa.samples import ...` works) | Yes |
| 7 | RESULTS | P3 | Readable summary and explanation of equity vs balance | `summary()` is a one-line dict dump; open position at end explains equity != balance, not explained | Yes |
| 8 | CONFIG | P3 | Default costs stated | Defaults (spread 0.0002, slippage 0.0001, commission 0) only visible in run.json | Yes |
| 9 | RESULTS | P3 | trades() include timestamps/reasons; clean floats | Only bar_index; no entry reason; pnl float noise | Yes |
| 10 | REPLAY | P3 | Documented non-blocking replay (task mentioned one) | CLI blocks; `ReplayServer` undocumented in README; I backgrounded the process. UI rendering not visually verified (no browser) | Yes |

Counts: P0 0, P1 0, P2 2, P3 8. No errors or exceptions from Observa itself occurred.
