// Presentation state tests; canonical economics stay covered by replay.test.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const dir = __dirname + '/../python/observa/static/js/';
const button = { textContent: '', classList: { toggle() {} }, setAttribute() {} };
const ctx = vm.createContext({ console, document: { getElementById: id => id === 'chart-container' ? { getBoundingClientRect: () => ({ top: 100 }) } : button }, window: { innerHeight: 768, innerWidth: 1366 } });
vm.runInContext(fs.readFileSync(dir + 'helpers.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync(dir + 'workspace.js', 'utf8'), ctx);
assert.equal(ctx.fmtNum(-0, 2), '0.00');
assert.equal(ctx.fmtNum(-100, 2), '-100.00');
vm.runInContext(fs.readFileSync(dir + 'panels.js', 'utf8'), ctx);
assert.equal(ctx.instrumentLabel({ symbol: 'NQ', interval: '5m' }), 'NQ · 5m');
assert.equal(ctx.instrumentLabel({ symbol: 'BTCUSDT', interval: '1h' }), 'BTCUSDT · 1h');
assert.equal(ctx.instrumentLabel({ symbol: 'EURUSD' }), 'EURUSD');
assert.equal(ctx.instrumentLabel({}), 'Loaded run');
for (const width of [700, 1280, 1800]) {
  const range = ctx.followRange(599, width, 8);
  assert.ok(Math.abs((599 - range.from) / (range.to - range.from) - 0.8) < 1e-10);
  assert.ok(Math.abs(width / (range.to - range.from) - 8) < 1e-10);
}
ctx.pauseChartFollow();
assert.equal(ctx.chartFollowing, false);
assert.equal(button.textContent, 'Resume follow');
assert.equal(ctx.clampPanelHeight(-100), 130);
assert.equal(ctx.clampPanelHeight(9999), 405);
assert.equal(ctx.clampPanelHeight(280), 280);
assert.equal(ctx.tradeDuration(1000, 6400), '1h 30m');
assert.equal(ctx.tradeDuration(1000, 1000), '0m');
assert.equal(ctx.tradeDuration('', 1000), '—');
assert.equal(ctx.tradeDuration(2000, 1000), '—');
console.log('PASS workspace: metadata fallback, follow spacing/position, user override, resize bounds, duration');
