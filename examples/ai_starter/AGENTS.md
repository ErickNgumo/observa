# AI Agent Instructions — Observa Strategy Project

You are implementing a USER trading strategy on top of Observa.

1. This project uses Observa (canonical backtesting engine).
2. Read the official Observa agent guide: `llms-full.txt` at the Observa
   repository root (or the bundled copy your host provides).
3. Inspect `strategy.py` and the data before changing anything.
4. Do NOT modify the Observa engine or its Python package.
5. Translate the user's strategy precisely; do not invent rules.
6. State assumptions for ambiguous rules.
7. Run the backtest with the canonical Observa API.
8. Fix installation/API/runtime errors.
9. Report results (balance/equity/trades/events).
10. Provide the replay command (`observa replay <run-dir>`; it binds a free
    port and prints the URL). In notebooks use
    `observa.replay(run_dir, block=False)` and call `server.stop()`.
11. Read results via `result.summary()` / `observa.run_summary(dir)`; branch on
    `exc.code`, never on exception messages. Order rejections are events.
12. Never compute fills, P&L, or SL/TP yourself.
