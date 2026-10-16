// Metrics panel presentation (js/metrics.js) against real metrics reports.
//   node python/tests/metrics_panel.test.js
// The panel must show canonical values only, label total vs annualised
// figures, show sample sizes and assumptions, explain every unavailable
// metric, handle runs without trades, and keep older (schema 1) runs readable.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const dir = __dirname + '/../python/observa/static/js/';
const fx = __dirname + '/fixtures/metrics/';
const load = (name) => JSON.parse(fs.readFileSync(fx + name + '.json', 'utf8'));

function context(events) {
  const grid = { innerHTML: '', attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] || null; } };
  const ctx = {
    console, Number, Math, JSON, Object, String, Array,
    document: { getElementById: (id) => (id === 'metrics-grid' ? grid : null) },
    lastMetricsReport: null,
    replayEvents: events || [],
    drawDrawdownHighlight: () => {},
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(dir + 'helpers.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(dir + 'metrics.js', 'utf8'), ctx);
  return { ctx, grid };
}

let groups = 0;
function group(name, fn) { fn(); groups += 1; console.log('PASS ' + name); }

function noJunk(html) {
  for (const bad of ['NaN', 'undefined', 'Infinity', 'null%', '>null<']) {
    assert(!html.includes(bad), 'rendered "' + bad + '"');
  }
}

group('schema 2 with annualisation: values, scopes, sample and assumptions', () => {
  const r = load('v2_demo_annualised');
  const trades = [];
  for (let i = 0; i < r.total_trades; i++) trades.push({ type: 'position_closed', net_realized_pnl: i % 3 ? -50 : 120 });
  const { ctx, grid } = context(trades);
  ctx.renderMetrics(r);
  const h = grid.innerHTML;
  noJunk(h);
  assert(h.includes(ctx.fmtNum(r.sharpe_ratio, 2)), 'Sharpe value shown');
  assert(h.includes('Annualised</span>') && h.includes('Total</span>'), 'total vs annualised badges');
  assert(h.includes('24,192</b> bars/year'), 'annualisation factor shown');
  assert(h.includes(r.sample.bars.toLocaleString('en-US') + '</b> bars'), 'sample size shown');
  assert(h.includes('Unavailable') && h.includes('GIPS'), 'annualised return unavailable with its reason');
  assert(h.includes('Closed-trade outcomes') && (h.match(/z/g) || []).length >= r.total_trades &&
         (h.match(/M[0-9.]+ [0-9.]+h/g) || []).length === r.total_trades, 'one bar per closed trade');
  assert(h.includes('Execution costs') && h.includes(' USD'), 'cost breakdown in account currency');
  assert(h.includes('inspectMaxDrawdown()'), 'drawdown card is inspectable');
  assert(h.includes('Read with care') && h.includes('highly uncertain'), 'short-sample warning shown');
});

group('schema 2 without a factor: annualised metrics explain why', () => {
  const r = load('v2_demo_no_factor');
  const { ctx, grid } = context([]);
  ctx.renderMetrics(r);
  const h = grid.innerHTML;
  noJunk(h);
  assert(h.includes('Not annualised'), 'sample strip says not annualised');
  assert(h.includes('intraday interval'), 'reason mentions the intraday interval');
  for (const k of ['sharpe_ratio', 'sortino_ratio', 'annualised_volatility_pct']) {
    assert(r[k] === null && h.includes('data-metric="' + k + '"'), k + ' rendered as unavailable');
  }
});

group('no closed trades: honest empty state, no fake zeros', () => {
  const r = load('v2_no_trades');
  const { ctx, grid } = context([]);
  ctx.renderMetrics(r);
  const h = grid.innerHTML;
  noJunk(h);
  assert(h.includes('No closed trades in this run'), 'empty trade state');
  assert(!h.includes('Closed-trade outcomes'), 'no empty chart');
  assert(!h.includes('Execution costs'), 'no cost chart without costs');
});

group('schema 1 (Observa 0.1.6) run: still renders, flagged as legacy', () => {
  const r = load('v1_legacy');
  const { ctx, grid } = context([]);
  ctx.renderMetrics(r);
  const h = grid.innerHTML;
  noJunk(h);
  assert(h.includes('Recorded by Observa 0.1.6 or earlier'), 'legacy notice');
  assert(h.includes('Annualised Return (legacy)'), 'legacy annualised value labelled');
  assert(h.includes(ctx.fmtNum(r.total_return_pct, 2) + '%'), 'total return shown');
});

group('hostile or malformed report: no markup injection, no crash', () => {
  const r = JSON.parse(JSON.stringify(load('v2_demo_annualised')));
  r.commission_cost = '1" onmouseover="alert(1)';
  r.total_costs = '<img src=x onerror=alert(1)>';
  r.unavailable = { sharpe_ratio: 42 };
  r.sharpe_ratio = null;
  r.warnings = 'not a list';
  r.assumptions.annualisation_note = '"><script>alert(1)</script>';
  const { ctx, grid } = context([{ type: 'position_closed', net_realized_pnl: '"><b>x' }]);
  ctx.renderMetrics(r);
  const h = grid.innerHTML;
  assert(!h.includes('onmouseover="alert') && !h.includes('<img') && !h.includes('<script>'), 'nothing injected');
  assert(h.includes('42'), 'non-string reason rendered as text');
});

group('the same report is not re-rendered when replay reaches the last bar', () => {
  const r = load('v2_demo_annualised');
  const { ctx, grid } = context([]);
  ctx.renderMetrics(r);
  grid.innerHTML = 'sentinel';
  ctx.renderMetrics(r);
  assert(grid.innerHTML === 'sentinel', 're-render skipped');
});

group('20,000 closed trades render quickly', () => {
  const r = load('v2_demo_annualised');
  const many = Array.from({ length: 20000 }, (_, i) => ({ type: 'position_closed', net_realized_pnl: i % 3 ? -1 : 2 }));
  const { ctx, grid } = context(many);
  const t = Date.now();
  ctx.renderMetrics(r);
  const ms = Date.now() - t;
  assert(ms < 1500 && grid.innerHTML.includes('20,000 trades'), 'render took ' + ms + ' ms');
});

console.log(groups + ' metrics panel test groups passed');
