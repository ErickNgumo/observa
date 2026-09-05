// ══════════════════════════════════════════════
// MAX DRAWDOWN INVESTIGATION
// Adapts the metrics report to the generic Investigation Mode. It never
// resets, seeks, pauses, or otherwise changes replay state.
// ══════════════════════════════════════════════

function closestEquityPoint(targetUnix) {
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

function drawDrawdownHighlight(report) {
  if (!report.max_drawdown_start || !report.max_drawdown_end) return;

  var startPoint = closestEquityPoint(toUnix(report.max_drawdown_start));
  var endPoint = closestEquityPoint(toUnix(report.max_drawdown_end));
  if (!startPoint || !endPoint) return;

  registerInvestigation('max-drawdown', {
    label: 'Maximum drawdown',
    shortLabel: 'Max drawdown',
    summary: '-' + fmtNum(report.max_drawdown_pct, 1) + '%',
    showEquityOutline: true,
    clickToInspect: true,
    outlineColor: '#f06c77',
    range: { start: startPoint.time, end: endPoint.time }
  });
}

function inspectMaxDrawdown() {
  enterInvestigation('max-drawdown');
}

// Compatibility alias for the existing reset lifecycle.
function clearDrawdownHighlight() {
  clearInvestigation();
  clearInvestigationOutlines();
}
