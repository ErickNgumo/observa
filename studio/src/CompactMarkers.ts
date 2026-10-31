import { markerPixels } from "./replay.ts";

// A presentation primitive avoids the built-in markers' 12px minimum and text
// stacking. Its coordinates are recalculated by the chart on every zoom/resize.
export class CompactMarkers {
  private chart: any;
  private series: any;
  private requestUpdate = () => {};
  private markers: any[] = [];
  private candles = new Map<number, any>();
  attached({ chart, series, requestUpdate }: any) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }
  detached() {
    this.chart = null;
    this.series = null;
    this.requestUpdate = () => {};
  }
  setData(markers: any[], candles: any[]) {
    this.markers = markers;
    this.candles = new Map(candles.map((c) => [c.time, c]));
    this.requestUpdate();
  }
  updateAllViews() {}
  paneViews() {
    return [
      {
        zOrder: () => "top",
        renderer: () => ({
          draw: (target: any) => {
            if (!this.chart || !this.series) return;
            const scale = this.chart.timeScale(),
              range = scale.getVisibleLogicalRange();
            if (!range) return;
            const size = markerPixels(
              scale.width() / Math.max(1, range.to - range.from),
            );
            // Multiple fills on the same bar remain individually inspectable in the
            // tooltip, while sharing a glyph instead of covering each other.
            const groups = new Map<string, any>();
            for (const marker of this.markers) {
              const key = `${marker.time}:${marker.position}:${marker.shape}`;
              const previous = groups.get(key);
              if (!previous || marker.selected) groups.set(key, marker);
            }
            target.useMediaCoordinateSpace(
              ({ context: ctx, mediaSize }: any) => {
                const lanes = new Map<string, number>();
                for (const m of groups.values()) {
                  const candle = this.candles.get(m.time),
                    x = scale.timeToCoordinate(m.time);
                  if (!candle || x == null || x < 0 || x > mediaSize.width)
                    continue;
                  const below = m.position === "belowBar",
                    key = `${m.time}:${m.position}`;
                  const lane = lanes.get(key) || 0;
                  lanes.set(key, lane + 1);
                  const priceY = this.series.priceToCoordinate(
                    below ? candle.low : candle.high,
                  );
                  if (priceY == null) continue;
                  const y =
                    priceY +
                    (below ? 1 : -1) * (4 + size / 2 + lane * (size + 2));
                  ctx.save();
                  ctx.fillStyle = m.color;
                  ctx.strokeStyle = "#ffffff";
                  ctx.lineWidth = 1;
                  ctx.beginPath();
                  if (m.shape === "circle")
                    ctx.arc(x, y, size / 2, 0, Math.PI * 2);
                  else if (m.shape === "square")
                    ctx.rect(x - size / 2, y - size / 2, size, size);
                  else {
                    const direction = m.shape === "arrowUp" ? -1 : 1;
                    ctx.moveTo(x, y + (direction * size) / 2);
                    ctx.lineTo(x - size / 2, y - (direction * size) / 2);
                    ctx.lineTo(x + size / 2, y - (direction * size) / 2);
                    ctx.closePath();
                  }
                  ctx.fill();
                  if (size >= 5) ctx.stroke();
                  ctx.restore();
                }
              },
            );
          },
        }),
      },
    ];
  }
}
