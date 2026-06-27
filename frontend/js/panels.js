// ══════════════════════════════════════════════
// BOTTOM PANEL CONTROLS
// Tab switching (Equity Curve / Trade Log /
// Metrics) and the collapse/expand toggle.
// ══════════════════════════════════════════════

function showPanel(tab) {
  document.getElementById('equity-panel').style.display  = tab === 'equity'  ? 'block' : 'none';
  document.getElementById('trade-log').style.display     = tab === 'trades'  ? 'block' : 'none';
  document.getElementById('metrics-panel').style.display  = tab === 'metrics' ? 'block' : 'none';

  var tabs = document.querySelectorAll('.panel-tab');
  tabs[0].classList.toggle('active', tab === 'equity');
  tabs[1].classList.toggle('active', tab === 'trades');
  tabs[2].classList.toggle('active', tab === 'metrics');
}

function togglePanel() {
  var panel     = document.getElementById('bottom-panel');
  var toggle    = document.getElementById('panel-toggle');
  var collapsed = panel.classList.toggle('collapsed');
  toggle.textContent = collapsed ? '▲' : '▼';

  // Wait for the CSS height transition to finish
  // before resizing the charts inside the panel.
  setTimeout(resizeCharts, 220);
}