// ══════════════════════════════════════════════
// METRICS PANEL (presentation only)
// Renders the canonical metrics report produced by the Rust engine
// (metrics.json). Nothing here derives a financial number: values, reasons,
// sample sizes and assumptions all come from the report; the trade chart
// plots canonical position_closed P&L values as recorded.
// Handles schema 2 (Observa ≥ 0.2) and schema 1 (≤ 0.1.6) reports.
// ══════════════════════════════════════════════

var metricHelp = {
  net_profit: 'Final equity minus the starting balance, in account currency.',
  total_return_pct: 'Final equity relative to the starting balance over the whole run. Not annualised.',
  annualised_return_pct: 'Compound annual growth rate. Only shown when the run covers at least one year and the bars per year are known.',
  unrealised_pnl_end: 'Mark-to-market P&L of positions still open at the end (included in final equity).',
  annualised_volatility_pct: 'Standard deviation of per-bar equity returns, scaled by √(bars per year).',
  sharpe_ratio: 'Mean per-bar return ÷ its standard deviation × √(bars per year). Risk-free rate 0. Short samples are noisy.',
  sortino_ratio: 'Like Sharpe, but divides by downside deviation (negative returns only).',
  calmar_ratio: 'Annualised return ÷ maximum drawdown.',
  max_drawdown_pct: 'Largest fall from a running equity peak (starting balance included), at bar closes. Click to inspect.',
  max_drawdown_amount: 'The same drawdown in account currency.',
  longest_drawdown_bars: 'Longest stretch of consecutive bars spent below a previous equity peak.',
  current_drawdown_pct: 'Distance below the running peak at the last bar.',
  total_trades: 'Closed positions. Positions still open at the end are not counted.',
  win_rate_pct: 'Share of closed trades with positive net P&L (after commission).',
  avg_win: 'Average net P&L of winning closed trades.',
  avg_loss: 'Average net loss of losing closed trades (shown as a positive amount).',
  payoff_ratio: 'Average win ÷ average loss.',
  profit_factor: 'Gross profit ÷ gross loss of closed trades.',
  expectancy: 'Average net P&L per closed trade.',
  largest_win: 'Best single closed trade.',
  largest_loss: 'Worst single closed trade (positive amount).',
  max_consecutive_losses: 'Longest run of losing closed trades, in closing order.',
  avg_holding_bars: 'Average bars between a position opening and closing.',
  time_in_market_pct: 'Share of bars that ended with at least one open position.',
  max_gross_leverage: 'Largest gross position value ÷ equity at a bar close.',
  commission_cost: 'Commission charged by the configured cost model.',
  spread_cost: 'Half-spread paid on each fill (entries, exits and SL/TP), in account currency.',
  slippage_cost: 'Adverse slippage applied to fills, in account currency.',
  total_costs: 'Commission + spread + slippage. Financing / swap costs are not modelled.'
};

function metricsCurrency(r) {
  return (r.assumptions && r.assumptions.currency) || '';
}

function metricText(r, key, kind) {
  var v = r[key];
  if (v === null || v === undefined) return null;
  if (kind !== 'text') {
    v = Number(v);
    if (!Number.isFinite(v)) return null;  // never render a non-number from a report
  }
  var cur = metricsCurrency(r);
  switch (kind) {
    case 'pct': return fmtNum(v, 2) + '%';
    case 'ratio': return fmtNum(v, 2);
    case 'money': return (v < 0 ? '−' : '') + fmtNum(Math.abs(v), 2) + (cur ? ' ' + cur : '');
    case 'signed-money': return (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v), 2) + (cur ? ' ' + cur : '');
    case 'times': return fmtNum(v, 2) + '×';
    case 'bars': return fmtNum(v, v % 1 === 0 ? 0 : 1) + ' bars';
    case 'int': return fmtNum(v, 0);
    default: return String(v);
  }
}

function metricTone(r, key, kind) {
  var v = r[key];
  if (v === null || v === undefined) return 'neutral';
  if (key === 'max_drawdown_pct' || key === 'max_drawdown_amount' || key === 'current_drawdown_pct' ||
      key === 'avg_loss' || key === 'largest_loss' || kind === 'cost') return v > 0 ? 'negative' : 'neutral';
  if (key === 'net_profit' || key === 'total_return_pct' || key === 'annualised_return_pct' ||
      key === 'expectancy' || key === 'unrealised_pnl_end' || key === 'sharpe_ratio' || key === 'sortino_ratio' ||
      key === 'calmar_ratio') return v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';
  return 'neutral';
}

function metricCard(r, opts) {
  var key = opts.key, kind = opts.kind;
  var text = metricText(r, key, kind === 'cost' ? 'money' : kind);
  var unavailable = text === null;
  var reason = unavailable ? ((r.unavailable && r.unavailable[key]) || 'Not recorded for this run.') : '';
  reason = String(reason);
  reason = reason.charAt(0).toUpperCase() + reason.slice(1);
  var tone = unavailable ? 'unavailable' : metricTone(r, key, kind);
  var tag = opts.action && !unavailable ? 'button' : 'div';
  var help = metricHelp[key] || '';
  var badge = opts.scope ? '<span class="metric-scope ' + opts.scope + '">' + (opts.scope === 'annual' ? 'Annualised' : 'Total') + '</span>' : '';
  return '<' + tag + (tag === 'button' ? ' type="button" onclick="' + opts.action + '"' : '') +
    ' class="metric-card ' + tone + (tag === 'button' ? ' inspectable' : '') + '" data-metric="' + key + '">' +
    '<div class="metric-label"><span>' + escapeHtml(opts.label) +
    (help ? ' <span class="info-tip" tabindex="0" role="img" aria-label="' + escapeHtml(help) + '" title="' + escapeHtml(help) + '">ⓘ</span>' : '') +
    '</span>' + badge + '</div>' +
    '<div class="metric-value ' + tone + '">' + (unavailable ? 'Unavailable' : escapeHtml(text)) + '</div>' +
    (unavailable
      ? '<div class="metric-detail metric-reason" title="' + escapeHtml(reason) + '">' + escapeHtml(reason) + '</div>'
      : (opts.detail ? '<div class="metric-detail">' + opts.detail + '</div>' : '')) +
    '</' + tag + '>';
}

function metricGroup(title, description, body, cls) {
  return '<section class="metric-group ' + (cls || '') + '">' +
    '<div class="metric-group-heading"><div><h3>' + title + '</h3><p>' + description + '</p></div></div>' +
    '<div class="metric-group-cards">' + body + '</div></section>';
}

function fmtDays(days) {
  if (days === null || days === undefined) return null;
  if (days >= 365) return fmtNum(days / 365.25, 1) + ' years';
  if (days >= 2) return fmtNum(days, 0) + ' days';
  return fmtNum(days * 24, 1) + ' hours';
}

function metricsSampleStrip(r) {
  var s = r.sample || {};
  var a = r.assumptions || {};
  var chips = [];
  if (s.bars != null) chips.push('<span class="sample-chip"><b>' + fmtNum(s.bars, 0) + '</b> bars</span>');
  var span = fmtDays(s.calendar_days);
  if (span) chips.push('<span class="sample-chip"><b>' + span + '</b> calendar span</span>');
  if (s.return_periods != null) chips.push('<span class="sample-chip"><b>' + fmtNum(s.return_periods, 0) + '</b> returns</span>');
  if (s.closed_trades != null) chips.push('<span class="sample-chip"><b>' + fmtNum(s.closed_trades, 0) + '</b> closed trades</span>');
  var annual = a.bars_per_year
    ? 'Annualised with <b>' + fmtNum(a.bars_per_year, 0) + '</b> bars/year' + (a.bars_per_year_source === 'interval_default' ? ' (default for ' + escapeHtml(a.interval || '') + ')' : ' (set explicitly)')
    : 'Not annualised';
  chips.push('<span class="sample-chip ' + (a.bars_per_year ? '' : 'warn') + '" title="' + escapeHtml(a.annualisation_note || '') + '">' + annual + '</span>');
  if (a.risk_free_rate != null) chips.push('<span class="sample-chip">Risk-free rate <b>' + fmtNum(a.risk_free_rate * 100, 0) + '%</b></span>');
  return '<div class="metrics-sample" aria-label="Sample and assumptions">' + chips.join('') + '</div>';
}

// Plots each closed trade's canonical net P&L (from position_closed events)
// as a bar, in closing order. Scaling only — no derived figures.
function tradeOutcomeChart(r) {
  var closed = (typeof replayEvents !== 'undefined' ? replayEvents : []).filter(function (e) {
    return e.type === 'position_closed' && Number.isFinite(Number(e.net_realized_pnl));
  });
  if (!closed.length) return '';
  var w = 600, h = 120, pad = 6, mid = h / 2;
  var max = closed.reduce(function (m, e) { return Math.max(m, Math.abs(Number(e.net_realized_pnl))); }, 0) || 1;
  var bw = (w - pad * 2) / closed.length;
  var barW = Math.max(0.6, bw * 0.78);
  // Two <path> elements (wins, losses) instead of one node per trade, so
  // runs with tens of thousands of trades stay fast.
  var win = [], loss = [];
  closed.forEach(function (e, i) {
    var v = Number(e.net_realized_pnl);
    var bh = Math.max(1, Math.abs(v) / max * (mid - pad));
    var x = (pad + i * bw).toFixed(2);
    var y = (v >= 0 ? mid - bh : mid).toFixed(2);
    (v >= 0 ? win : loss).push('M' + x + ' ' + y + 'h' + barW.toFixed(2) + 'v' + bh.toFixed(2) + 'h-' + barW.toFixed(2) + 'z');
  });
  return '<figure class="metrics-chart"><figcaption><span>Closed-trade outcomes</span><em>net P&amp;L per trade, in closing order · ' +
    fmtNum(closed.length, 0) + ' trades · largest bar ' + escapeHtml(metricText({ v: max, assumptions: r.assumptions }, 'v', 'money')) + '</em></figcaption>' +
    '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" role="img" aria-label="Net P&amp;L of each closed trade">' +
    '<line x1="0" x2="' + w + '" y1="' + mid + '" y2="' + mid + '" class="axis"/>' +
    '<path class="win" d="' + win.join('') + '"/><path class="loss" d="' + loss.join('') + '"/></svg></figure>';
}

// Stacked bar of the canonical cost components.
function costChart(r) {
  var parts = [['commission_cost', 'Commission'], ['spread_cost', 'Spread'], ['slippage_cost', 'Slippage']];
  var total = Number(r.total_costs);
  if (!Number.isFinite(total) || total <= 0) return '';
  var segs = parts.map(function (p) {
    var v = Number(r[p[0]]);
    if (!Number.isFinite(v) || v <= 0) return '';
    return '<span class="cost-seg ' + p[0] + '" style="flex:' + v + '" title="' + p[1] + ': ' + escapeHtml(metricText(r, p[0], 'money')) + '"></span>';
  }).join('');
  var legend = parts.map(function (p) {
    return '<span><i class="cost-dot ' + p[0] + '"></i>' + p[1] + ' ' + escapeHtml(metricText(r, p[0], 'money') || '—') + '</span>';
  }).join('');
  return '<figure class="metrics-chart cost-breakdown"><figcaption><span>Execution costs</span><em>' +
    escapeHtml(metricText(r, 'total_costs', 'money')) +
    (r.total_costs_pct_of_starting_balance != null ? ' · ' + fmtNum(r.total_costs_pct_of_starting_balance, 2) + '% of starting balance' : '') +
    '</em></figcaption><div class="cost-bar">' + segs + '</div><div class="cost-legend">' + legend + '</div></figure>';
}

function warningsNotice(r) {
  var w = Array.isArray(r.warnings) ? r.warnings.filter(function (x) { return typeof x === 'string' && x; }) : [];
  if (!w.length) return '';
  return '<div class="metrics-notice" role="note"><strong>Read with care</strong><ul>' +
    w.map(function (x) { return '<li>' + escapeHtml(x) + '</li>'; }).join('') + '</ul></div>';
}

function legacyNotice(r) {
  if ((r.metrics_schema_version || 1) >= 2) return '';
  return '<div class="metrics-notice">Recorded by Observa 0.1.6 or earlier: the annualisation factor was not recorded. Unless one was passed explicitly, annualised figures used 252 bars per year whatever the bar interval, so they may be mis-scaled for intraday data. Re-run with Observa 0.2 for annualisation-aware metrics.</div>';
}

function renderMetrics(report) {
  var grid = document.getElementById('metrics-grid');
  if (!grid || !report) return;
  // The report is fixed for a run: re-rendering it when replay reaches the
  // last bar would only repeat work (and is costly for very large runs).
  if (report === lastMetricsReport && grid.getAttribute('data-rendered') === '1') {
    drawDrawdownHighlight(report);
    return;
  }
  lastMetricsReport = report;
  var r = report;
  var legacy = (r.metrics_schema_version || 1) < 2;
  var cur = metricsCurrency(r);
  var trades = r.total_trades || 0;
  var dd = r.max_drawdown_pct > 0 ? 'inspectMaxDrawdown()' : null;
  var html = legacyNotice(r) + (legacy ? '' : metricsSampleStrip(r) + warningsNotice(r));

  html += metricGroup('Overview', 'Whole-run headline figures', [
    metricCard(r, { key: legacy ? 'total_return_pct' : 'net_profit', label: legacy ? 'Total Return' : 'Net Profit', kind: legacy ? 'pct' : 'signed-money', scope: 'total',
      detail: legacy ? null : escapeHtml(metricText(r, 'total_return_pct', 'pct') || '') + ' total return' }),
    metricCard(r, { key: 'max_drawdown_pct', label: 'Max Drawdown', kind: 'pct', action: dd,
      detail: r.max_drawdown_amount != null ? escapeHtml(metricText(r, 'max_drawdown_amount', 'money')) + (r.max_drawdown_recovered_at === null && r.max_drawdown_pct > 0 ? ' · not recovered' : '') : null }),
    metricCard(r, { key: 'sharpe_ratio', label: legacy ? 'Sharpe Ratio (legacy)' : 'Sharpe Ratio', kind: 'ratio', scope: 'annual' }),
    metricCard(r, { key: 'profit_factor', label: 'Profit Factor', kind: 'ratio' }),
    metricCard(r, { key: 'win_rate_pct', label: 'Win Rate', kind: 'pct', detail: trades ? fmtNum(r.winning_trades, 0) + ' of ' + fmtNum(trades, 0) + ' closed trades' : null }),
    legacy ? metricCard(r, { key: 'total_trades', label: 'Trades', kind: 'int' })
           : metricCard(r, { key: 'expectancy', label: 'Expectancy', kind: 'signed-money', detail: 'per closed trade' })
  ].join(''), 'primary-metrics');

  if (legacy) {
    html += metricGroup('Recorded metrics', 'As stored in this run (schema 1)', [
      metricCard(r, { key: 'annualised_return_pct', label: 'Annualised Return (legacy)', kind: 'pct', scope: 'annual' }),
      metricCard(r, { key: 'calmar_ratio', label: 'Calmar Ratio (legacy)', kind: 'ratio', scope: 'annual' }),
      metricCard(r, { key: 'current_drawdown_pct', label: 'Current Drawdown', kind: 'pct' }),
      metricCard(r, { key: 'expectancy', label: 'Expectancy', kind: 'signed-money' }),
      metricCard(r, { key: 'avg_win', label: 'Average Win', kind: 'money' }),
      metricCard(r, { key: 'avg_loss', label: 'Average Loss', kind: 'money' })
    ].join(''));
    grid.innerHTML = html;
    grid.setAttribute('data-rendered', '1');
    drawDrawdownHighlight(r);
    return;
  }

  html += metricGroup('Returns', 'Total figures cover the whole run; annualised figures need ≥ 1 year of data', [
    metricCard(r, { key: 'total_return_pct', label: 'Total Return', kind: 'pct', scope: 'total' }),
    metricCard(r, { key: 'annualised_return_pct', label: 'Annualised Return', kind: 'pct', scope: 'annual' }),
    metricCard(r, { key: 'unrealised_pnl_end', label: 'Unrealised P&L at End', kind: 'signed-money',
      detail: r.open_positions_remaining ? fmtNum(r.open_positions_remaining, 0) + ' position(s) still open' : 'No open positions' })
  ].join(''));

  html += metricGroup('Risk', 'Return variability and drawdowns, from end-of-bar equity', [
    metricCard(r, { key: 'annualised_volatility_pct', label: 'Volatility', kind: 'pct', scope: 'annual' }),
    metricCard(r, { key: 'sharpe_ratio', label: 'Sharpe Ratio', kind: 'ratio', scope: 'annual' }),
    metricCard(r, { key: 'sortino_ratio', label: 'Sortino Ratio', kind: 'ratio', scope: 'annual' }),
    metricCard(r, { key: 'calmar_ratio', label: 'Calmar Ratio', kind: 'ratio', scope: 'annual' }),
    metricCard(r, { key: 'longest_drawdown_bars', label: 'Longest Drawdown', kind: 'bars' }),
    metricCard(r, { key: 'current_drawdown_pct', label: 'Current Drawdown', kind: 'pct' })
  ].join(''));

  html += metricGroup('Exposure and costs', 'How much the strategy was in the market, and what execution cost' + (cur ? ' (' + escapeHtml(cur) + ')' : ''), [
    metricCard(r, { key: 'time_in_market_pct', label: 'Time in Market', kind: 'pct' }),
    metricCard(r, { key: 'max_gross_leverage', label: 'Max Gross Leverage', kind: 'times' }),
    metricCard(r, { key: 'total_costs', label: 'Total Costs', kind: 'cost',
      detail: r.total_costs_pct_of_starting_balance != null ? fmtNum(r.total_costs_pct_of_starting_balance, 2) + '% of starting balance' : null })
  ].join('') + costChart(r));

  if (trades === 0) {
    html += '<section class="metric-group"><div class="metric-group-heading"><div><h3>Trades</h3><p>Closed position outcomes</p></div></div>' +
      '<div class="empty-note">No closed trades in this run, so trade statistics are not defined.' +
      (r.open_positions_remaining ? ' ' + fmtNum(r.open_positions_remaining, 0) + ' position(s) were still open at the end.' : '') + '</div></section>';
  } else {
    html += metricGroup('Trades', fmtNum(trades, 0) + ' closed trades · ' + fmtNum(r.winning_trades, 0) + ' won · ' +
      fmtNum(r.losing_trades, 0) + ' lost' + (r.breakeven_trades ? ' · ' + fmtNum(r.breakeven_trades, 0) + ' break-even' : '') + ' · net of commission', [
      metricCard(r, { key: 'expectancy', label: 'Expectancy', kind: 'signed-money' }),
      metricCard(r, { key: 'avg_win', label: 'Average Win', kind: 'money' }),
      metricCard(r, { key: 'avg_loss', label: 'Average Loss', kind: 'money' }),
      metricCard(r, { key: 'payoff_ratio', label: 'Payoff Ratio', kind: 'ratio' }),
      metricCard(r, { key: 'largest_win', label: 'Largest Win', kind: 'money' }),
      metricCard(r, { key: 'largest_loss', label: 'Largest Loss', kind: 'money' }),
      metricCard(r, { key: 'max_consecutive_losses', label: 'Max Losing Streak', kind: 'int' }),
      metricCard(r, { key: 'avg_holding_bars', label: 'Average Holding', kind: 'bars' })
    ].join('') + tradeOutcomeChart(r), 'wide');
  }

  grid.innerHTML = html;
  grid.setAttribute('data-rendered', '1');
  drawDrawdownHighlight(r);
}
