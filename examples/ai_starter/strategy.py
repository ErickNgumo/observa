"""AI starter strategy — a template the agent completes for the user.

The strategy must use the canonical Observa API (see llms-full.txt):
initialize(params) / on_bar(bar, portfolio, history) / teardown(),
signal dicts, and explicit-ticket closes. Do not implement execution.
"""
from datetime import datetime
from pathlib import Path

import observa


class UserStrategy(observa.Strategy):
    def initialize(self, params=None):
        # Replace with real parameter defaults / state.
        pass

    def on_bar(self, bar, portfolio, history):
        # Replace with the user's entry/exit logic.
        return []

    def teardown(self):
        pass


def main():
    data = observa.sample_data_path()  # bundled deterministic sample
    config = observa.Config(
        fill_mode=observa.BAR_CLOSE,
        spread=0.0002,
        slippage=0.0001,
        commission=0.0,
        interval="15m",
        strategy_name="UserStrategy",
        dataset_source=data,
    )
    run_dir = str(Path("runs") / ("starter_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    result = observa.run(UserStrategy(), data, config=config, output=run_dir)
    print("final balance:  %.2f" % result.final_balance)
    print("final equity:   %.2f" % result.final_equity)
    print("trades:         %d" % len(result.trades))
    print("events:         %d" % len(result.events))
    print("Run saved to:    %s" % run_dir)
    print("Replay with:     observa replay %s" % run_dir)
    print("Then open:       http://localhost:7878")


if __name__ == "__main__":
    main()
