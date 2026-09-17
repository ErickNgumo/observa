class RSIStrategy:
    """
    RSI Mean Reversion Strategy
    ===========================
    Buys when RSI drops below 30 (oversold).
    Closes when RSI rises above 70 (overbought).

    Demonstrates:
    - Incremental RSI calculation (no external libraries needed)
    - Ticket-based position closing
    - Strategy annotations (OBS-AI-02): a continuous RSI series, entry/exit
      labels, a level line and signal markers
    - Safe warmup period handling (gaps, never interpolation)

    Annotation contract: see ``docs/STRATEGY_API.md``. Annotations are
    descriptive only and never affect fills, P&L or execution.
    """

    def initialize(self, params=None):
        # RSI settings
        self.period     = params.get('period', 14) if params else 14
        self.oversold   = params.get('oversold', 30) if params else 30
        self.overbought = params.get('overbought', 70) if params else 70

        # RSI calculation state
        self.prev_close = None
        self.avg_gain   = None
        self.avg_loss   = None
        self.gains      = []
        self.losses     = []
        self.current_rsi = None

        # Drawing counter for unique IDs
        self.label_count = 0

        print(f"RSI({self.period}) Strategy initialized")
        print(f"  Oversold threshold:   {self.oversold}")
        print(f"  Overbought threshold: {self.overbought}")

    def _update_rsi(self, close):
        """
        Calculates RSI incrementally using Wilder's smoothing method.
        Returns None during the warmup period (first `period` bars).
        """
        if self.prev_close is None:
            self.prev_close = close
            return None

        change = close - self.prev_close
        self.prev_close = close

        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self.avg_gain is None:
            # Accumulate initial bars for seed calculation
            self.gains.append(gain)
            self.losses.append(loss)

            if len(self.gains) < self.period:
                return None

            # Seed the averages with simple mean
            self.avg_gain = sum(self.gains) / self.period
            self.avg_loss = sum(self.losses) / self.period
        else:
            # Wilder's smoothing: (prev * (n-1) + current) / n
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) \
                            / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) \
                            / self.period

        if self.avg_loss == 0.0:
            return 100.0

        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar, portfolio, history):
        rsi = self._update_rsi(bar['close'])
        self.current_rsi = rsi

        # Not enough history yet — wait silently
        if rsi is None:
            return []

        signals  = []
        drawings = []
        positions = portfolio['open_positions']

        # ── Entry — oversold ────────────────────────
        if rsi < self.oversold and not portfolio['has_open_position']:
            self.label_count += 1

            signals.append({
                'direction': 'buy',
                'size':      1.0,
                'sl':        bar['close'] - 0.0030,
                'tp':        bar['close'] + 0.0060,
                'reason':    f'RSI oversold: {rsi:.1f}',
            })

            # Callout with the RSI reading
            drawings.append({
                'id':       f'rsi_entry_{self.label_count}',
                'type':     'label',
                'time':     bar['timestamp'],
                'price':    bar['low'] - 0.0005,
                'text':     f'RSI {rsi:.0f}',
                'color':    '#3fb950',
                'position': 'below',
            })

            # A strategy marker for "entry condition fired"
            drawings.append({
                'id':       f'rsi_entry_marker_{self.label_count}',
                'type':     'marker',
                'time':     bar['timestamp'],
                'position': 'below',
                'shape':    'arrow_up',
                'color':    '#3fb950',
                'text':     'oversold',
            })

            # Entry level (hline is extended automatically; no time needed)
            drawings.append({
                'id':         f'entry_line_{self.label_count}',
                'type':       'hline',
                'price':      bar['close'],
                'color':      '#3fb950',
                'line_style': 'dashed',
                'width':      1,
                'label':      'entry',
            })

        # ── Exit — overbought ───────────────────────
        elif rsi > self.overbought and positions:
            self.label_count += 1

            signals.append({
                'direction': 'close',
                'ticket':    positions[0]['ticket'],
                'size':      1.0,
                'reason':    f'RSI overbought: {rsi:.1f}',
            })

            # Exit callout + marker
            drawings.append({
                'id':       f'rsi_exit_{self.label_count}',
                'type':     'label',
                'time':     bar['timestamp'],
                'price':    bar['high'] + 0.0005,
                'text':     f'RSI {rsi:.0f}',
                'color':    '#f85149',
                'position': 'above',
            })
            drawings.append({
                'id':       f'rsi_exit_marker_{self.label_count}',
                'type':     'marker',
                'time':     bar['timestamp'],
                'position': 'above',
                'shape':    'arrow_down',
                'color':    '#f85149',
                'text':     'overbought',
            })

        # Continuous RSI series on its own pane. `value: None` during warm-up
        # is a gap — never zero, never interpolated.
        drawings.insert(0, {
            'id':          'rsi',
            'type':        'series',
            'value':       rsi,
            'series_type': 'line',
            'pane':        'separate',
            'color':       '#8957e5',
            'label':       f'RSI {self.period}',
        })

        return {'signals': signals, 'drawings': drawings}

    def teardown(self):
        rsi_str = f'{self.current_rsi:.1f}' \
                  if self.current_rsi is not None else 'N/A'
        print(f"RSI Strategy complete")
        print(f"  Final RSI: {rsi_str}")