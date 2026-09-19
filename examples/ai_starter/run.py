"""Run the starter strategy with the canonical Observa engine.

    python run.py            # bundled deterministic sample data
    python run.py my.csv     # your own CSV (timestamp,open,high,low,close,volume)

Every run is persisted to `runs/` so it can be inspected afterwards with
`observa replay <run-dir>`, `observa.inspect_run(<run-dir>)`, or the read-only
MCP server (`observa mcp --runs-dir runs`).
"""

from __future__ import annotations

import datetime
import os
import sys

import observa

from strategy import UserStrategy


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    data = args[0] if args else observa.sample_data_path()

    config = observa.Config(
        dataset_source=data,
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={"period": 5},
        strategy_name="UserStrategy",
    )
    run_dir = os.path.join(
        "runs", "starter_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    result = observa.run(UserStrategy(), data, config=config, output=run_dir)
    summary = result.summary()
    print("status:        %s" % summary["status"])
    print("bars:          %s" % summary["total_bars"])
    print("trades:        %s" % summary["trades"])
    print("open:          %s" % summary["open_positions"])
    print("final_balance: %.2f" % summary["final_balance"])
    print("final_equity:  %.2f" % summary["final_equity"])
    print("run saved to:  %s" % run_dir)
    print("inspect with:  observa replay %s" % run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
