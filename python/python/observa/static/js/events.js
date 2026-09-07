// ══════════════════════════════════════════════
// CANONICAL REPLAY DRIVER (OBS-0010)
// Loads the canonical replay payload (/api/replay), derives the view from
// canonical events (ObservaReplay) and renders bar-by-bar state:
// candles, markers, positions, orders, account, equity/balance and the
// current-bar event inspector. The frontend never computes economics.
// ══════════════════════════════════════════════

var exitReasonLabel = { StopLoss: 'Stop Loss', TakeProfit: 'Take Profit', Signal: 'Signal' };
var exitReasonCode  = { StopLoss: 'SL', TakeProfit: 'TP', Signal: 'X' };

function loadEvents() {
  return fetch('/api/replay')
    .then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    })
    .then(function (data) {
      payload      = data;
      replayEvents = data.events || [];
      replayBars   = data.bars || [];
      totalBars    = replayBars.length;
      replayIndex  = ObservaReplay.indexEvents(replayEvents);
      if (totalBars === 0 && replayEvents.length > 0) {
        showNotice('The dataset for this run could not be recovered, so the ' +
          'candle chart is unavailable. Events, orders, positions and ' +
          'account state still replay below.');
      }
      updateProgressLabel();
      if (payload.run && payload.run.status === 'failed') {
        var meta = payload.run;
        showRunFailed(meta.error_category || 'run_failed', meta.error_message || 'run failed', null);
      }
      renderToBar(-1);
      console.log('Observa ready: ' + replayEvents.length + ' canonical events, ' + totalBars + ' bars');
    })
    .catch(function (err) {
      showRunFailed('runtime', 'Failed to load replay payload: ' + err, null);
      console.error('Failed to load replay payload:', err);
    });
}

// ── Navigation helpers ─────────────────────────

function maxReplayBar() {
  // Bars actually processed (bucketed). Failed runs may stop before the end
  // of the dataset; we never invent events for unprocessed bars.
  return replayIndex ? replayIndex.bars.length - 1 : -1;
}

function updateProgressLabel() {
  var shown = currentBar >= 0 ? currentBar + 1 : 0;
  var el = document.getElementById('stat-progress');
  if (el) el.textContent = 'Bar ' + shown + ' / ' + totalBars;
  var fill = document.getElementById('progress-fill');
  if (fill) fill.style.width = (totalBars > 0 ? (shown / totalBars) * 100 : 0) + '%';
}

function endEventOfBar(k) {
  if (k < 0 || !replayIndex) return -1;
  if (k >= replayIndex.endEventOfBar.length) k = replayIndex.endEventOfBar.length - 1;
  return replayIndex.endEventOfBar[k];
}

// ── Deterministic rendering to bar k ───────────

function renderToBar(k) {
  if (!payload || !replayIndex) return;
  var maxK = maxReplayBar();
  if (k > maxK) k = maxK;
  currentBar = k;

  var endIdx = endEventOfBar(k);
  var view = ObservaReplay.stateThrough(replayEvents, endIdx);
  if (payload.run && payload.run.symbol) view.symbol = payload.run.symbol;
  currentView = view;

  // Finished only when we processed through a run_completed / run_failed tail.
  finished = (k === maxK) && (!!view.completed || !!view.failed);

  renderCandles(k, view);
  renderMarkers(endIdx);
  renderAccount(view);
  renderPositions(view);
  renderOrders(view);
  renderBarEvents(k);
  renderTradeLog(view);
  renderCurves(endIdx, view);
  updateProgressLabel();

  if (view.failed) {
    showRunFailed(view.failed.category, view.failed.message, k);
  } else if (view.completed && finished) {
    hideRunFailed();
    if (payload.metrics) renderMetrics(payload.metrics);
    setPlayButton('done');
  }
  chart.timeScale().scrollToPosition(0, false);
}

function renderCandles(k, view) {
  candleData = [];
  for (var i = 0; i <= k && i < replayBars.length; i++) {
    var b = replayBars[i];
    candleData.push({
      time: toUnix(b.time), open: b.open, high: b.high, low: b.low, close: b.close
    });
  }
  candleSeries.setData(candleData);
  barsDrawn = candleData.length;
}

function markerBarTime(barIndex) {
  var b = replayBars[barIndex];
  return b ? toUnix(b.time) : null;
}

function renderMarkers(endIdx) {
  tradeMarkers = [];
  for (var i = 0; i <= endIdx && i < replayEvents.length; i++) {
    var e = replayEvents[i];
    if (e.type === 'position_opened') {
      var t = markerBarTime(e.bar_index);
      if (t === null) continue;
      tradeMarkers.push({
        time: t,
        position: e.side === 'Buy' ? 'belowBar' : 'aboveBar',
        color: e.side === 'Buy' ? '#3fb950' : '#f85149',
        shape: e.side === 'Buy' ? 'arrowUp' : 'arrowDown',
        text: (e.side === 'Buy' ? 'B' : 'S') + ' @ ' + Number(e.entry_price).toFixed(5)
      });
    } else if (e.type === 'position_closed') {
      var ct = markerBarTime(e.bar_index);
      if (ct === null) continue;
      var pnl = e.net_realized_pnl;
      var red = e.exit_reason === 'StopLoss' || pnl < 0;
      tradeMarkers.push({
        time: ct,
        position: e.side === 'Buy' ? 'aboveBar' : 'belowBar',
        color: red ? '#f85149' : '#3fb950',
        shape: 'circle',
        text: exitReasonCode[e.exit_reason] || 'X' + ' @ ' + Number(e.exit_price).toFixed(5)
      });
    }
  }
  refreshMarkers();
}

function renderAccount(view) {
  var balance = document.getElementById('stat-balance');
  var equity = document.getElementById('stat-equity');
  var open = document.getElementById('stat-open');
  if (view.account) {
    balance.textContent = fmtNum(view.account.balance, 2);
    equity.textContent  = fmtNum(view.account.equity, 2);
    open.textContent    = String(countOpen(view));
  } else {
    balance.textContent = '—';
    equity.textContent  = '—';
    open.textContent    = '—';
  }
  document.getElementById('stat-trades').textContent = view.closedTrades.length;
  renderAccountPanel(view);
}

function countOpen(view) {
  var n = 0;
  view.positions.forEach(function (p) { if (p.open) n++; });
  return n;
}

function renderAccountPanel(view) {
  var box = document.getElementById('account-figures');
  if (!box) return;
  var a = view.account;
  var html = '';
  function fig(label, value, cls) {
    return '<div class="account-figure' + (cls ? ' ' + cls : '') + '"><span>' + label + '</span><strong>' + value + '</strong></div>';
  }
  if (!a) {
    html = fig('Balance', '—') + fig('Equity', '—') + fig('Used margin', '—') + fig('Free margin', '—');
  } else {
    html = fig('Balance', '$' + fmtNum(a.balance, 2)) +
           fig('Equity', '$' + fmtNum(a.equity, 2)) +
           fig('Used margin', '$' + fmtNum(a.used_margin, 2)) +
           fig('Free margin', '$' + fmtNum(a.free_margin, 2)) +
           fig('Unrealised P&L', (a.unrealised_pnl >= 0 ? '+' : '') + '$' + fmtNum(a.unrealised_pnl, 2), a.unrealised_pnl >= 0 ? 'positive' : 'negative') +
           fig('Realised P&L', (a.realised_pnl >= 0 ? '+' : '') + '$' + fmtNum(a.realised_pnl, 2), a.realised_pnl >= 0 ? 'positive' : 'negative');
  }
  box.innerHTML = html;
}

function positionDirBadge(side) {
  return side === 'Buy' ? 'long' : 'short';
}

function renderPositions(view) {
  var tbody = document.getElementById('positions-body');
  if (!tbody) return;
  var rows = [];
  view.positions.forEach(function (p) {
    var exitCell = p.open
      ? '<span class="tag-open">open</span>'
      : '<span class="tag-closed">closed · ' + (exitReasonLabel[p.exit.exit_reason] || p.exit.exit_reason) + '</span>';
    rows.push(
      '<tr class="' + (p.open ? 'row-open' : 'row-closed') + '">' +
      '<td><span class="direction-badge ' + positionDirBadge(p.side) + '">' + p.side + '</span></td>' +
      '<td>' + (p.symbol || (view.symbol || '—')) + '</td>' +
      '<td class="mono">' + p.quantity_lots + '</td>' +
      '<td class="mono">' + Number(p.entry_price).toFixed(5) + '</td>' +
      '<td class="mono">' + (p.stop_loss == null ? '—' : Number(p.stop_loss).toFixed(5)) + '</td>' +
      '<td class="mono">' + (p.take_profit == null ? '—' : Number(p.take_profit).toFixed(5)) + '</td>' +
      '<td class="mono">' + p.position_id.slice(0, 8) + '</td>' +
      '<td>' + exitCell + '</td>' +
      '</tr>'
    );
  });
  tbody.innerHTML = rows.join('') || '<tr><td colspan="8" class="empty-note">No positions at this point</td></tr>';
}

function renderOrders(view) {
  var tbody = document.getElementById('orders-body');
  if (!tbody) return;
  var ordered = [];
  view.orders.forEach(function (o) { ordered.push(o); });
  ordered.sort(function (a, b) { return a.seq - b.seq; });
  var html = '';
  ordered.forEach(function (o) {
    var priceCell = o.executed_price != null ? Number(o.executed_price).toFixed(5)
      : (o.order_type === 'market' ? '—' : 'pending');
    var stateCell = '<span class="order-state order-' + o.state + '">' + o.state + '</span>';
    if (o.state === 'rejected') {
      stateCell += '<div class="reject-detail">' + (o.category || '') + (o.reason ? ': ' + o.reason : '') + '</div>';
    }
    html += '<tr>' +
      '<td class="mono">' + o.seq + '</td>' +
      '<td>' + o.type + '</td>' +
      '<td>' + o.side + '</td>' +
      '<td class="mono">' + o.quantity_lots + '</td>' +
      '<td class="mono">' + o.created_bar + '</td>' +
      '<td class="mono">' + priceCell + '</td>' +
      '<td>' + stateCell + '</td>' +
      '</tr>';
  });
  tbody.innerHTML = html || '<tr><td colspan="7" class="empty-note">No orders at this point</td></tr>';
}

function shortPayload(e) {
  var keys = Object.keys(e).filter(function (k) {
    return k !== 'type' && k !== 'event_seq' && k !== 'timestamp' && k !== 'position_id' && k !== 'order_seq';
  });
  var parts = keys.map(function (k) {
    var v = e[k];
    if (typeof v === 'number') v = Number(v).toPrecision(8);
    if (v === null) v = 'null';
    return k + '=' + v;
  });
  var detail = parts.slice(0, 6).join(' ');
  return detail ? ' · ' + detail : '';
}

function renderBarEvents(k) {
  var list = document.getElementById('bar-events');
  if (!list) return;
  var events = [];
  if (k >= 0 && replayIndex) events = replayIndex.bars[k] || [];
  var html = '';
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    html += '<div class="canon-event" data-seq="' + e.event_seq + '">' +
      '<span class="ce-seq mono">#' + e.event_seq + '</span>' +
      '<span class="ce-type">' + e.type + '</span>' +
      '<span class="ce-detail">' + shortPayload(e) + '</span>' +
      '</div>';
  }
  if (!html) {
    html = '<div class="empty-note">No canonical events on this bar' +
      (k < 0 ? ' — press Play or Step to begin' : '') + '</div>';
  }
  list.innerHTML = html;
  var decisionEl = document.getElementById('bar-decision');
  if (decisionEl) {
    var count = currentView ? currentView.decisionsByBar[k] : undefined;
    decisionEl.textContent = count == null ? '—' : (count + (count === 1 ? ' signal' : ' signals'));
  }
}

function renderTradeLog(view) {
  var tbody = document.getElementById('trade-log-body');
  if (!tbody) return;
  var rows = '';
  for (var i = 0; i < view.closedTrades.length; i++) {
    var t = view.closedTrades[i];
    var entryTime = t.opened_bar != null && replayBars[t.opened_bar]
      ? new Date(toUnix(replayBars[t.opened_bar].time) * 1000).toISOString().slice(0, 16).replace('T', ' ')
      : '-';
    var entryTimeUnix = t.opened_bar != null && replayBars[t.opened_bar] ? toUnix(replayBars[t.opened_bar].time) : '';
    var exitTimeUnix = t.closed_bar != null && replayBars[t.closed_bar] ? toUnix(replayBars[t.closed_bar].time) : '';
    var entryPrice = Number(t.entry_price).toFixed(5);
    var sl = t.stop_loss == null ? '-' : Number(t.stop_loss).toFixed(5);
    var tp = t.take_profit == null ? '-' : Number(t.take_profit).toFixed(5);
    var reason = exitReasonLabel[t.exit_reason] || t.exit_reason;
    var pnl = t.net_realized_pnl;
    rows +=
      '<tr data-entry-time="' + entryTimeUnix + '" data-exit-time="' + exitTimeUnix + '">' +
      '<td class="trade-number">' + (i + 1) + '</td>' +
      '<td><span class="direction-badge ' + positionDirBadge(t.side) + '">' + t.side + '</span></td>' +
      '<td>' + entryTime + '</td>' +
      '<td>' + entryPrice + '</td>' +
      '<td>' + Number(t.exit_price).toFixed(5) + '</td>' +
      '<td>' + sl + '</td>' +
      '<td>' + tp + '</td>' +
      '<td class="trade-reason">' + reason + '</td>' +
      '<td class="' + (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') + '">' +
        (pnl >= 0 ? '+' : '') + '$' + Number(pnl).toFixed(2) + '</td>' +
      '</tr>';
  }
  tbody.innerHTML = rows || '<tr><td colspan="9" class="empty-note">No closed trades yet</td></tr>';
}

function renderCurves(endIdx, view) {
  equityData = [];
  balanceData = [];
  for (var i = 0; i <= endIdx && i < replayEvents.length; i++) {
    var e = replayEvents[i];
    if (e.type === 'portfolio_snapshot') {
      var t = markerBarTime(e.bar_index);
      if (t === null) continue;
      equityData.push({ time: t, value: e.equity });
      balanceData.push({ time: t, value: e.balance });
    }
  }
  equitySeries.setData(equityData);
  if (balanceSeries) balanceSeries.setData(balanceData);
}

// ── Metrics + failure presentation ─────────────

function renderMetrics(report) {
  lastMetricsReport = report;
  var grid = document.getElementById('metrics-grid');
  if (!grid || !report) return;

  function card(label, value, cls, detail, action) {
    var tag = action ? 'button' : 'div';
    return '<' + tag + (action ? ' type="button" onclick="' + action + '"' : '') +
      ' class="metric-card ' + (cls || 'neutral') + (action ? ' inspectable' : '') + '">' +
      '<div class="metric-label">' + label + '</div>' +
      '<div class="metric-value ' + (cls || 'neutral') + '">' + value + '</div>' +
      (detail ? '<div class="metric-detail">' + detail + '</div>' : '') +
      '</' + tag + '>';
  }
  function group(title, description, cards, extraClass) {
    return '<section class="metric-group ' + (extraClass || '') + '">' +
      '<div class="metric-group-heading"><div><h3>' + title + '</h3><p>' + description + '</p></div></div>' +
      '<div class="metric-group-cards">' + cards + '</div></section>';
  }

  var r = report;
  var html = '';
  html += group('Performance', 'Return quality and risk-adjusted outcome',
    card('Total Return', fmtNum(r.total_return_pct, 2) + '%', r.total_return_pct >= 0 ? 'positive' : 'negative') +
    card('Annualised Return', r.annualised_return_pct != null ? fmtNum(r.annualised_return_pct, 2) + '%' : 'N/A', r.annualised_return_pct != null ? (r.annualised_return_pct >= 0 ? 'positive' : 'negative') : 'neutral') +
    card('Sharpe Ratio', r.sharpe_ratio !== null ? fmtNum(r.sharpe_ratio, 2) : 'N/A', 'neutral') +
    card('Calmar Ratio', r.calmar_ratio !== null ? fmtNum(r.calmar_ratio, 2) : 'N/A', 'neutral'), 'performance-group');
  html += group('Risk', 'Drawdown and return durability',
    card('Max Drawdown', fmtNum(r.max_drawdown_pct, 2) + '%', 'negative', 'Inspect evidence across charts and trades', 'inspectMaxDrawdown()') +
    card('Current Drawdown', r.current_drawdown_pct != null ? fmtNum(r.current_drawdown_pct, 2) + '%' : 'N/A', 'negative') +
    card('Profit Factor', fmtNum(r.profit_factor, 2), 'neutral'), 'risk-group');
  html += group('Trade Statistics', 'Execution outcomes across closed positions',
    card('Win Rate', fmtNum(r.win_rate_pct, 1) + '%', 'neutral') +
    card('Total Trades', r.total_trades, 'neutral') +
    card('Winning Trades', r.winning_trades, 'positive') +
    card('Losing Trades', r.losing_trades, 'negative') +
    card('Avg Win', '$' + fmtNum(r.avg_win, 2), 'positive') +
    card('Avg Loss', '$' + fmtNum(r.avg_loss, 2), 'negative') +
    card('Expectancy', '$' + fmtNum(r.expectancy, 2), r.expectancy >= 0 ? 'positive' : 'negative'), 'trades-group');
  grid.innerHTML = html;
  drawDrawdownHighlight(r);
}

function showNotice(message) {
  var banner = document.getElementById('run-banner');
  if (!banner) return;
  banner.style.display = 'block';
  banner.innerHTML = '<div class="run-banner-icon" aria-hidden="true">i</div>' +
    '<div><strong>Dataset not available</strong><span>' + escapeHtml(message) + '</span></div>';
}

function showRunFailed(category, message, barIndex) {
  var banner = document.getElementById('run-banner');
  if (!banner) return;
  banner.style.display = 'block';
  banner.innerHTML =
    '<div class="run-banner-icon" aria-hidden="true">!</div>' +
    '<div><strong>Run failed' + (barIndex != null ? ' after bar ' + barIndex : '') + '</strong>' +
    '<span>' + escapeHtml(String(category || '')) + (message ? ' — ' + escapeHtml(String(message)) : '') + '</span></div>';
  document.getElementById('btn-play').disabled = true;
  document.getElementById('btn-step').disabled = true;
}

function hideRunFailed() {
  var banner = document.getElementById('run-banner');
  if (!banner) return;
  banner.style.display = 'none';
  document.getElementById('btn-play').disabled = false;
  document.getElementById('btn-step').disabled = false;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function setPlayButton(state) {
  var btn = document.getElementById('btn-play');
  if (state === 'playing') {
    btn.textContent = '⏸ Pause'; btn.classList.add('active');
  } else if (state === 'done') {
    btn.textContent = '▶ Play'; btn.classList.remove('active');
    btn.disabled = true;
  } else {
    btn.textContent = '▶ Play'; btn.classList.remove('active');
  }
}
