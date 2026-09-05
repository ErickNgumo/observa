// ══════════════════════════════════════════════
// GLOBAL STATE (OBS-0010 — canonical replay)
// Shared variables live here so every other file can read and update them.
// The authoritative view is derived deterministically from the canonical
// event stream (see replay-core.js); these are presentation buffers only.
// ══════════════════════════════════════════════

// Canonical inputs fetched from /api/replay
var payload       = null;   // full replay payload
var replayEvents  = [];     // canonical events (event_seq order)
var replayBars    = [];     // canonical OHLC bars
var replayIndex   = null;   // { preamble, bars, endEventOfBar }
var currentBar    = -1;     // -1 = nothing shown; else last shown bar index
var finished      = false;  // reached the end-of-run (completed or failed)
var currentView   = null;   // last derived view (ObservaReplay.stateThrough)

// Playback controls
var isPlaying = false;
var playTimer = null;
var playSpeed = 200;
var showLines = true;
var totalBars = 0;
var barsDrawn = 0;

// Chart objects (created in charts.js)
var chart, candleSeries, fastEmaSeries, slowEmaSeries;
var equityChart, equitySeries, balanceSeries;
var markerPlugin = null; // v5 marker plugin for the main chart

// Presentation buffers
var candleData   = [];
var equityData   = []; // equity curve points (canonical snapshots)
var balanceData  = []; // balance curve points (canonical snapshots)
var tradeMarkers = []; // raw marker objects for the candlestick chart
var tradeLines   = []; // line series for entry-exit connectors
var activeDrawings = {}; // active strategy drawing series (id -> series[])

// Last metrics report received from the server
var lastMetricsReport = null;
