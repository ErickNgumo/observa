# AI Starter — an Observa strategy project

A minimal, working starter for implementing a **user strategy** with an AI
coding agent. Four files, no configuration.

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Instructions the coding agent should read first (vendor-neutral). |
| `strategy.py` | The strategy skeleton — a mirror of Observa's gold example. |
| `run.py` | Builds the `Config`, runs the backtest, persists the run. |
| `README.md` | This file. |

## Install Observa first

```bash
# official private-MVP wheel (see observa.agent_spec()["installation"])
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.5-private-mvp/observa-0.1.5-cp310-abi3-manylinux_2_34_x86_64.whl"
```

> ⚠️ Do **not** run `pip install observa` or `pip install "observa[mcp]"`. The
> public PyPI project named `observa` is unrelated to this one.

That one install also provides MCP, so there is nothing else to add — start it
with `observa mcp --runs-dir runs/`. (The old `[mcp]` extra is still accepted as
an empty compatibility alias, but it is never needed.)

## Use it

```bash
observa validate-strategy strategy.py --smoke --json   # validate before running
python run.py                                          # bundled sample data
python run.py path/to/your.csv                         # your own data
observa replay runs/starter_<timestamp>                # inspect the run
```

Agents can discover the whole contract without this repository:

```python
import observa
observa.agent_spec()          # canonical machine-readable contract
observa.agent_guide_path()    # short authoring guide
observa.agent_example_path()  # gold example
```
