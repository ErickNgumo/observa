// ══════════════════════════════════════════════
// MAX DRAWDOWN HIGHLIGHT + CLICK-TO-REPLAY
// Draws a red highlight over the worst drawdown
// period on the equity curve and lets the user
// click a banner to jump the replay back to the
// peak that preceded it.
// ══════════════════════════════════════════════

// Draws the red highlight line + markers on the
// equity chart for the max drawdown period
// reported by the engine.
function drawDrawdownHighlight(report) {
  if (!report.max_drawdown_start || !report.max_drawdown_end) {
    return; // no drawdown recorded
  }

  var startUnix = toUnix(report.max_drawdown_start);
  var endUnix   = toUnix(report.max_drawdown_end);

  // Find the closest equity point to each target time,
  // rather than requiring an exact timestamp match —
  // serialization/timezone rounding can shift things
  // by a second or two.
  function closestPoint(targetUnix) {
    var closest = null;
    var smallestDiff = Infinity;
    for (var i = 0; i < equityData.length; i++) {
      var diff = Math.abs(equityData[i].time - targetUnix);
      if (diff < smallestDiff) {
        smallestDiff = diff;
        closest = equityData[i];
      }
    }
    return closest;
  }

  // Find the equity values at those two points
  var startPoint = closestPoint(startUnix);
  var endPoint   = closestPoint(endUnix);

  
  if (!startPoint || !endPoint) {
    console.warn('Drawdown highlight: could not find matching equity points', {
      startUnix: startUnix, endUnix: endUnix
    });
    return;
  }

  var LC = LightweightCharts;

  // Remove any previous highlight before drawing a new one
  if (drawdownMarkerSeries) {
    equityChart.removeSeries(drawdownMarkerSeries);
    drawdownMarkerSeries = null;
  }

  drawdownMarkerSeries = equityChart.addSeries(LC.LineSeries, {
    color:            '#f85149',
    lineWidth:        3,
    priceLineVisible: false,
    lastValueVisible: false
  });
  drawdownMarkerSeries.setData([startPoint, endPoint]);

  // Markers at the peak and trough
  LC.createSeriesMarkers(equitySeries, [
    {
      time:     startPoint.time,
      position: 'aboveBar',
      color:    '#f85149',
      shape:    'arrowDown',
      text:     'Peak: $' + fmtNum(startPoint.value, 0)
    },
    {
      time:     endPoint.time,
      position: 'belowBar',
      color:    '#f85149',
      shape:    'circle',
      text:     '-' + fmtNum(report.max_drawdown_pct, 1) + '%'
    }
  ]);

  // Remember where to jump to when the banner is clicked
  window._ddStartIndex = findEventIndexNearTime(startPoint.time);

  showDrawdownBanner(report);
}

// Creates (or replaces) the clickable warning banner
// shown in the top-right corner of the equity panel.
function showDrawdownBanner(report) {
  var existing = document.getElementById('dd-banner');
  if (existing) existing.remove();

  var banner = document.createElement('div');
  banner.id = 'dd-banner';
  banner.textContent =
    '⚠ Max Drawdown: -' + fmtNum(report.max_drawdown_pct, 1) +
    '% — click to jump to peak';
  banner.onclick = function() {
    jumpToDrawdownPeak();
  };

  document.getElementById('equity-panel').appendChild(banner);
}

// Resets the replay and fast-forwards it to the bar
// just before the max drawdown peak, so the user can
// watch it unfold from there.
function jumpToDrawdownPeak() {
  if (isPlaying) togglePlay();

  var targetIndex = window._ddStartIndex || 0;

  resetReplay();

  for (var i = 0; i < targetIndex; i++) {
    processEvent(allEvents[i]);
  }
  currentIndex = targetIndex;

  console.log('Jumped to drawdown peak at index ' + targetIndex);
}

// Removes the drawdown highlight, markers, and banner.
// Called from resetReplay() in playback.js.
function clearDrawdownHighlight() {
  if (drawdownMarkerSeries) {
    equityChart.removeSeries(drawdownMarkerSeries);
    drawdownMarkerSeries = null;
  }
  var banner = document.getElementById('dd-banner');
  if (banner) banner.remove();
}