# Observa — Official AI Strategy-Implementation Prompt

Use Observa to implement and backtest the strategy below.

Read the official Observa agent documentation first:
`llms-full.txt` (repository root; complete agent & integration guide).

Install the official Observa wheel by URL if not already installed:
`python -m pip install "https://github.com/ErickNgumo/observa/releases/download/observa-0.1.0-private-mvp/observa-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl"`
(SHA-256: `8367263b786243e0fd89d289cb8a9df1cf1e0ec961316697c95d36f2605fc23c`). Never `pip install observa` — that is an unrelated
PyPI package.

Use the documented Observa API. Do not invent methods, classes, or execution
behavior.

Your responsibilities:

1. Translate the strategy into precise rules.
2. Identify rules that materially affect the backtest but are ambiguous.
3. State the assumptions you use.
4. Inspect and validate the data.
5. Implement the strategy with Observa.
6. Use the canonical Observa Engine for execution.
7. Do not implement fills, SL/TP, portfolio P&L, or order execution independently.
8. Close positions using explicit tickets.
9. Run the backtest if terminal execution is available.
10. Fix installation/API/runtime errors.
11. Persist the run.
12. Return key results.
13. Give me the Observa replay command.
14. Warn me about lookahead or execution assumptions.

Strategy:
[DESCRIBE STRATEGY]

Data:
[ATTACH FILE OR PROVIDE PATH]
