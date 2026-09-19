# AGENTS.md — writing an Observa strategy

You are implementing a **user trading strategy** on top of Observa. This file is
the whole instruction set; no Observa-specific syntax should need to be
explained to you by a human.

## 1. Discover the contract — do this first

```bash
python -c "import observa, json; print(json.dumps(observa.agent_spec(), indent=2))"
python -c "import observa; print(observa.agent_guide_path())"     # short guide
python -c "import observa; print(observa.agent_example_path())"   # gold example
```

Read the spec and the guide, then imitate the gold example. The spec is the
canonical machine-readable contract; these docs are commentary on it.

## 2. Rules

1. Use the canonical Observa strategy contract only — `initialize(params=None)`,
   `on_bar(bar, portfolio, history)`, `teardown()`, and signal dicts returned
   from `on_bar`.
2. Return a **list** of signal dicts, or `{"signals": [...], "drawings": [...]}`.
   Return `[]` for no action. Never return a bare signal dict, and never return
   `None`.
3. Signal inputs are `direction`, `size`, `order_type`, `price`, `sl`, `tp`,
   `reason`, `ticket`. `size` is the quantity field; `sl`/`tp` are the
   protective levels. An unknown key is silently ignored by the engine, so a
   typo silently drops your stop loss.
4. Close a position with its **exact ticket**:
   `{"direction": "close", "size": pos["size"], "ticket": pos["position_id"]}`.
   There is no FIFO and no implicit close.
5. Guard warm-up: `history` holds strictly prior bars and is empty on bar 0.
   `if len(history) < period: return []`.
6. Give every entry and exit a meaningful `reason` (≤1024 UTF-8 bytes). Reasons
   are persisted canonical events and are how a human understands your logic.
7. Use annotations where they add explanatory value — return a `drawings` list
   (`hline`, `marker`, `label`, `region`, …). They are descriptive
   only and never change results.
8. **Validate before running**, and repair from the structured errors:
   ```bash
   observa validate-strategy strategy.py --json
   observa validate-strategy strategy.py --smoke --json
   ```
   Exit 0 means valid. Exit 1 means the `errors[]` array tells you exactly what
   to fix. Exit 2 means a usage/setup problem.
9. **Persist every run** by passing `output=` to `observa.run(...)`; that is what
   writes `run.json`, `events.jsonl` and `metrics.json`. Output directories are
   create-only.
10. Inspect the result before reporting it: `result.summary()`,
    `observa.inspect_run(run_dir)`, or the read-only MCP server
    (`observa mcp --runs-dir <runs-root>`). Order rejections are
    `order_rejected` **events**, not exceptions — read them.
11. Report results as canonical numbers from Observa, and state which run
    directory produced them.

## 3. Never do this

* Never implement your own fill model, matching engine or backtest loop.
* Never apply spread, slippage or commission yourself.
* Never compute balance, equity, P&L, drawdown or any metric yourself.
* Never recreate order execution, queueing or SL/TP evaluation.
* Never read future bars or index beyond the current bar.
* Never assume FIFO or "close the oldest position".
* Never change Observa's engine, package or execution semantics.
* Never run `pip install observa` or `pip install "observa[mcp]"` — the public
  PyPI project named `observa` is unrelated and you will install the wrong
  package. Install the official release wheel, or that same wheel with `[mcp]`:
  ```bash
  python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-<version>-private-mvp/observa-<version>-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"
  ```
  (See `observa.agent_spec()["installation"]` for the exact current URL.)

## 4. Escalate instead of guessing

If the user's rule is ambiguous (entry timing, sizing, exit condition), state the
assumption you made explicitly in your report rather than silently inventing
behaviour.
