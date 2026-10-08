// Presentation-only research workspace helpers. No financial derivations.
var chartFollowing = true;
var selectedTradeId = null;

function instrumentLabel(run) {
  run = run || {};
  return (run.symbol || 'Loaded run') + (run.interval ? ' · ' + run.interval : '');
}

function followRange(lastIndex, width, spacing) {
  var span = Math.max(10, width / Math.max(1, spacing));
  return { from: lastIndex - span * 0.8, to: lastIndex + span * 0.2 };
}

function tradeDuration(entry, exit) {
  if (!Number.isFinite(entry) || !Number.isFinite(exit) || exit < entry) return '—';
  var minutes = Math.floor((exit - entry) / 60);
  if (minutes < 60) return minutes + 'm';
  if (minutes < 1440) return Math.floor(minutes / 60) + 'h ' + minutes % 60 + 'm';
  return Math.floor(minutes / 1440) + 'd ' + Math.floor(minutes % 1440 / 60) + 'h';
}

var conceptHelp = {
  'Balance': 'Recorded cash balance after realised outcomes and charges.',
  'Equity': 'Recorded account value including unrealised P&L on open positions.',
  'Used margin': 'Margin reserved for open positions.',
  'Free margin': 'Account equity available after reserved margin.',
  'Unrealised P&L': 'Recorded mark-to-market result of positions still open.',
  'Realised P&L': 'Realised P&L recorded in the account snapshot.',
  'Sharpe Ratio': 'Canonical risk-adjusted return relative to return variability. Short samples can be misleading.',
  'Calmar Ratio': 'Annualised return relative to maximum drawdown.',
  'Profit Factor': 'Canonical ratio of gross profits to gross losses.',
  'Expectancy': 'Canonical average net outcome per closed trade.',
  'Max Drawdown': 'Largest recorded peak-to-trough equity decline. Click to inspect the recorded period.',
  'Current Drawdown': 'Drawdown at the end of the complete run.',
  'Annualised Return': 'Complete-run return expressed at an annual rate.',
  'Total Return': 'Canonical total return for the complete run.',
  'Win Rate': 'Percentage of closed trades recorded as winners.',
  'Order state': 'Latest recorded lifecycle state: created, pending, triggered, filled, rejected or expired.',
  'Position state': 'Open until a recorded close for that exact position ticket.',
  'Signal / decision': 'Intent emitted by the strategy. A signal does not guarantee an order fill.'
};
function helpLabel(label) {
  var tip = conceptHelp[label];
  return escapeHtml(label) + (tip ? ' <span class="info-tip" tabindex="0" role="img" aria-label="' + escapeHtml(tip) + '" title="' + escapeHtml(tip) + '">ⓘ</span>' : '');
}

function pauseChartFollow() {
  chartFollowing = false;
  updateFollowControl();
}
function updateFollowControl() {
  var button = document.getElementById('btn-follow');
  button.textContent = chartFollowing ? 'Following replay' : 'Resume follow';
  button.classList.toggle('active', chartFollowing);
  button.setAttribute('aria-pressed', String(chartFollowing));
}
function followReplayChart() {
  if (!chartFollowing || !candleData.length) return;
  var scale = chart.timeScale();
  var range = followRange(candleData.length - 1, scale.width(), scale.options().barSpacing);
  scale.scrollToPosition(range.to - (candleData.length - 1), false);
  chart.priceScale('right').applyOptions({ autoScale: true });
}
function resumeChartFollow() {
  chartFollowing = true;
  clearInvestigation();
  selectedTradeId = null;
  if (currentView) renderTradeLog(currentView);
  updateFollowControl();
  followReplayChart();
}
function fitReplayChart() {
  pauseChartFollow();
  chart.timeScale().fitContent();
  chart.priceScale('right').applyOptions({ autoScale: true });
}
function selectTrade(index) {
  var trade = currentView && currentView.closedTrades[index];
  if (!trade) return;
  stopPlayback(); isPlaying = false; setPlayButton(finished ? 'done' : 'idle');
  pauseChartFollow();
  selectedTradeId = trade.position_id;
  renderTradeLog(currentView);
  var start = markerBarTime(trade.opened_bar), end = markerBarTime(trade.closed_bar);
  if (start === null || end === null) return;
  var padding = Math.max(8, (trade.closed_bar - trade.opened_bar) * 0.2);
  chart.timeScale().setVisibleLogicalRange({ from: trade.opened_bar - padding, to: trade.closed_bar + padding });
  chart.priceScale('right').applyOptions({ autoScale: true });
  registerInvestigation('trade', {
    color: 'var(--accent)', range: { start: start, end: end }, shortLabel: 'Trade ' + (index + 1),
    label: 'Trade ' + (index + 1) + ' · ' + trade.side.toUpperCase(),
    summary: exitReasonLabel[trade.exit_reason] || trade.exit_reason
  });
  enterInvestigation('trade');
}
function initializeResearchWorkspace() {
  updateFollowControl();
  var host = document.getElementById('chart');
  var down = null;
  host.addEventListener('wheel', pauseChartFollow, { passive: true });
  host.addEventListener('pointerdown', function(e) { down = { x: e.clientX, y: e.clientY }; });
  host.addEventListener('pointermove', function(e) {
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 3) pauseChartFollow();
  });
  window.addEventListener('pointerup', function() { down = null; });
  host.addEventListener('pointercancel', function() { down = null; });
  chart.subscribeClick(function(param) {
    if (!param.time) return;
    var index = drawingBarTimes.indexOf(param.time);
    if (index < 0 || index > currentBar) return;
    stopPlayback(); isPlaying = false; pauseChartFollow();
    renderToBar(index); setPlayButton(finished ? 'done' : 'idle');
    showPanel('replay');
  });
  document.getElementById('trade-log-body').addEventListener('click', function(e) {
    var row = e.target.closest('[data-trade-index]');
    if (row) selectTrade(Number(row.dataset.tradeIndex));
  });
  document.getElementById('trade-log-body').addEventListener('keydown', function(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var row = e.target.closest('[data-trade-index]');
    if (row) { e.preventDefault(); selectTrade(Number(row.dataset.tradeIndex)); }
  });
  ['positions-body', 'orders-body'].forEach(function(id) {
    var body = document.getElementById(id);
    function selectRow(e) {
      if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
      var row = e.target.closest('tr');
      if (!row || row.querySelector('.empty-note')) return;
      if (e.type === 'keydown') e.preventDefault();
      body.querySelectorAll('tr').forEach(function(r) {
        r.classList.toggle('is-selected', r === row);
        r.setAttribute('aria-selected', String(r === row));
      });
    }
    body.addEventListener('click', selectRow);
    body.addEventListener('keydown', selectRow);
  });
  document.querySelector('#positions-body').closest('table').querySelector('th:last-child').innerHTML = helpLabel('Position state');
  document.querySelector('#orders-body').closest('table').querySelector('th:last-child').innerHTML = helpLabel('Order state');
  document.getElementById('bar-decision').title = conceptHelp['Signal / decision'];
}
