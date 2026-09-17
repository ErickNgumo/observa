"""Create the OBS-AI-02 annotation demo run (deterministic, offline).

Produces a persisted run that visually contains:

* an EMA price-pane **line** series and a **VWAP** line series
* a **z-score** series and a **histogram** series in the single secondary pane
* a **rectangle** zone (created at bar 20, explicitly removed at bar 60)
* a horizontal level (`hline`)
* **markers** on several bars
* **labels** in all four positions at bar 30

Data is the bundled deterministic sample — no network, no external files.

Usage (from the repository root, with the Observa wheel installed):

    python python/tests/make_annotation_demo.py            # -> runs/annotation_demo
    observa replay runs/annotation_demo

or with a custom directory:

    python python/tests/make_annotation_demo.py /tmp/obs-annotations
    observa replay /tmp/obs-annotations
"""

import os
import sys

import observa


class AnnotationDemo:
    """Long-only EMA/mean-reversion demo that annotates everything it looks at."""

    def __init__(self):
        self.closes = []
        self.volumes = []
        self.zone_open = False
        self.bars = 0

    def initialize(self, params=None):
        self.closes = []
        self.volumes = []
        self.zone_open = False
        self.bars = 0

    def _mean(self, values, period):
        if len(values) < period:
            return None
        return sum(values[-period:]) / float(period)

    def on_bar(self, bar, portfolio, history):
        index = self.bars
        self.bars += 1
        self.closes.append(bar["close"])
        self.volumes.append(bar.get("volume") or 0.0)

        drawings = []
        signals = []

        # ── price-pane continuous series ──────────────────────────────
        ema = self._mean(self.closes, 10)
        drawings.append({
            "id": "ema_10", "type": "series", "value": ema,
            "series_type": "line", "line_style": "solid", "width": 2,
            "color": "#58a6ff", "pane": "price", "label": "EMA 10",
        })

        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        vwap = self._mean([c for c in self.closes], 20)
        drawings.append({
            "id": "vwap", "type": "series", "value": vwap,
            "series_type": "line", "line_style": "dashed", "width": 1,
            "color": "#d29922", "pane": "price", "label": "VWAP(20)",
        })

        # ── secondary-pane series: z-score line + histogram ───────────
        zscore = None
        if len(self.closes) >= 20:
            window = self.closes[-20:]
            mean = sum(window) / 20.0
            var = sum((c - mean) ** 2 for c in window) / 20.0
            if var > 0:
                zscore = max(-3.0, min(3.0, (bar["close"] - mean) / var ** 0.5))
        drawings.append({
            "id": "zscore", "type": "series", "value": zscore,
            "series_type": "line", "line_style": "solid", "width": 1,
            "color": "#8957e5", "pane": "separate", "label": "z-score(20)",
        })
        change = None
        if len(self.closes) >= 2:
            change = (self.closes[-1] - self.closes[-2]) * 10000.0
        drawings.append({
            "id": "delta", "type": "series", "value": change,
            "series_type": "histogram", "line_style": "solid", "width": 1,
            "color": "#3dd8d2", "pane": "separate", "label": "Δpips",
        })

        # ── a horizontal level (never re-emitted) ─────────────────────
        if index == 0:
            drawings.append({
                "id": "level_110", "type": "hline", "price": 1.10,
                "color": "#8b949e", "line_style": "dotted", "width": 1,
                "label": "1.1000",
            })

        # ── a zone with an explicit lifecycle ─────────────────────────
        if index == 20:
            drawings.append({
                "id": "zone_1", "type": "rectangle",
                "time_start": bar["timestamp"], "time_end": None,
                "price_top": bar["high"] + 0.0004, "price_bot": bar["low"] - 0.0004,
                "color": "#3fb950", "opacity": 0.14, "border": "#3fb950",
                "label": "gap zone",
            })
            self.zone_open = True
        if index == 60 and self.zone_open:
            drawings.append({"id": "zone_1", "action": "remove"})
            self.zone_open = False

        # ── markers (strategy events, not execution markers) ─────────
        if index % 30 == 0:
            drawings.append({
                "id": "sig_%d" % index, "type": "marker", "time": bar["timestamp"],
                "position": "below", "shape": "arrow_up", "color": "#3fb950",
                "text": "signal",
            })

        # ── labels in all four positions ──────────────────────────────
        if index == 30:
            for position, colour in (("above", "#3fb950"), ("below", "#f85149"),
                                     ("left", "#d29922"), ("right", "#8957e5")):
                drawings.append({
                    "id": "note_%s" % position, "type": "label",
                    "time": bar["timestamp"], "price": bar["close"],
                    "text": position.upper(), "color": colour, "position": position,
                })

        # A tiny bit of trading so the run is a real backtest too.
        if ema is not None and not portfolio["has_open_position"] and bar["close"] > ema:
            signals.append({"direction": "buy", "size": 1.0, "reason": "close > EMA 10"})

        return {"signals": signals, "drawings": drawings}

    def teardown(self):
        pass


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    out_dir = args[0] if args else os.path.join("runs", "annotation_demo")
    data = observa.sample_data_path()
    config = observa.Config(
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=7.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        strategy_name="AnnotationDemo",
        dataset_source=data,
    )
    result = observa.run(AnnotationDemo(), data, config=config, output=out_dir)
    summary = result.summary()
    annotated = sum(1 for e in result.events
                    if e.get("type") == "drawings_emitted")
    print("Run written to: %s" % summary["artifact_dir"])
    print("  bars: %s | trades: %s | events: %s | annotated bars: %d"
          % (summary["total_bars"], summary["trades"], summary["events"], annotated))
    print()
    print("Inspect it with:")
    print("  observa replay %s" % out_dir)
    print("  (the CLI prints the URL it bound; then click Play and use the Annotations button)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
