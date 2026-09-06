"""AI starter strategy — a template the agent completes for the user.

The strategy must use the canonical Observa API (see llms-full.txt):
initialize(params) / on_bar(bar, portfolio, history) / teardown(),
signal dicts, and explicit-ticket closes. Do not implement execution.
"""
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
    result = observa.run(UserStrategy(), data, config=config, output="runs/starter")
    print("final balance:  %.2f" % result.final_balance)
    print("final equity:   %.2f" % result.final_equity)
    print("trades:         %d" % len(result.trades))
    print("events:         %d" % len(result.events))
    print("replay:         observa replay %s" % "runs/starter")


if __name__ == "__main__":
    main()
