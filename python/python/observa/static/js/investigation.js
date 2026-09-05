// ══════════════════════════════════════════════
// INVESTIGATION MODE
// Reusable, non-mutating evidence highlighting for statistics. A statistic
// supplies a time range; this module highlights that range without touching
// replay position, playback, event buffers, or chart viewport.
// ══════════════════════════════════════════════

var investigations = {};
var activeInvestigation = null;
var investigationEquitySeries = null;
var investigationOutlines = {};

function registerInvestigation(id, definition) {
  investigations[id] = definition;
  if (definition.showEquityOutline) renderInvestigationOutline(id, definition);
}

function enterInvestigation(id) {
  var definition = investigations[id];
  if (!definition || !definition.range) return;

  clearInvestigation();
  activeInvestigation = definition;
  document.body.classList.add('is-inspecting');

  renderInvestigationEquity(definition);
  renderInvestigationOverlay(definition);
  highlightInvestigationTrades(definition.range);
  showInvestigationBanner(definition);
}

function clearInvestigation() {
  if (investigationEquitySeries) {
    equityChart.removeSeries(investigationEquitySeries);
    investigationEquitySeries = null;
  }
  activeInvestigation = null;
  document.body.classList.remove('is-inspecting');
  document.querySelectorAll('#trade-log-body tr').forEach(function(row) {
    row.classList.remove('is-inspection-match', 'is-inspection-muted');
  });
  var overlay = document.getElementById('investigation-overlay');
  if (overlay) overlay.remove();
  var banner = document.getElementById('investigation-banner');
  if (banner) banner.remove();
}

function renderInvestigationEquity(definition) {
  // The persistent outline already traces this range. During inspection we
  // add a brighter overlay so it remains obvious among other evidence.
  var points = equityData.filter(function(point) {
    return point.time >= definition.range.start && point.time <= definition.range.end;
  });
  if (points.length === 0) return;

  investigationEquitySeries = equityChart.addSeries(LightweightCharts.LineSeries, {
    color: '#f06c77', lineWidth: 3, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false
  });
  investigationEquitySeries.setData(points);
}

function renderInvestigationOutline(id, definition) {
  clearInvestigationOutline(id);
  var points = equityData.filter(function(point) {
    return point.time >= definition.range.start && point.time <= definition.range.end;
  });
  if (points.length === 0) return;

  investigationOutlines[id] = equityChart.addSeries(LightweightCharts.LineSeries, {
    color: definition.outlineColor || '#f06c77', lineWidth: 4,
    priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false
  });
  investigationOutlines[id].setData(points);
}

function clearInvestigationOutline(id) {
  if (investigationOutlines[id]) {
    equityChart.removeSeries(investigationOutlines[id]);
    delete investigationOutlines[id];
  }
}

function clearInvestigationOutlines() {
  Object.keys(investigationOutlines).forEach(clearInvestigationOutline);
}

function renderInvestigationOverlay(definition) {
  var container = document.getElementById('chart-container');
  var overlay = document.createElement('div');
  overlay.id = 'investigation-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  overlay.innerHTML = '<span>' + definition.shortLabel + '</span>';
  container.appendChild(overlay);
  updateInvestigationOverlay();
}

function updateInvestigationOverlay() {
  if (!activeInvestigation || !chart) return;
  var overlay = document.getElementById('investigation-overlay');
  if (!overlay) return;
  var start = chart.timeScale().timeToCoordinate(activeInvestigation.range.start);
  var end = chart.timeScale().timeToCoordinate(activeInvestigation.range.end);
  var width = document.getElementById('chart-container').clientWidth;

  if (start === null || end === null || width === 0) {
    overlay.style.display = 'none';
    return;
  }
  var left = Math.max(0, Math.min(start, end));
  var right = Math.min(width, Math.max(start, end));
  overlay.style.display = right > left ? 'block' : 'none';
  overlay.style.left = left + 'px';
  overlay.style.width = Math.max(0, right - left) + 'px';
}

function highlightInvestigationTrades(range) {
  document.querySelectorAll('#trade-log-body tr').forEach(function(row) {
    var entryTime = Number(row.getAttribute('data-entry-time'));
    var exitTime = Number(row.getAttribute('data-exit-time'));
    var matches = entryTime <= range.end && exitTime >= range.start;
    row.classList.toggle('is-inspection-match', matches);
    row.classList.toggle('is-inspection-muted', !matches);
  });
}

function showInvestigationBanner(definition) {
  var banner = document.createElement('aside');
  banner.id = 'investigation-banner';
  banner.innerHTML = '<div><span>Inspection mode</span><strong>' + definition.label + ' <em>' + definition.summary + '</em></strong></div>' +
    '<button type="button" onclick="clearInvestigation()">Clear inspection</button>';
  document.getElementById('chart-container').appendChild(banner);
}

// Keep an active evidence band aligned while the user pans, zooms, or resizes.
function initializeInvestigationMode() {
  chart.timeScale().subscribeVisibleTimeRangeChange(updateInvestigationOverlay);
  window.addEventListener('resize', updateInvestigationOverlay);

  // Persistent statistic outlines are direct entry points into investigation.
  // Clicks only add visual evidence; replay position and playback are untouched.
  equityChart.subscribeClick(function(param) {
    if (!param.seriesData) return;
    Object.keys(investigationOutlines).some(function(id) {
      var outline = investigationOutlines[id];
      var definition = investigations[id];
      if (definition && definition.clickToInspect && param.seriesData.get(outline)) {
        enterInvestigation(id);
        return true;
      }
      return false;
    });
  });
}
