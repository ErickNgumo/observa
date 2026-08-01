class RSIStrategy:

    def initialize(self, params=None):
        self.period     = 14
        self.prev_close = None
        self.avg_gain   = None
        self.avg_loss   = None
        self.gains      = []
        self.losses     = []

    def _rsi(self, close):
        if self.prev_close is None:
            self.prev_close = close
            return None

        change = close - self.prev_close
        self.prev_close = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self.avg_gain is None:
            self.gains.append(gain)
            self.losses.append(loss)
            if len(self.gains) < self.period:
                return None
            self.avg_gain = sum(self.gains) / self.period
            self.avg_loss = sum(self.losses) / self.period
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) \
                            / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) \
                            / self.period

        if self.avg_loss == 0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar, portfolio, history):
        rsi = self._rsi(bar['close'])
        if rsi is None:
            return []

        positions = portfolio['open_positions']

        # Oversold — buy signal
        if rsi < 30 and not portfolio['has_open_position']:
            return [{
                'direction': 'buy',
                'size':      1.0,
                'sl':        bar['close'] - 0.0030,
                'tp':        bar['close'] + 0.0060,
                'reason':    f'RSI oversold: {rsi:.1f}',
            }]

        # Overbought — close signal
        if rsi > 70 and positions:
            return [{
                'direction': 'close',
                'ticket':    positions[0]['ticket'],
                'size':      1.0,
                'reason':    f'RSI overbought: {rsi:.1f}',
            }]

        return []

    def teardown(self):
        pass