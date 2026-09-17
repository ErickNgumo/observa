// ══════════════════════════════════════════════
// STRATEGY ANNOTATION RENDERER (OBS-AI-02)
// Renders the annotation state produced by `ObservaDrawings`:
//   * continuous series  -> native Lightweight Charts series (price or the one
//                           generic secondary pane)
//   * zones/lines/labels -> chart primitives (fills below candles, strokes and
//                           text above them)
//   * markers            -> merged into the canonical marker layer by events.js
//
// Annotations are presentation only. Nothing here computes or alters
// economics, and canonical execution markers are never touched.
// ══════════════════════════════════════════════

var drawingSeriesById = {};      // id -> { series, pane, options }
var drawingPrimitivesById = {};  // id -> { primitive, spec }
var drawingPaneIndex = null;     // lazily created secondary pane (1)

// ── Series ──────────────────────────────────────

function drawingLineStyle(LC, style) {
  if (style === 'dashed') return LC.LineStyle.Dashed;
  if (style === 'dotted') return LC.LineStyle.Dotted;
  return LC.LineStyle.Solid;
}

function drawingEnsurePane(LC) {
  if (drawingPaneIndex !== null) return drawingPaneIndex;
  // Lightweight Charts creates panes on demand: index 1 is the first
  // secondary pane. Only ONE generic strategy pane is supported by contract.
  drawingPaneIndex = 1;
  return drawingPaneIndex;
}

function drawingSeriesOptions(LC, options) {
  var opts = {
    lineWidth: options.width || 1,
    lineStyle: drawingLineStyle(LC, options.line_style),
    priceLineVisible: false,
    lastValueVisible: false
  };
  if (options.series_type === 'histogram') {
    opts.color = options.color;
    opts.base = 0;
  } else {
    opts.color = options.color;
    opts.title = options.label || '';
  }
  return opts;
}

function drawingCreateSeries(LC, id, options) {
  var pane = options.pane === 'separate' ? drawingEnsurePane(LC) : 0;
  var ctor = options.series_type === 'histogram' ? LC.HistogramSeries : LC.LineSeries;
  var series = chart.addSeries(ctor, drawingSeriesOptions(LC, options), pane);
  drawingSeriesById[id] = { series: series, pane: pane, options: options };
  return drawingSeriesById[id];
}

function applyDrawingSeries(state, incremental) {
  var LC = window.LightweightCharts;
  if (!LC || !candleSeries) return;

  // Remove series that no longer exist in the folded state.
  for (var known in drawingSeriesById) {
    if (!Object.prototype.hasOwnProperty.call(drawingSeriesById, known)) continue;
    if (!state.series[known]) {
      chart.removeSeries(drawingSeriesById[known].series);
      delete drawingSeriesById[known];
    }
  }

  for (var id in state.series) {
    if (!Object.prototype.hasOwnProperty.call(state.series, id)) continue;
    var entry = state.series[id];
    var existing = drawingSeriesById[id];
    var wantedPane = entry.options.pane === 'separate' ? 1 : 0;
    if (existing && (existing.pane !== wantedPane ||
        existing.options.series_type !== entry.options.series_type)) {
      chart.removeSeries(existing.series);
      delete drawingSeriesById[id];
      existing = null;
    }
    if (!existing) {
      existing = drawingCreateSeries(LC, id, entry.options);
      existing.series.setData(entry.points);
      continue;
    }
    // Styling may change between bars (strategy re-emits colour/width).
    existing.options = entry.options;
    existing.series.applyOptions(drawingSeriesOptions(LC, entry.options));
    if (incremental && entry.points.length) {
      existing.series.update(entry.points[entry.points.length - 1]);
    } else {
      existing.series.setData(entry.points);
    }
  }
}

// ── Primitives (zones, lines, text) ─────────────

function StrategyDrawingPrimitive(spec) {
  this.spec = spec;
}

StrategyDrawingPrimitive.prototype.paneViews = function () {
  var primitive = this;
  return [
    {
      zOrder: function () { return 'bottom'; },
      renderer: function () {
        return { drawBackground: function (target) { primitive.draw(target, true); } };
      }
    },
    {
      zOrder: function () { return 'top'; },
      renderer: function () {
        return { draw: function (target) { primitive.draw(target, false); } };
      }
    }
  ];
};

StrategyDrawingPrimitive.prototype.times = function () {
  var spec = this.spec;
  var start = spec.time_start || spec.time || spec.x1;
  var end = spec.time_end || spec.x2;
  var first = start ? toUnix(start) : null;
  var last = end ? toUnix(end) : (candleData.length ? candleData[candleData.length - 1].time : first);
  return { start: first, end: last };
};

StrategyDrawingPrimitive.prototype.coordinates = function () {
  var times = this.times();
  if (times.start === null || times.end === null) return null;
  var x1 = chart.timeScale().timeToCoordinate(times.start);
  var x2 = chart.timeScale().timeToCoordinate(times.end);
  if (x1 === null || x2 === null) return null;
  return { x1: x1, x2: x2, times: times };
};

StrategyDrawingPrimitive.prototype.draw = function (target, background) {
  var spec = this.spec;
  var isFill = spec.type === 'rectangle' || spec.type === 'region';
  if (background && !isFill) return;
  if (!background && isFill && !spec.border) {
    // a zone without a border still draws its fill above (nothing to stroke)
  }

  target.useMediaCoordinateSpace(function (scope) {
    var ctx = scope.context;
    ctx.save();
    try {
      if (spec.type === 'rectangle') drawNativeRectangle(ctx, spec, this.coordinates(), background);
      if (spec.type === 'region') drawNativeRegion(ctx, spec, this.coordinates(), scope.mediaSize.height, background);
      if (!background && spec.type === 'hline') drawNativeHorizontalLine(ctx, spec, scope.mediaSize.width);
      if (!background && spec.type === 'line') drawNativeTrendLine(ctx, spec, this.coordinates());
      if (!background && spec.type === 'label') drawNativeLabel(ctx, spec, this.coordinates());
    } finally {
      ctx.restore();
    }
  }.bind(this));
};

/** `#RRGGBB` / `#RRGGBBAA` / `rgba(...)` -> an `rgba()` fill string. */
function drawingFillColor(color, opacity, fallback) {
  if (!color) return fallback;
  var alpha = typeof opacity === 'number' ? opacity : null;
  var hex = String(color).replace('#', '');
  if (hex.length === 8 && /^[0-9a-fA-F]{8}$/.test(hex)) {
    alpha = parseInt(hex.slice(6, 8), 16) / 255;
    hex = hex.slice(0, 6);
  }
  if (hex.length === 6 && /^[0-9a-fA-F]{6}$/.test(hex)) {
    var r = parseInt(hex.slice(0, 2), 16);
    var g = parseInt(hex.slice(2, 4), 16);
    var b = parseInt(hex.slice(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha === null ? 0.14 : alpha) + ')';
  }
  return color;
}

function drawingStrokeColor(color, fallback) {
  if (!color) return fallback;
  var hex = String(color).replace('#', '');
  if (hex.length === 8) hex = hex.slice(0, 6);
  if (hex.length === 6 && /^[0-9a-fA-F]{6}$/.test(hex)) return '#' + hex;
  return color;
}

function drawingStroke(ctx, spec) {
  ctx.strokeStyle = drawingStrokeColor(spec.border || spec.color, '#58a6ff');
  ctx.lineWidth = spec.width || 1;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  if (spec.line_style === 'dashed') ctx.setLineDash([5, 4]);
  if (spec.line_style === 'dotted') ctx.setLineDash([1, 3]);
}

/** Crisp border: align the stroke to the pixel grid and inset by half a line. */
function crispRect(ctx, x, y, width, height, lineWidth) {
  var inset = (lineWidth % 2 === 1) ? 0.5 : 1.0;
  var left = Math.round(x) + inset;
  var top = Math.round(y) + inset;
  var w = Math.max(1, Math.round(width) - inset * 2);
  var h = Math.max(1, Math.round(height) - inset * 2);
  ctx.strokeRect(left, top, w, h);
}

function drawNativeRectangle(ctx, spec, coords, fillOnly) {
  if (!coords) return;
  var yTop = candleSeries.priceToCoordinate(spec.price_top);
  var yBottom = candleSeries.priceToCoordinate(spec.price_bot);
  if (yTop === null || yBottom === null) return;
  var x = Math.min(coords.x1, coords.x2);
  var y = Math.min(yTop, yBottom);
  var width = Math.max(1, Math.abs(coords.x2 - coords.x1));
  var height = Math.max(1, Math.abs(yBottom - yTop));
  if (fillOnly) {
    ctx.fillStyle = drawingFillColor(spec.color, spec.opacity, 'rgba(63, 185, 80, 0.14)');
    ctx.fillRect(x, y, width, height);
  } else if (spec.border) {
    drawingStroke(ctx, spec);
    crispRect(ctx, x, y, width, height, ctx.lineWidth);
  }
}

function drawNativeRegion(ctx, spec, coords, paneHeight, fillOnly) {
  if (!coords) return;
  var x = Math.min(coords.x1, coords.x2);
  var width = Math.max(1, Math.abs(coords.x2 - coords.x1));
  if (fillOnly) {
    ctx.fillStyle = drawingFillColor(spec.color, spec.opacity, 'rgba(88, 166, 255, 0.10)');
    ctx.fillRect(x, 0, width, paneHeight);
  } else {
    drawingStroke(ctx, spec);
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, paneHeight);
    ctx.moveTo(x + width - 0.5, 0);
    ctx.lineTo(x + width - 0.5, paneHeight);
    ctx.stroke();
  }
}

/** Horizontal levels naturally span the whole pane (no `time` required). */
function drawNativeHorizontalLine(ctx, spec, paneWidth) {
  var y = candleSeries.priceToCoordinate(spec.price);
  if (y === null) return;
  drawingStroke(ctx, spec);
  var yy = ctx.lineWidth % 2 === 1 ? Math.round(y) + 0.5 : Math.round(y);
  ctx.beginPath();
  ctx.moveTo(0, yy);
  ctx.lineTo(paneWidth, yy);
  ctx.stroke();
}

function drawNativeTrendLine(ctx, spec, coords) {
  if (!coords) return;
  var y1 = candleSeries.priceToCoordinate(spec.y1);
  var y2 = candleSeries.priceToCoordinate(spec.y2);
  if (y1 === null || y2 === null) return;
  drawingStroke(ctx, spec);
  ctx.beginPath();
  ctx.moveTo(coords.x1, y1);
  ctx.lineTo(coords.x2, y2);
  ctx.stroke();
}

function drawNativeLabel(ctx, spec, coords) {
  if (!coords) return;
  var y = candleSeries.priceToCoordinate(spec.price);
  if (y === null) return;
  var text = spec.text || '';
  ctx.font = '600 10px Manrope, Segoe UI, sans-serif';
  var paddingX = 5;
  var height = 18;
  var width = Math.ceil(ctx.measureText(text).width) + paddingX * 2;
  var anchorX = coords.x1;
  var gap = 8;

  // All four positions are honoured (left/right are not silently mapped).
  var position = spec.position || 'above';
  var left, top;
  if (position === 'left') {
    left = anchorX - width - gap;
    top = y - height / 2;
  } else if (position === 'right') {
    left = anchorX + gap;
    top = y - height / 2;
  } else {
    left = anchorX - width / 2;
    top = position === 'below' ? y + gap : y - height - gap;
  }

  var stroke = drawingStrokeColor(spec.color, '#58a6ff');
  ctx.fillStyle = drawingBackgroundColor(stroke);
  roundNativeRect(ctx, left, top, width, height, 4);
  ctx.fill();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = stroke;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, left + width / 2, top + height / 2 + 0.5);
}

function drawingBackgroundColor(color) {
  var hex = String(color).replace('#', '').slice(0, 6);
  if (hex.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(hex)) return 'rgba(13, 17, 23, 0.92)';
  return 'rgba(' + parseInt(hex.slice(0, 2), 16) + ',' +
    parseInt(hex.slice(2, 4), 16) + ',' +
    parseInt(hex.slice(4, 6), 16) + ',0.18)';
}

function roundNativeRect(ctx, x, y, width, height, radius) {
  var r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function drawingSupportsPrimitive(type) {
  return type === 'rectangle' || type === 'region' || type === 'hline' ||
    type === 'line' || type === 'label';
}

function applyDrawingPrimitives(state) {
  if (!candleSeries) return;

  for (var known in drawingPrimitivesById) {
    if (!Object.prototype.hasOwnProperty.call(drawingPrimitivesById, known)) continue;
    if (!state.primitives[known]) {
      removeStrategyDrawing(drawingPrimitivesById[known].primitive);
      delete drawingPrimitivesById[known];
    }
  }

  for (var id in state.primitives) {
    if (!Object.prototype.hasOwnProperty.call(state.primitives, id)) continue;
    var spec = state.primitives[id].spec;
    if (!drawingSupportsPrimitive(spec.type)) continue;
    var existing = drawingPrimitivesById[id];
    if (existing && JSON.stringify(existing.spec) === JSON.stringify(spec)) continue;
    if (existing) removeStrategyDrawing(existing.primitive);
    var primitive = new StrategyDrawingPrimitive(spec);
    candleSeries.attachPrimitive(primitive);
    drawingPrimitivesById[id] = { primitive: primitive, spec: spec };
  }
}

// ── Entry points ────────────────────────────────

/** Applies a folded drawing state to the chart. */
function applyDrawingState(state, options) {
  var opts = options || {};
  if (!showAnnotations || !state) {
    clearDrawingLayer();
    return;
  }
  applyDrawingSeries(state, !!opts.incremental);
  applyDrawingPrimitives(state);
}

/** Detaches/removes every rendered annotation (toggle off, reset). */
function clearDrawingLayer() {
  if (candleSeries) {
    for (var pid in drawingPrimitivesById) {
      if (Object.prototype.hasOwnProperty.call(drawingPrimitivesById, pid)) {
        removeStrategyDrawing(drawingPrimitivesById[pid].primitive);
      }
    }
  }
  for (var sid in drawingSeriesById) {
    if (Object.prototype.hasOwnProperty.call(drawingSeriesById, sid)) {
      chart.removeSeries(drawingSeriesById[sid].series);
    }
  }
  drawingPrimitivesById = {};
  drawingSeriesById = {};
}

/** Strategy markers in the shape the canonical marker plugin expects.
 *  `visible` defaults to the UI toggle (`showAnnotations`). */
function drawingMarkersFor(state, visible) {
  var show = visible === undefined ? showAnnotations : visible;
  if (!show || !state || !state.markers) return [];
  var shapeMap = { circle: 'circle', square: 'square', arrow_up: 'arrowUp', arrow_down: 'arrowDown' };
  return state.markers.map(function (m) {
    return {
      time: m.time,
      position: m.position === 'above' ? 'aboveBar' : 'belowBar',
      shape: shapeMap[m.shape] || 'circle',
      color: m.color,
      text: m.text || '',
      size: 0.6
    };
  });
}

function createStrategyDrawing(spec) {
  if (!candleSeries || typeof candleSeries.attachPrimitive !== 'function') return null;
  if (!drawingSupportsPrimitive(spec.type)) return null;
  var primitive = new StrategyDrawingPrimitive(spec);
  candleSeries.attachPrimitive(primitive);
  return primitive;
}

function removeStrategyDrawing(primitive) {
  if (candleSeries && primitive && typeof candleSeries.detachPrimitive === 'function') {
    candleSeries.detachPrimitive(primitive);
  }
}

// Node-testable pure helpers (no DOM is touched by these functions).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    drawingMarkersFor: drawingMarkersFor,
    drawingFillColor: drawingFillColor,
    drawingStrokeColor: drawingStrokeColor,
    drawingSupportsPrimitive: drawingSupportsPrimitive
  };
}
