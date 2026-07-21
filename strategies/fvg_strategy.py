class FVGStrategy:
    """
    Fair Value Gap (FVG) detection strategy.
    Marks bullish and bearish FVGs on the chart.
    Enters on FVG formation, exits on fill.
    """

    def initialize(self, params=None):
        self.fvg_count = 0
        print("FVG Strategy initialized")

    def on_bar(self, bar, portfolio, history):
        if len(history) < 2:
            return {'signals': [], 'drawings': []}

        candle_1 = history[-2]  # two bars ago
        candle_2 = history[-1]  # previous bar
        candle_3 = bar          # current bar

        signals  = []
        drawings = []

        # Bullish FVG — gap between candle1 low and candle3 high
        # candle3 low > candle1 high means there's a gap
        bullish_fvg = candle_3['low'] > candle_1['high']

        # Bearish FVG — gap between candle1 high and candle3 low
        bearish_fvg = candle_3['high'] < candle_1['low']

        if bullish_fvg:
            self.fvg_count += 1
            fvg_id = f"bull_fvg_{self.fvg_count}"
            drawings.append({
                'id':         fvg_id,
                'type':       'rectangle',
                'time_start': candle_1['timestamp'],
                'time_end':   None,
                'price_top':  candle_3['low'],
                'price_bot':  candle_1['high'],
                'color':      '#3fb95033',
                'border':     '#3fb950',
                'persist':    'until_filled',
                'fill_price': candle_1['high'],
            })
            # Label it
            drawings.append({
                'id':       f"bull_fvg_label_{self.fvg_count}",
                'type':     'label',
                'time':     candle_2['timestamp'],
                'price':    (candle_3['low'] + candle_1['high']) / 2,
                'text':     'FVG',
                'color':    '#3fb950',
                'position': 'right',
            })

            if not portfolio['has_open_position']:
                signals.append({
                    'direction': 'buy',
                    'size':      1.0,
                    'sl':        candle_1['low'] - 0.0010,
                    'tp':        candle_3['high'] + 0.0030,
                    'reason':    'Bullish FVG entry',
                })

        if bearish_fvg:
            self.fvg_count += 1
            fvg_id = f"bear_fvg_{self.fvg_count}"
            drawings.append({
                'id':         fvg_id,
                'type':       'rectangle',
                'time_start': candle_1['timestamp'],
                'time_end':   None,
                'price_top':  candle_1['low'],
                'price_bot':  candle_3['high'],
                'color':      '#f8514933',
                'border':     '#f85149',
                'persist':    'until_filled',
                'fill_price': candle_1['low'],
            })
            drawings.append({
                'id':       f"bear_fvg_label_{self.fvg_count}",
                'type':     'label',
                'time':     candle_2['timestamp'],
                'price':    (candle_1['low'] + candle_3['high']) / 2,
                'text':     'FVG',
                'color':    '#f85149',
                'position': 'right',
            })

        return {'signals': signals, 'drawings': drawings}

    def teardown(self):
        print(f"FVG Strategy complete — {self.fvg_count} FVGs detected")