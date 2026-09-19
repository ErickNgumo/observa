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
python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.3-private-mvp/observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl"
```

> ⚠️ Do **not** run `pip install observa` or `pip install "observa[mcp]"`. The
> public PyPI project named `observa` is unrelated to this one.

MCP inspection is an optional extra on the same wheel:

```bash
python -m pip install "./observa-0.1.3-cp310-abi3-manylinux_2_34_x86_64.whl[mcp]"
```

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
