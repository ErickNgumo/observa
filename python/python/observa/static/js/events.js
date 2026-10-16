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
      drawingBarTimes = replayBars.map(function (b) { return toUnix(b.time); });
      drawingState = null;
      lastDrawingBar = -2;
      if (totalBars === 0 && replayEvents.length > 0) {
        showNotice('The dataset for this run could not be recovered, so the ' +
          'candle chart is unavailable. Events, orders, positions and ' +
          'account state still replay below.');
      }
      document.getElementById("stat-pair").textContent = instrumentLabel(data.run);
      var started = replayEvents.find(function(e) { return e.type === "run_started"; });
      document.getElementById("run-identity").textContent = started && started.strategy_name || "Strategy research";
      if (data.run && Number.isInteger(data.run.price_decimals)) {
        var precision = Math.max(0, Math.min(12, data.run.price_decimals));
        candleSeries.applyOptions({ priceFormat: { type: 'price', precision: precision, minMove: Math.pow(10, -precision) } });
      }
      if (data.metrics) renderMetrics(data.metrics);
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
  k = Math.max(-1, k);
  var heldRange = !chartFollowing ? chart.timeScale().getVisibleLogicalRange() : null;
  if (activeInvestigation) clearInvestigation();
  clearInvestigationOutlines();
  delete investigations["max-drawdown"];
  currentBar = k;

  var endIdx = endEventOfBar(k);
  var view = ObservaReplay.stateThrough(replayEvents, endIdx);
  if (payload.run && payload.run.symbol) view.symbol = payload.run.symbol;
  currentView = view;

  // Finished only when we processed through a run_completed / run_failed tail.
  finished = (k === maxK) && (!!view.completed || !!view.failed);

  // Annotation state is folded before candles so bar colours apply, and
  // applied after candles so right-extending zones see the current bar.
  var annotationsIncremental = foldAnnotations(k);
  renderCandles(k, view);
  applyAnnotations(annotationsIncremental);
  renderMarkers(endIdx);
  renderAccount(view);
  renderPositions(view);
  renderOrders(view);
  renderBarEvents(k);
  renderTradeLog(view);
  renderCurves(endIdx, view);
  if (payload.metrics) drawDrawdownHighlight(payload.metrics);
  updateProgressLabel();

  if (view.failed) {
    showRunFailed(view.failed.category, view.failed.message, k);
  } else if (view.completed && finished) {
    hideRunFailed();
    if (payload.metrics) renderMetrics(payload.metrics);
    setPlayButton('done');
  }
  var drawdownButton = document.querySelector('[onclick="inspectMaxDrawdown()"]');
  if (drawdownButton) {
    drawdownButton.disabled = !investigations['max-drawdown'];
    drawdownButton.title = drawdownButton.disabled ? 'Advance replay through the drawdown period to inspect it.' : conceptHelp['Max Drawdown'];
  }
  if (heldRange) chart.timeScale().setVisibleLogicalRange(heldRange);
  else followReplayChart();
  document.getElementById("btn-play").disabled = finished || maxK < 0;
  document.getElementById("btn-prev").disabled = k < 0;
  document.getElementById("btn-step").disabled = finished;
  document.getElementById("btn-end").disabled = finished;
  document.getElementById("inspector-bar").textContent = k < 0 ? "· before replay" : "· bar " + (k + 1) + " / " + totalBars;
}

function renderCandles(k, view) {
  candleData = [];
  for (var i = 0; i <= k && i < replayBars.length; i++) {
    var b = replayBars[i];
    var point = {
      time: toUnix(b.time), open: b.open, high: b.high, low: b.low, close: b.close
    };
    if (drawingState && drawingState.barColors[point.time]) {
      point.color = drawingState.barColors[point.time];
    }
    candleData.push(point);
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
  // Strategy markers (OBS-AI-02) are a separate layer merged in here.
  // Canonical execution markers are never replaced or hidden.
  var strategyMarkers = drawingMarkersFor(drawingState);
  for (var m = 0; m < strategyMarkers.length; m++) tradeMarkers.push(strategyMarkers[m]);
  refreshMarkers();
}

// ── Strategy annotations (OBS-AI-02) ───────────

var lastDrawingBar = -2;

/** Folds the canonical `drawings` array up to bar `k`; returns whether the
 *  fold was incremental (forward step) so series can use `update()`. */
function foldAnnotations(k) {
  if (!payload) { drawingState = null; lastDrawingBar = k; return false; }
  var perBar = payload.drawings || [];
  var incremental = !!(drawingState && k === lastDrawingBar + 1);
  if (incremental) {
    ObservaDrawings.applyInstructions(drawingState, perBar[k] || [], k, drawingBarTimes[k]);
  } else {
    drawingState = ObservaDrawings.fold(perBar, k, drawingBarTimes);
  }
  lastDrawingBar = k;
  return incremental;
}

function applyAnnotations(incremental) {
  applyDrawingState(drawingState, { incremental: !!incremental });
  renderSeriesLegend(drawingState);
}

/** Full re-render of the annotation layer (used by the Annotations toggle). */
function drawAnnotations(k, force) {
  var incremental = force ? false : foldAnnotations(k);
  applyAnnotations(incremental);
  // Strategy markers live in the marker layer, not the series/primitives layer,
  // so the toggle must refresh it too — otherwise marker visibility lags until
  // the next playback step or seek. Canonical execution markers are unaffected:
  // renderMarkers rebuilds them from canonical events and only merges the
  // annotation markers through drawingMarkersFor(state).
  renderMarkers(endEventOfBar(k));
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
    return '<div class="account-figure' + (cls ? ' ' + cls : '') + '"><span>' + helpLabel(label) + '</span><strong>' + value + '</strong></div>';
  }
  if (!a) {
    html = fig('Balance', '—') + fig('Equity', '—') + fig('Used margin', '—') + fig('Free margin', '—') + fig('Unrealised P&L', '—') + fig('Realised P&L', '—');
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
      '<tr tabindex="0" class="' + (p.open ? 'row-open' : 'row-closed') + '">' +
      '<td><span class="direction-badge ' + positionDirBadge(p.side) + '">' + p.side + '</span></td>' +
      '<td>' + escapeHtml(p.symbol || (view.symbol || '—')) + '</td>' +
      '<td class="mono">' + p.quantity_lots + '</td>' +
      '<td class="mono">' + Number(p.entry_price).toFixed(5) + '</td>' +
      '<td class="mono">' + (p.stop_loss == null ? '—' : Number(p.stop_loss).toFixed(5)) + '</td>' +
      '<td class="mono">' + (p.take_profit == null ? '—' : Number(p.take_profit).toFixed(5)) + '</td>' +
      '<td class="mono" title="' + escapeHtml(p.position_id) + '">' + escapeHtml(p.position_id.slice(0, 8)) + '</td>' +
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
      stateCell += '<div class="reject-detail">' + escapeHtml(o.category || '') + (o.reason ? ': ' + escapeHtml(o.reason) : '') + '</div>';
    }
    html += '<tr tabindex="0">' +
      '<td class="mono">' + o.seq + '</td>' +
      '<td>' + o.type + '</td>' +
      '<td>' + o.side + '</td>' +
      '<td class="mono">' + o.quantity_lots + '</td>' +
      '<td class="mono">' + (o.created_bar + 1) + '</td>' +
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
    if (typeof v === 'number') v = Number.isInteger(v) ? String(v) : fmtNum(v, 5);
    if (Array.isArray(v)) v = v.length + (v.length === 1 ? ' item' : ' items');
    else if (v && typeof v === 'object') v = 'expand for details';
    if (v === null) v = 'null';
    return k.replace(/_/g, ' ') + ': ' + v;
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
    html += '<details class="canon-event" data-seq="' + e.event_seq + '"><summary>' +
      '<span class="ce-seq mono">#' + e.event_seq + '</span>' +
      '<span class="ce-type">' + escapeHtml(e.type.replace(/_/g, ' ')) + '</span>' +
      '<span class="ce-detail">' + escapeHtml(shortPayload(e)) + '</span></summary>' +
      '<pre>' + escapeHtml(JSON.stringify(e, null, 2)) + '</pre></details>';
  }
  if (!html) {
    html = '<div class="empty-note">No canonical events on this bar' +
      (k < 0 ? ' — press Play or Step to begin' : '') + '</div>';
  }
  list.innerHTML = html;
  var reasons = [];
  events.forEach(function(e) {
    if (e.type === 'strategy_decision') (e.signals || []).forEach(function(signal) {
      if (signal.reason) reasons.push('<p><span class="status-pill">Signal ' + (signal.signal_index + 1) + '</span> ' + escapeHtml(signal.reason) + '</p>');
    });
  });
  document.getElementById('signal-reasons').innerHTML = reasons.join('') || '<span class="empty-note">No strategy reasons recorded at this bar.</span>';
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
    var exitTime = exitTimeUnix !== '' ? new Date(exitTimeUnix * 1000).toISOString().slice(0, 16).replace('T', ' ') : '—';
    var entryPrice = Number(t.entry_price).toFixed(5);
    var reason = exitReasonLabel[t.exit_reason] || t.exit_reason;
    var pnl = t.net_realized_pnl;
    rows +=
      '<tr tabindex="0" aria-selected="' + (selectedTradeId === t.position_id) + '" class="' + (selectedTradeId === t.position_id ? 'is-selected' : '') + '" data-trade-index="' + i + '" data-entry-time="' + entryTimeUnix + '" data-exit-time="' + exitTimeUnix + '">' +
      '<td class="trade-number">' + (i + 1) + '</td>' +
      '<td><span class="direction-badge ' + positionDirBadge(t.side) + '">' + t.side + '</span></td>' +
      '<td>' + entryTime + '</td>' +
      '<td>' + exitTime + '</td>' +
      '<td>' + entryPrice + '</td>' +
      '<td>' + Number(t.exit_price).toFixed(5) + '</td>' +

      '<td class="' + (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') + '">' +
        (pnl >= 0 ? '+' : '') + '$' + Number(pnl).toFixed(2) + '</td>' +
      '<td>' + tradeDuration(entryTimeUnix, exitTimeUnix) + '</td>' +
      '<td class="trade-reason" title="' + escapeHtml(reason) + '">' + escapeHtml(reason) + '</td>' +
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
  equityChart.timeScale().fitContent();
}

// ── Metrics + failure presentation ─────────────

// renderMetrics lives in js/metrics.js (presentation of the canonical report).

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
