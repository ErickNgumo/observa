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
  equityChart = LC.createChart(document.getElementById('equity-panel'), {
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
    width:  document.getElementById('equity-panel').clientWidth,
    height: document.getElementById('equity-panel').clientHeight
  });

  equitySeries = equityChart.addSeries(LC.LineSeries, {
    color:            activeTheme.positive,
    lineWidth:        2,
    priceLineVisible: false
  });

  // Resize both charts whenever the window resizes
  window.addEventListener('resize', function() {
    chart.resize(
      document.getElementById('chart').clientWidth,
      document.getElementById('chart').clientHeight
    );
    equityChart.resize(
      document.getElementById('equity-panel').clientWidth,
      document.getElementById('equity-panel').clientHeight
    );
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
  chart.resize(
    document.getElementById('chart').clientWidth,
    document.getElementById('chart').clientHeight
  );
  equityChart.resize(
    document.getElementById('equity-panel').clientWidth,
    document.getElementById('equity-panel').clientHeight
  );
}
