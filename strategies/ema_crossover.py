class EMACrossover:
    """
    Simple EMA crossover strategy.
    Buys when fast EMA crosses above slow EMA.
    Closes when fast EMA crosses below slow EMA.
    """

    def initialize(self, params=None):
        self.fast_period = 5
        self.slow_period = 20
        self.fast_ema    = None
        self.slow_ema    = None
        self.prev_fast   = None
        self.prev_slow   = None
        print(f"EMA{self.fast_period}/{self.slow_period} strategy initialized")

    def _update_ema(self, current, price, period):
        if current is None:
            return price
        k = 2.0 / (period + 1.0)
        return price * k + current * (1.0 - k)

    def on_bar(self, bar, portfolio, history):
        # Update EMAs
        self.prev_fast = self.fast_ema
        self.prev_slow = self.slow_ema
        self.fast_ema  = self._update_ema(
            self.fast_ema, bar['close'], self.fast_period
        )
        self.slow_ema  = self._update_ema(
            self.slow_ema, bar['close'], self.slow_period
        )

        # Wait for warmup
        if self.prev_fast is None or self.prev_slow is None:
            return []

        crossed_up   = self.prev_fast <= self.prev_slow \
                       and self.fast_ema > self.slow_ema
        crossed_down = self.prev_fast >= self.prev_slow \
                       and self.fast_ema < self.slow_ema

        # Entry
        if crossed_up and not portfolio['has_open_position']:
            return [{
                'direction': 'buy',
                'size':      1.0,
                'price':     bar['close'],
                'sl':        bar['close'] - 0.0030,
                'tp':        bar['close'] + 0.0060,
                'reason':    f'EMA{self.fast_period} crossed above EMA{self.slow_period}',
            }]

        # Exit
        if crossed_down and portfolio['has_open_position']:
            return [{
                'direction': 'close',
                'size':      1.0,
                'reason':    f'EMA{self.fast_period} crossed below EMA{self.slow_period}',
            }]

        return []

    def teardown(self):
        print("Strategy complete")