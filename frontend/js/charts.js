// ══════════════════════════════════════════════
// CHART SETUP
// Creates the candlestick chart and the equity
// curve chart using TradingView Lightweight
// Charts v5. Also holds small chart-related
// helpers used elsewhere.
// ══════════════════════════════════════════════

function initCharts() {
  var LC = LightweightCharts;

  // ── Main candlestick chart ─────────────────
  chart = LC.createChart(document.getElementById('chart'), {
    layout: {
      background: { color: '#0d1117' },
      textColor:  '#8b949e'
    },
    grid: {
      vertLines: { color: '#21262d' },
      horzLines: { color: '#21262d' }
    },
    crosshair: { mode: LC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#30363d' },
    timeScale: {
      borderColor:    '#30363d',
      timeVisible:    true,
      secondsVisible: false,
      rightOffset:    5,
      barSpacing:     4
    },
    width:  document.getElementById('chart').clientWidth,
    height: document.getElementById('chart').clientHeight
  });

  candleSeries = chart.addSeries(LC.CandlestickSeries, {
    upColor:         '#3fb950',
    downColor:       '#f85149',
    borderUpColor:   '#3fb950',
    borderDownColor: '#f85149',
    wickUpColor:     '#3fb950',
    wickDownColor:   '#f85149'
  });

  fastEmaSeries = chart.addSeries(LC.LineSeries, {
    color:            '#58a6ff',
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
      background: { color: '#161b22' },
      textColor:  '#8b949e'
    },
    grid: {
      vertLines: { color: '#21262d' },
      horzLines: { color: '#21262d' }
    },
    rightPriceScale: { borderColor: '#30363d' },
    timeScale: {
      borderColor:    '#30363d',
      timeVisible:    true,
      secondsVisible: false
    },
    width:  document.getElementById('equity-panel').clientWidth,
    height: document.getElementById('equity-panel').clientHeight
  });

  equitySeries = equityChart.addSeries(LC.LineSeries, {
    color:            '#3fb950',
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