// ══════════════════════════════════════════════
// CHART SETUP
// Creates the candlestick chart and the equity
// curve chart using TradingView Lightweight
// Charts v5. Also holds small chart-related
// helpers used elsewhere.
// ══════════════════════════════════════════════

function initCharts() {
  var LC = LightweightCharts;
  var activeTheme = observaThemes[(document.getElementById('theme-select') || {}).value] || observaThemes.midnight;

  // ── Main candlestick chart ─────────────────
  chart = LC.createChart(document.getElementById('chart'), {
    layout: {
      background: { color: activeTheme.chart },
      textColor:  activeTheme.muted
    },
    grid: {
      vertLines: { color: activeTheme.grid },
      horzLines: { color: activeTheme.grid }
    },
    crosshair: { mode: LC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: activeTheme.border },
    timeScale: {
      borderColor:    activeTheme.border,
      timeVisible:    true,
      secondsVisible: false,
      rightOffset:    5,
      barSpacing:     4
    },
    width:  document.getElementById('chart').clientWidth,
    height: document.getElementById('chart').clientHeight
  });

  candleSeries = chart.addSeries(LC.CandlestickSeries, {
    upColor:         activeTheme.positive,
    downColor:       activeTheme.negative,
    borderUpColor:   activeTheme.positive,
    borderDownColor: activeTheme.negative,
    wickUpColor:     activeTheme.positive,
    wickDownColor:   activeTheme.negative
  });

  fastEmaSeries = chart.addSeries(LC.LineSeries, {
    color:            activeTheme.accent,
    lineWidth:        1,
    priceLineVisible: false,
    lastValueVisible: false
  });

  slowEmaSeries = chart.addSeries(LC.LineSeries, {
    color:            '#f78166',
    lineWidth:        1,
    priceLineVisible: false,
    lastValueVisible: false
  });

  // v5 marker plugin — replaces the old setMarkers() on series
  markerPlugin = LC.createSeriesMarkers(candleSeries, []);

  // ── Equity curve chart ─────────────────────
  equityChart = LC.createChart(document.getElementById('equity-chart'), {
    layout: {
      background: { color: activeTheme.surface },
      textColor:  activeTheme.muted
    },
    grid: {
      vertLines: { color: activeTheme.grid },
      horzLines: { color: activeTheme.grid }
    },
    rightPriceScale: { borderColor: activeTheme.border },
    timeScale: {
      borderColor:    activeTheme.border,
      timeVisible:    true,
      secondsVisible: false
    },
    width:  document.getElementById('equity-chart').clientWidth,
    height: document.getElementById('equity-chart').clientHeight
  });

  equitySeries = equityChart.addSeries(LC.LineSeries, {
    color:            activeTheme.positive,
    lineWidth:        2,
    priceLineVisible: false
  });

  // Keep the selected equity observation visible while investigating the curve.
  equityChart.subscribeCrosshairMove(function(param) {
    var inspector = document.getElementById('equity-inspector');
    if (!inspector) return;
    var point = param.seriesData && param.seriesData.get(equitySeries);
    if (!point || point.value === undefined || !param.time) {
      inspector.innerHTML = '<span>Point</span><strong>Hover curve</strong>';
      return;
    }
    var timestamp = typeof param.time === 'number' ? param.time : param.time.timestamp;
    var time = timestamp ? new Date(timestamp * 1000).toISOString().slice(0, 16).replace('T', ' ') : '—';
    inspector.innerHTML = '<span>' + time + '</span><strong>Balance $' + fmtNum(point.value, 2) + '</strong>';
  });

  // Resize both charts whenever the window resizes
  window.addEventListener('resize', function() {
    resizeCharts();
  });
}

// Redraws every marker currently stored in tradeMarkers.
// Called any time a position opens or closes.
function refreshMarkers() {
  var sorted = tradeMarkers.slice().sort(function(a, b) {
    return a.time - b.time;
  });
  markerPlugin.setMarkers(sorted);
}

// Resizes both charts — used after the bottom panel
// is collapsed or expanded.
function resizeCharts() {
  var chartEl = document.getElementById('chart');
  var equityEl = document.getElementById('equity-chart');

  if (chartEl.clientWidth > 0 && chartEl.clientHeight > 0) {
    chart.resize(chartEl.clientWidth, chartEl.clientHeight);
  }
  // A hidden analysis tab has a zero-sized container. Avoid resizing the
  // equity canvas to 0×0; it will resize on the next visible layout pass.
  if (equityEl.clientWidth > 0 && equityEl.clientHeight > 0) {
    equityChart.resize(equityEl.clientWidth, equityEl.clientHeight);
  }
}
