"""
EMA Crossover — Reference strategy for Observa.

Buys when the 20 EMA crosses above the 50 EMA.
Sells when the 20 EMA crosses below the 50 EMA.

This is what a trader writes when using Observa.
"""
from observa import Strategy, OrderIntent, Direction, EMA


class EMACrossover(Strategy):

    def initialize(self, params):
        self.ema20 = self.indicator(EMA(period=params.get("ema_fast", 20)))
        self.ema50 = self.indicator(EMA(period=params.get("ema_slow", 50)))
        self.in_trade = False

    def on_bar(self, bar):
        if not self.ema20.ready or not self.ema50.ready:
            return

        crossed_up = (
            self.ema20.previous <= self.ema50.previous and
            self.ema20.value    >  self.ema50.value
        )
        crossed_down = (
            self.ema20.previous >= self.ema50.previous and
            self.ema20.value    <  self.ema50.value
        )

        if crossed_up and not self.in_trade:
            self.submit(OrderIntent(
                direction = Direction.BUY,
                size      = 1.0,
                sl        = bar.close - 0.0020,
                tp        = bar.close + 0.0040,
                reason    = "EMA20 crossed above EMA50",
            ))
        elif crossed_down and self.in_trade:
            self.close(reason="EMA20 crossed below EMA50")

    def on_fill(self, fill):
        self.in_trade = True
        self.annotate(fill.event_id, "Entered on EMA crossover")

    def on_close(self, fill):
        self.in_trade = False
        self.annotate(fill.event_id, f"Closed — {fill.exit_reason} | PnL: {fill.pnl}")

    def teardown(self):
        self.log("Strategy complete.")
