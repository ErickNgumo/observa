import { markerPixels } from "./replay.ts";

// Native chart primitive: arrows and connectors use the recorded fill price,
// and reproject automatically whenever the chart pans, zooms or resizes.
export class CompactMarkers {
  private chart: any;
  private series: any;
  private requestUpdate = () => {};
  private markers: any[] = [];
  private connections: any[] = [];
  private candles = new Map<number, any>();
  private scale = 1;
  private targets: any[] = [];
  attached({ chart, series, requestUpdate }: any) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }
  detached() {
    this.chart = null;
    this.series = null;
    this.targets = [];
    this.requestUpdate = () => {};
  }
  setData(markers: any[], candles: any[], connections: any[] = [], scale = 1) {
    this.markers = markers;
    this.connections = connections;
    this.scale = scale;
    this.candles = new Map(candles.map((c) => [c.time, c]));
    this.requestUpdate();
  }
  updateAllViews() {
    this.targets = [];
  }
  hitTest(x: number, y: number) {
    for (const t of [...this.targets].reverse()) {
      const dx = t.x2 - t.x1,
        dy = t.y2 - t.y1,
        length = dx * dx + dy * dy;
      const fraction = length
        ? Math.max(0, Math.min(1, ((x - t.x1) * dx + (y - t.y1) * dy) / length))
        : 0;
      if (
        Math.hypot(x - t.x1 - fraction * dx, y - t.y1 - fraction * dy) <=
        t.radius
      )
        return { externalId: `trade:${t.positionId}`, zOrder: "top" as const };
    }
    return null;
  }
  paneViews() {
    return [
      {
        zOrder: () => "top",
        renderer: () => ({
          draw: (target: any) => {
            if (!this.chart || !this.series) return;
            const timeScale = this.chart.timeScale(),
              range = timeScale.getVisibleLogicalRange();
            if (!range) return;
            const size = markerPixels(
              timeScale.width() / Math.max(1, range.to - range.from),
              this.scale,
            );
            this.targets = [];
            target.useMediaCoordinateSpace(
              ({ context: ctx, mediaSize }: any) => {
                for (const p of this.connections) {
                  const x1 = timeScale.timeToCoordinate(p.start),
                    x2 = timeScale.timeToCoordinate(p.end);
                  const y1 = this.series.priceToCoordinate(p.entry),
                    y2 = this.series.priceToCoordinate(p.exit);
                  if (
                    [x1, x2, y1, y2].some((v) => v == null) ||
                    Math.max(x1, x2) < 0 ||
                    Math.min(x1, x2) > mediaSize.width
                  )
                    continue;
                  ctx.save();
                  ctx.strokeStyle = p.color;
                  ctx.globalAlpha = p.selected ? 0.95 : 0.5;
                  ctx.lineWidth = p.selected ? 2 : 1;
                  ctx.setLineDash([4, 3]);
                  ctx.beginPath();
                  ctx.moveTo(x1, y1);
                  ctx.lineTo(x2, y2);
                  ctx.stroke();
                  ctx.restore();
                  this.targets.push({
                    x1,
                    x2,
                    y1,
                    y2,
                    radius: 5,
                    positionId: p.positionId,
                  });
                }
                const groups = new Map<string, any>();
                for (const m of this.markers) {
                  const key = `${m.time}:${m.position}:${m.shape}:${m.price ?? ""}`;
                  if (!groups.has(key) || m.selected) groups.set(key, m);
                }
                for (const m of groups.values()) {
                  const candle = this.candles.get(m.time),
                    x = timeScale.timeToCoordinate(m.time);
                  if (!candle || x == null || x < 0 || x > mediaSize.width)
                    continue;
                  const below = m.position === "belowBar";
                  const y = this.series.priceToCoordinate(
                    m.price ?? (below ? candle.low : candle.high),
                  );
                  if (y == null) continue;
                  const glyphSize = m.positionId ? size : size * 0.65;
                  ctx.save();
                  ctx.fillStyle = m.color;
                  ctx.strokeStyle = "#ffffff";
                  ctx.lineWidth = 1;
                  ctx.beginPath();
                  if (m.shape === "circle")
                    ctx.arc(
                      x,
                      y + (below ? 1 : -1) * glyphSize,
                      glyphSize / 3,
                      0,
                      Math.PI * 2,
                    );
                  else if (m.shape === "square")
                    ctx.rect(
                      x - glyphSize / 3,
                      y + (below ? 2 : -glyphSize),
                      glyphSize * 0.65,
                      glyphSize * 0.65,
                    );
                  else {
                    const d = m.shape === "arrowUp" ? 1 : -1,
                      half = glyphSize / 2,
                      stem = glyphSize * 0.18;
                    // The arrow tip is the execution price. The shaft extends away from it.
                    ctx.moveTo(x, y);
                    ctx.lineTo(x - half, y + d * glyphSize * 0.55);
                    ctx.lineTo(x - stem, y + d * glyphSize * 0.55);
                    ctx.lineTo(x - stem, y + d * glyphSize);
                    ctx.lineTo(x + stem, y + d * glyphSize);
                    ctx.lineTo(x + stem, y + d * glyphSize * 0.55);
                    ctx.lineTo(x + half, y + d * glyphSize * 0.55);
                    ctx.closePath();
                  }
                  ctx.fill();
                  ctx.stroke();
                  ctx.restore();
                  if (m.positionId)
                    this.targets.push({
                      x1: x,
                      x2: x,
                      y1: y,
                      y2: y + (below ? size : -size),
                      radius: size / 2,
                      positionId: m.positionId,
                    });
                }
              },
            );
          },
        }),
      },
    ];
  }
}
