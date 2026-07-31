// ══════════════════════════════════════════════
// NATIVE STRATEGY DRAWING RENDERER
// Lightweight Charts primitives render directly on the chart canvas. Fills
// live below candles while borders, lines and labels live above them.
// ══════════════════════════════════════════════

function StrategyDrawingPrimitive(spec) {
  this.spec = spec;
}

StrategyDrawingPrimitive.prototype.paneViews = function() {
  var primitive = this;
  return [
    {
      zOrder: function() { return 'bottom'; },
      renderer: function() {
        return { drawBackground: function(target) { primitive.draw(target, true); } };
      }
    },
    {
      zOrder: function() { return 'top'; },
      renderer: function() {
        return { draw: function(target) { primitive.draw(target, false); } };
      }
    }
  ];
};

StrategyDrawingPrimitive.prototype.times = function() {
  var start = this.spec.time_start || this.spec.time || this.spec.x1;
  var end = this.spec.time_end || this.spec.x2;
  var first = start ? toUnix(start) : null;
  var last = end ? toUnix(end) : (candleData.length ? candleData[candleData.length - 1].time : first);
  return { start: first, end: last };
};

StrategyDrawingPrimitive.prototype.coordinates = function() {
  var times = this.times();
  if (times.start === null || times.end === null) return null;
  var x1 = chart.timeScale().timeToCoordinate(times.start);
  var x2 = chart.timeScale().timeToCoordinate(times.end);
  if (x1 === null || x2 === null) return null;
  return { x1: x1, x2: x2, times: times };
};

StrategyDrawingPrimitive.prototype.draw = function(target, background) {
  var spec = this.spec;
  var coords = this.coordinates();
  if (!coords) return;
  var isFill = spec.type === 'rectangle' || spec.type === 'region';
  if (background && !isFill) return;

  target.useMediaCoordinateSpace(function(scope) {
    var ctx = scope.context;
    ctx.save();
    try {
      if (spec.type === 'rectangle') drawNativeRectangle(ctx, spec, coords, background);
      if (spec.type === 'region') drawNativeRegion(ctx, spec, coords, scope.mediaSize.height, background);
      if (!background && spec.type === 'hline') drawNativeHorizontalLine(ctx, spec, coords);
      if (!background && spec.type === 'line') drawNativeTrendLine(ctx, spec, coords);
      if (!background && spec.type === 'label') drawNativeLabel(ctx, spec, coords);
    } finally {
      ctx.restore();
    }
  });
};

function drawingStroke(ctx, spec) {
  ctx.strokeStyle = spec.border || spec.color || '#58a6ff';
  ctx.lineWidth = spec.width || 1;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  if (spec.style === 'dashed') ctx.setLineDash([5, 4]);
  if (spec.style === 'dotted') ctx.setLineDash([1, 3]);
}

function drawNativeRectangle(ctx, spec, coords, fillOnly) {
  var yTop = candleSeries.priceToCoordinate(spec.price_top);
  var yBottom = candleSeries.priceToCoordinate(spec.price_bot);
  if (yTop === null || yBottom === null) return;
  var x = Math.min(coords.x1, coords.x2);
  var y = Math.min(yTop, yBottom);
  var width = Math.max(1, Math.abs(coords.x2 - coords.x1));
  var height = Math.max(1, Math.abs(yBottom - yTop));
  if (fillOnly) {
    ctx.fillStyle = nativeTransparentColor(spec.color, 'rgba(63, 185, 80, 0.13)');
    ctx.fillRect(x, y, width, height);
  } else {
    drawingStroke(ctx, spec);
    ctx.strokeRect(x + .5, y + .5, Math.max(0, width - 1), Math.max(0, height - 1));
  }
}

function drawNativeRegion(ctx, spec, coords, paneHeight, fillOnly) {
  var x = Math.min(coords.x1, coords.x2);
  var width = Math.max(1, Math.abs(coords.x2 - coords.x1));
  if (fillOnly) {
    ctx.fillStyle = nativeTransparentColor(spec.color, 'rgba(88, 166, 255, 0.08)');
    ctx.fillRect(x, 0, width, paneHeight);
  } else {
    drawingStroke(ctx, spec);
    ctx.beginPath();
    ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, paneHeight);
    ctx.moveTo(x + width - .5, 0); ctx.lineTo(x + width - .5, paneHeight);
    ctx.stroke();
  }
}

function drawNativeHorizontalLine(ctx, spec, coords) {
  var y = candleSeries.priceToCoordinate(spec.price);
  if (y === null) return;
  drawingStroke(ctx, spec);
  ctx.beginPath(); ctx.moveTo(coords.x1, y); ctx.lineTo(coords.x2, y); ctx.stroke();
}

function drawNativeTrendLine(ctx, spec, coords) {
  var y1 = candleSeries.priceToCoordinate(spec.y1);
  var y2 = candleSeries.priceToCoordinate(spec.y2);
  if (y1 === null || y2 === null) return;
  drawingStroke(ctx, spec);
  ctx.beginPath(); ctx.moveTo(coords.x1, y1); ctx.lineTo(coords.x2, y2); ctx.stroke();
}

function drawNativeLabel(ctx, spec, coords) {
  var y = candleSeries.priceToCoordinate(spec.price);
  if (y === null) return;
  var text = spec.text || '';
  var x = coords.x1;
  var above = spec.position !== 'below';
  ctx.font = '600 10px Manrope, Segoe UI, sans-serif';
  var paddingX = 5;
  var height = 18;
  var width = Math.ceil(ctx.measureText(text).width) + paddingX * 2;
  var top = above ? y - height - 8 : y + 8;
  ctx.fillStyle = nativeLabelBackground(spec.color || '#58a6ff');
  roundNativeRect(ctx, x - width / 2, top, width, height, 4);
  ctx.fill();
  ctx.strokeStyle = spec.color || '#58a6ff'; ctx.lineWidth = 1; ctx.stroke();
  ctx.fillStyle = spec.color || '#58a6ff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, x, top + height / 2 + .5);
}

function nativeLabelBackground(color) {
  var hex = color.replace('#', '').slice(0, 6);
  if (hex.length !== 6) return 'rgba(13, 17, 23, 0.92)';
  return 'rgba(' + parseInt(hex.slice(0, 2), 16) + ',' +
    parseInt(hex.slice(2, 4), 16) + ',' + parseInt(hex.slice(4, 6), 16) + ',0.18)';
}

function nativeTransparentColor(color, fallback) {
  if (!color) return fallback;
  var hex = color.replace('#', '');
  if (hex.length === 6) {
    return 'rgba(' + parseInt(hex.slice(0, 2), 16) + ',' +
      parseInt(hex.slice(2, 4), 16) + ',' + parseInt(hex.slice(4, 6), 16) + ',0.14)';
  }
  return color;
}

function roundNativeRect(ctx, x, y, width, height, radius) {
  var r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r); ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r); ctx.closePath();
}

function createStrategyDrawing(spec) {
  if (!candleSeries || typeof candleSeries.attachPrimitive !== 'function') return null;
  if (['rectangle', 'region', 'hline', 'line', 'label'].indexOf(spec.type) === -1) return null;
  var primitive = new StrategyDrawingPrimitive(spec);
  candleSeries.attachPrimitive(primitive);
  return primitive;
}

function removeStrategyDrawing(primitive) {
  if (candleSeries && typeof candleSeries.detachPrimitive === 'function') {
    candleSeries.detachPrimitive(primitive);
  }
}
