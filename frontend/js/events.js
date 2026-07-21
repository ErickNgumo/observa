// ══════════════════════════════════════════════
// EVENT LOADING + PROCESSING
// Fetches the event log from the server and
// dispatches each event to its handler as the
// replay plays through it.
// ══════════════════════════════════════════════

function loadEvents() {
  return fetch('/api/events')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      allEvents = data;
      totalBars = allEvents.filter(function(e) {
        return e.event_type === 'BarReceived';
      }).length;
      document.getElementById('stat-progress').textContent =
        'Bar 0 / ' + totalBars;
      console.log('Loaded ' + allEvents.length + ' events, ' + totalBars + ' bars');
    })
    .catch(function(err) {
      console.error('Failed to load events:', err);
    });
}

// Routes a single event to the correct handler
// based on its event_type field.
function processEvent(ev) {
  switch (ev.event_type) {
    case 'BarReceived':       handleBar(ev);      break;
    case 'DrawingsEmitted':   handleDrawings(ev); break;
    case 'PositionOpened':    handleOpened(ev);   break;
    case 'PositionClosed':    handleClosed(ev);   break;
    case 'PortfolioSnapshot': handleSnapshot(ev); break;
    case 'MetricsReport':     handleMetrics(ev);  break;
  }
}

// ── BarReceived ──────────────────────────────
function handleBar(ev) {
  var t = toUnix(ev.timestamp);

  candleData.push({
    time:  t,
    open:  ev.open,
    high:  ev.high,
    low:   ev.low,
    close: ev.close
  });
  candleSeries.setData(candleData);

  if (ev.ema_fast !== null && ev.ema_fast !== undefined) {
    fastEmaData.push({ time: t, value: ev.ema_fast });
    fastEmaSeries.setData(fastEmaData);
  }
  if (ev.ema_slow !== null && ev.ema_slow !== undefined) {
    slowEmaData.push({ time: t, value: ev.ema_slow });
    slowEmaSeries.setData(slowEmaData);
  }

  barsDrawn++;
  var pct = totalBars > 0 ? (barsDrawn / totalBars) * 100 : 0;
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('stat-progress').textContent =
    'Bar ' + barsDrawn + ' / ' + totalBars;

  // Keep the latest bar visible as replay progresses
  chart.timeScale().scrollToPosition(0, false);
}

// ── PositionOpened ───────────────────────────
function handleOpened(ev) {
  openTrade = {
    direction:  ev.direction,
    entryPrice: ev.entry_price,
    entryTime:  toUnix(ev.timestamp),
    sl:         ev.sl,
    tp:         ev.tp
  };

  tradeMarkers.push({
    time:     toUnix(ev.timestamp),
    position: ev.direction === 'Buy' ? 'belowBar' : 'aboveBar',
    color:    ev.direction === 'Buy' ? '#3fb950' : '#f85149',
    shape:    ev.direction === 'Buy' ? 'arrowUp' : 'arrowDown',
    text:     (ev.direction === 'Buy' ? 'B' : 'S') +
              ' @ ' + Number(ev.entry_price).toFixed(5)
  });
  refreshMarkers();
}

// ── PositionClosed ───────────────────────────
function handleClosed(ev) {
  tradeCount++;
  var pnl = ev.pnl;

  tradeMarkers.push({
    time:     toUnix(ev.timestamp),
    position: ev.direction === 'Buy' ? 'aboveBar' : 'belowBar',
    color:    pnl >= 0 ? '#3fb950' : '#f85149',
    shape:    'circle',
    text:     (pnl >= 0 ? '+' : '') + Math.round(pnl)
  });
  refreshMarkers();

  if (showLines && openTrade) {
    var LC   = LightweightCharts;
    var line = chart.addSeries(LC.LineSeries, {
      color:                  pnl >= 0
                                ? 'rgba(63,185,80,0.5)'
                                : 'rgba(248,81,73,0.5)',
      lineWidth:              1,
      lineStyle:              LC.LineStyle.Dashed,
      priceLineVisible:       false,
      lastValueVisible:       false,
      crosshairMarkerVisible: false
    });
    line.setData([
      { time: openTrade.entryTime,  value: openTrade.entryPrice },
      { time: toUnix(ev.timestamp), value: ev.exit_price }
    ]);
    tradeLines.push(line);
  }

  addTradeRow(ev, openTrade);
  document.getElementById('stat-trades').textContent = tradeCount;
  openTrade = null;
}

// ── PortfolioSnapshot ────────────────────────
function handleSnapshot(ev) {
  var bal = ev.balance;
  var pnl = ev.realised_pnl;

  document.getElementById('stat-balance').textContent = fmtNum(bal, 2);

  var pnlEl = document.getElementById('stat-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + fmtNum(pnl, 2);
  pnlEl.style.color = pnl >= 0 ? '#3fb950' : '#f85149';

  if (candleData.length > 0) {
    var t = candleData[candleData.length - 1].time;
    if (equityData.length === 0 ||
        equityData[equityData.length - 1].time !== t) {
      equityData.push({ time: t, value: ev.equity });
      equitySeries.setData(equityData);
    }
  }
}

// Indicator Drawing

function handleDrawings(ev) {
  if (!ev.drawings || ev.drawings.length === 0) return;

  ev.drawings.forEach(function(d) {
    var action = d.action || 'add';

    if (action === 'remove') {
      removeDrawing(d.id);
      return;
    }

    if (action === 'update') {
      removeDrawing(d.id);
      // Fall through to add the updated version
    }

    // Add the drawing
    addDrawing(d);
  });
}

function addDrawing(d) {
  var LC = LightweightCharts;
  var series = null;

  switch (d.type) {

    case 'rectangle': {
      // Draw as two line series — top and bottom edges
      // with a filled area between them using two series
      var topSeries = chart.addSeries(LC.LineSeries, {
        color:            d.border || d.color,
        lineWidth:        1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      var botSeries = chart.addSeries(LC.LineSeries, {
        color:            d.border || d.color,
        lineWidth:        1,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      var t1 = toUnix(d.time_start);
      var t2 = d.time_end
        ? toUnix(d.time_end)
        : candleData.length > 0
          ? candleData[candleData.length - 1].time
          : t1;

      topSeries.setData([
        { time: t1, value: d.price_top },
        { time: t2, value: d.price_top },
      ]);
      botSeries.setData([
        { time: t1, value: d.price_bot },
        { time: t2, value: d.price_bot },
      ]);

      activeDrawings[d.id] = [topSeries, botSeries];
      break;
    }

    case 'hline': {
      series = chart.addSeries(LC.LineSeries, {
        color:            d.color,
        lineWidth:        d.width || 1,
        lineStyle:        lineStyleCode(d.style),
        priceLineVisible: false,
        lastValueVisible: false,
      });
      var t = toUnix(d.time);
      var endT = candleData.length > 0
        ? candleData[candleData.length - 1].time
        : t;
      series.setData([
        { time: t,    value: d.price },
        { time: endT, value: d.price },
      ]);
      activeDrawings[d.id] = [series];
      break;
    }

    case 'line': {
      series = chart.addSeries(LC.LineSeries, {
        color:            d.color,
        lineWidth:        d.width || 1,
        lineStyle:        lineStyleCode(d.style),
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData([
        { time: toUnix(d.x1), value: d.y1 },
        { time: toUnix(d.x2), value: d.y2 },
      ]);
      activeDrawings[d.id] = [series];
      break;
    }

    case 'label': {
      // Labels are markers on the main candlestick series
      var labelMarker = {
        time:     toUnix(d.time),
        position: d.position === 'below' ? 'belowBar' : 'aboveBar',
        color:    d.color || '#e6edf3',
        shape:    'circle',
        text:     d.text,
      };
      tradeMarkers.push(labelMarker);
      refreshMarkers();
      // Store the marker index for potential removal
      activeDrawings[d.id] = {
        type:   'label',
        marker: labelMarker,
      };
      break;
    }

    case 'region': {
      // Region — shaded vertical band
      // Implemented as a very wide rectangle at
      // the price extremes of the current chart
      series = chart.addSeries(LC.LineSeries, {
        color:            d.color,
        lineWidth:        1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      // We use a transparent line — the visual effect
      // comes from the background color
      // A proper region needs a custom primitive in v5
      // For now we mark with vertical lines at start/end
      var t1 = toUnix(d.time_start);
      var t2 = toUnix(d.time_end);
      LC.createSeriesMarkers(candleSeries, [
        {
          time:     t1,
          position: 'aboveBar',
          color:    d.color.slice(0, 7),
          shape:    'arrowDown',
          text:     d.label || '',
        },
        {
          time:     t2,
          position: 'aboveBar',
          color:    d.color.slice(0, 7),
          shape:    'arrowDown',
          text:     '',
        },
      ]);
      activeDrawings[d.id] = [series];
      break;
    }

    case 'bar_color': {
      // Store bar color overrides — applied on next render
      if (!window._barColors) window._barColors = {};
      window._barColors[d.time] = d.color;
      activeDrawings[d.id] = { type: 'bar_color', time: d.time };
      break;
    }
  }
}

function removeDrawing(id) {
  var drawing = activeDrawings[id];
  if (!drawing) return;

  if (Array.isArray(drawing)) {
    drawing.forEach(function(s) { chart.removeSeries(s); });
  } else if (drawing.type === 'label') {
    var idx = tradeMarkers.indexOf(drawing.marker);
    if (idx !== -1) {
      tradeMarkers.splice(idx, 1);
      refreshMarkers();
    }
  } else if (drawing.type === 'bar_color') {
    if (window._barColors) {
      delete window._barColors[drawing.time];
    }
  }

  delete activeDrawings[id];
}

function lineStyleCode(style) {
  var LC = LightweightCharts;
  switch (style) {
    case 'dashed': return LC.LineStyle.Dashed;
    case 'dotted': return LC.LineStyle.Dotted;
    default:       return LC.LineStyle.Solid;
  }
}

// ── MetricsReport ────────────────────────────
function handleMetrics(ev) {
  var r = ev.report;
  lastMetricsReport = r;

  var grid = document.getElementById('metrics-grid');

  function card(label, value, cls) {
    return '<div class="metric-card">' +
      '<div class="metric-label">' + label + '</div>' +
      '<div class="metric-value ' + (cls || 'neutral') + '">' + value + '</div>' +
      '</div>';
  }

  var html = '';
  html += card('Total Return', fmtNum(r.total_return_pct, 2) + '%',
                r.total_return_pct >= 0 ? 'positive' : 'negative');
  html += card('Max Drawdown', fmtNum(r.max_drawdown_pct, 2) + '%', 'negative');
  html += card('Sharpe Ratio',
                r.sharpe_ratio !== null ? fmtNum(r.sharpe_ratio, 2) : 'N/A', 'neutral');
  html += card('Calmar Ratio',
                r.calmar_ratio !== null ? fmtNum(r.calmar_ratio, 2) : 'N/A', 'neutral');
  html += card('Win Rate', fmtNum(r.win_rate_pct, 1) + '%', 'neutral');
  html += card('Profit Factor', fmtNum(r.profit_factor, 2), 'neutral');
  html += card('Total Trades', r.total_trades, 'neutral');
  html += card('Winning Trades', r.winning_trades, 'positive');
  html += card('Losing Trades', r.losing_trades, 'negative');
  html += card('Avg Win', '$' + fmtNum(r.avg_win, 2), 'positive');
  html += card('Avg Loss', '$' + fmtNum(r.avg_loss, 2), 'negative');
  html += card('Expectancy', '$' + fmtNum(r.expectancy, 2),
                r.expectancy >= 0 ? 'positive' : 'negative');

  grid.innerHTML = html;

  // Now that the equity curve is complete, draw the
  // drawdown highlight on top of it.
  drawDrawdownHighlight(r);
}


// ── Trade log row builder ────────────────────
function addTradeRow(closeEv, entry) {
  var tbody = document.getElementById('trade-log-body');
  var pnl   = closeEv.pnl;
  var row   = document.createElement('tr');

  var entryTime  = entry
    ? new Date(entry.entryTime * 1000).toISOString().slice(0, 16).replace('T', ' ')
    : '-';
  var entryPrice = entry ? Number(entry.entryPrice).toFixed(5) : '-';
  var sl = (entry && entry.sl != null) ? Number(entry.sl).toFixed(5) : '-';
  var tp = (entry && entry.tp != null) ? Number(entry.tp).toFixed(5) : '-';

  var dir = closeEv.direction;
  row.innerHTML =
    '<td>' + tradeCount + '</td>' +
    '<td style="color:' + (dir === 'Buy' ? '#3fb950' : '#f85149') + '">' + dir + '</td>' +
    '<td>' + entryTime + '</td>' +
    '<td>' + entryPrice + '</td>' +
    '<td>' + Number(closeEv.exit_price).toFixed(5) + '</td>' +
    '<td>' + sl + '</td>' +
    '<td>' + tp + '</td>' +
    '<td>' + closeEv.exit_reason + '</td>' +
    '<td class="' + (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') + '">' +
      (pnl >= 0 ? '+' : '') + '$' + Number(pnl).toFixed(2) +
    '</td>';
  tbody.appendChild(row);
}