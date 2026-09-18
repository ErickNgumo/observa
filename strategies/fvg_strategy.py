"""Fair Value Gap (FVG) example — canonical OBS-AI-02 annotation contract.

Shows how a strategy explains itself visually:

* a ``rectangle`` zone per detected gap (``time_end: None`` extends right as
  replay advances),
* an ``hline`` at the gap edge (a level the strategy cares about),
* a ``label`` callout,
* a strategy-driven ``marker`` for the entry condition,
* an explicit ``remove`` when the gap is filled — the strategy owns the
  lifecycle; Observa never guesses it.

Annotation contract (see ``docs/STRATEGY_API.md``): annotations are descriptive
only and never affect fills, P&L or execution. The deprecated ``persist`` /
``fill_price`` fields are intentionally NOT used — there is no hidden
price-crossing behaviour.
"""


class FVGStrategy:
    """Fair Value Gap detection; marks gaps and enters on formation."""

    def initialize(self, params=None):
        self.fvg_count = 0
        self.open_zones = {}  # id -> (price_top, price_bot)
        print("FVG Strategy initialized")

    def on_bar(self, bar, portfolio, history):
        if len(history) < 2:
            return {'signals': [], 'drawings': []}

        candle_1 = history[-2]  # two bars ago
        candle_2 = history[-1]  # previous bar
        candle_3 = bar          # current bar

        signals = []
        drawings = []

        # Strategy-owned lifecycle: a gap is invalidated once price trades
        # back through the zone. Emit `remove` instead of relying on the
        # Engine to interpret the concept.
        for zone_id, (top, bot) in list(self.open_zones.items()):
            if bar['low'] <= top and bar['high'] >= bot:
                drawings.append({'id': zone_id, 'action': 'remove'})
                del self.open_zones[zone_id]

        # Bullish FVG — gap between candle 1 high and candle 3 low.
        if candle_3['low'] > candle_1['high']:
            self.fvg_count += 1
            fvg_id = "bull_fvg_%d" % self.fvg_count
            top, bot = candle_3['low'], candle_1['high']
            self.open_zones[fvg_id] = (top, bot)
            drawings.append({
                'id':         fvg_id,
                'type':       'rectangle',
                'time_start': candle_1['timestamp'],
                'time_end':   None,          # extend right while it is live
                'price_top':  top,
                'price_bot':  bot,
                'color':      '#3fb950',
                'opacity':    0.14,
                'border':     '#3fb950',
                'label':      'FVG',
            })
            drawings.append({
                'id':        "bull_fvg_level_%d" % self.fvg_count,
                'type':      'hline',
                'price':     bot,
                'color':     '#3fb950',
                'line_style': 'dotted',
                'width':     1,
                'label':     'FVG edge',
            })
            drawings.append({
                'id':       "bull_fvg_note_%d" % self.fvg_count,
                'type':     'label',
                'time':     candle_2['timestamp'],
                'price':    (top + bot) / 2,
                'text':     'Bullish FVG',
                'color':    '#3fb950',
                'position': 'right',
            })

            if not portfolio['has_open_position']:
                drawings.append({
                    'id':       "bull_fvg_marker_%d" % self.fvg_count,
                    'type':     'marker',
                    'time':     bar['timestamp'],
                    'position': 'below',
                    'shape':    'arrow_up',
                    'color':    '#3fb950',
                    'text':     'FVG long',
                })
                signals.append({
                    'direction': 'buy',
                    'size':      1.0,
                    'sl':        candle_1['low'] - 0.0010,
                    'tp':        candle_3['high'] + 0.0030,
                    'reason':    'Bullish FVG entry',
                })

        # Bearish FVG — gap between candle 3 high and candle 1 low.
        if candle_3['high'] < candle_1['low']:
            self.fvg_count += 1
            fvg_id = "bear_fvg_%d" % self.fvg_count
            top, bot = candle_1['low'], candle_3['high']
            self.open_zones[fvg_id] = (top, bot)
            drawings.append({
                'id':         fvg_id,
                'type':       'rectangle',
                'time_start': candle_1['timestamp'],
                'time_end':   None,
                'price_top':  top,
                'price_bot':  bot,
                'color':      '#f85149',
                'opacity':    0.14,
                'border':     '#f85149',
                'label':      'FVG',
            })
            drawings.append({
                'id':       "bear_fvg_note_%d" % self.fvg_count,
                'type':     'label',
                'time':     candle_2['timestamp'],
                'price':    (top + bot) / 2,
                'text':     'Bearish FVG',
                'color':    '#f85149',
                'position': 'right',
            })

        return {'signals': signals, 'drawings': drawings}

    def teardown(self):
        print("FVG Strategy complete — %d FVGs detected" % self.fvg_count)
