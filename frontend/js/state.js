// ══════════════════════════════════════════════
// GLOBAL STATE
// All shared variables live here so every other
// file can read and update them.
// ══════════════════════════════════════════════

var allEvents    = [];
var currentIndex = 0;
var isPlaying    = false;
var playTimer    = null;
var playSpeed    = 200;
var showLines    = true;
var tradeCount   = 0;
var openTrade    = null;
var totalBars    = 0;
var barsDrawn    = 0;

// Chart objects (created in charts.js)
var chart, candleSeries, fastEmaSeries, slowEmaSeries;
var equityChart, equitySeries;
var markerPlugin = null;          // v5 marker plugin for the main chart
var drawdownMarkerSeries = null;  // red highlight line on equity chart

// Data buffers
var candleData   = [];
var fastEmaData  = [];
var slowEmaData  = [];
var equityData   = [];
var tradeMarkers = [];   // raw marker objects for the candlestick chart
var tradeLines   = [];   // line series for entry-exit connectors

// Last metrics report received from the server
var lastMetricsReport = null;