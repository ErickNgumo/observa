// OBS-0010 replay-state tests (Node, no browser needed).
// Loads canonical event fixtures produced by the real Engine and verifies the
// replay-core reducer: multi-position state, exact close pairing, hedging,
// SL/TP reasons/prices, gap execution prices, rejections, expiry, failures,
// open end positions, EventSeq ordering and unknown-event resilience.
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Replay = require('../js/replay-core.js');

const FIX = path.join(__dirname, 'fixtures');

function loadFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FIX, name + '.json'), 'utf8'));
}

function runAll(fixture) {
  return Replay.stateThrough(fixture.events, fixture.events.length - 1);
}

function bucketCounts(fixture) {
  const idx = Replay.indexEvents(fixture.events);
  return idx;
}

let passed = 0;
function ok(name) { passed++; console.log('PASS ' + name); }

// ── Fixture A: one MARKET round trip ──
{
  const f = loadFixture('a_market_trade');
  const view = runAll(f);
  assert.strictEqual(f.status, 'completed');
  assert.ok(view.completed, 'run completed');
  assert.strictEqual(view.closedTrades.length, 1, 'one closed trade');
  assert.strictEqual(countOpen(view), 0, 'no open positions');
  const t = view.closedTrades[0];
  assert.strictEqual(t.exit_reason, 'Signal');
  assert.ok(Math.abs(t.net_realized_pnl - 50000) < 1e-6, 'canonical PnL 50000');
  assert.ok(view.account && Math.abs(view.account.equity - 60000) < 1e-6);
  // EventSeq dense + within-bar ascending (canonical ordering preserved).
  const seqs = f.events.map(e => e.event_seq);
  assert.deepStrictEqual(seqs, seqs.map((_, i) => i), 'event_seq dense 0..n-1');
  const idx = bucketCounts(f);
  for (const bar of idx.bars) {
    for (let i = 1; i < bar.length; i++) {
      assert.ok(bar[i - 1].event_seq < bar[i].event_seq, 'bar events in event_seq order');
    }
  }
  ok('a_market_trade: economics, close reason, EventSeq density/order');
}

// ── Fixture B: NEXT_BAR_OPEN decision bar != fill bar ──
{
  const f = loadFixture('b_next_bar_open');
  const view = runAll(f);
  const created = f.events.find(e => e.type === 'order_created');
  const opened = f.events.find(e => e.type === 'position_opened');
  assert.strictEqual(created.created_bar, 0, 'decision bar 0');
  assert.strictEqual(opened.bar_index, 1, 'fill bar 1 (N+1)');
  assert.strictEqual(opened.entry_price, 1.25, 'filled at bar1 open');
  assert.strictEqual(countOpen(view), 1);
  ok('b_next_bar_open: decision bar != fill bar, no lookahead');
}

// ── Fixture C: LIMIT pending → triggered → filled at 0.95 ──
{
  const f = loadFixture('c_limit');
  const view = runAll(f);
  const types = f.events.map(e => e.type);
  assert.ok(types.includes('order_pending'));
  assert.ok(types.includes('order_triggered'));
  const fill = f.events.find(e => e.type === 'order_filled');
  assert.strictEqual(fill.executed_price, 0.95);
  const order = view.orders.get(0);
  assert.strictEqual(order.state, 'filled');
  assert.strictEqual(order.type, 'Limit');
  ok('c_limit: pending/trigger/fill lifecycle with canonical fill price');
}

// ── Fixture D: protective SL gap — marker must use canonical fill, not stop ──
{
  const f = loadFixture('d_sl_gap');
  const view = runAll(f);
  const close = f.events.find(e => e.type === 'position_closed');
  assert.strictEqual(close.exit_reason, 'StopLoss');
  assert.ok(close.exit_price < 0.995, 'gap fill below stop (open 0.985)');
  assert.strictEqual(countOpen(view), 0);
  assert.strictEqual(view.closedTrades[0].exit_reason, 'StopLoss');
  ok('d_sl_gap: canonical gap execution price used, stop not used as fill');
}

// ── Fixture E: three simultaneous positions ──
{
  const f = loadFixture('e_multi_position');
  const view = runAll(f);
  assert.strictEqual(countOpen(view), 3, 'three open positions simultaneously');
  ok('e_multi_position: multiple simultaneous positions');
}

// ── Fixture F: hedge (long + short same symbol) ──
{
  const f = loadFixture('f_hedge');
  const view = runAll(f);
  const sides = [];
  view.positions.forEach(p => sides.push(p.side));
  assert.ok(sides.includes('Buy') && sides.includes('Sell'), 'long and short coexist');
  assert.strictEqual(countOpen(view), 2);
  ok('f_hedge: long and short represented independently');
}

// ── Fixture G: close the exact position among several ──
{
  const f = loadFixture('g_close_exact_ticket');
  const view = runAll(f);
  assert.strictEqual(view.closedTrades.length, 1, 'exactly one close');
  const closed = view.closedTrades[0];
  assert.strictEqual(closed.quantity_lots, 2, 'closed the size-2 (middle) position');
  assert.strictEqual(closed.opened_bar, 1, 'B opened on bar 1');
  // Remaining open: A (size 1) and C (size 3).
  const openSizes = [];
  view.positions.forEach(p => { if (p.open) openSizes.push(p.quantity_lots); });
  openSizes.sort((a, b) => a - b);
  assert.deepStrictEqual(openSizes, [1, 3]);
  // No FIFO: the oldest open (size 1, bar 0) must still be open.
  assert.strictEqual(countOpen(view), 2);
  ok('g_close_exact_ticket: exact position_id pairing (A open, B closed, C open)');
}

// ── Fixture H: intrabar SL execution at 0.995 ──
{
  const f = loadFixture('h_sl_intrabar');
  const view = runAll(f);
  const close = f.events.find(e => e.type === 'position_closed');
  assert.strictEqual(close.exit_reason, 'StopLoss');
  assert.strictEqual(close.exit_price, 0.995, 'intrabar SL fills at stop price');
  assert.strictEqual(countOpen(view), 0);
  ok('h_sl_intrabar: SL reason + canonical execution price');
}

// ── Fixture I: TP execution at 1.005 ──
{
  const f = loadFixture('i_tp');
  const close = f.events.find(e => e.type === 'position_closed');
  assert.strictEqual(close.exit_reason, 'TakeProfit');
  assert.strictEqual(close.exit_price, 1.005);
  ok('i_tp: TakeProfit reason + canonical execution price');
}

// ── Fixture J: rejection ──
{
  const f = loadFixture('j_rejected');
  const view = runAll(f);
  const rej = f.events.find(e => e.type === 'order_rejected');
  assert.ok(rej, 'order_rejected present');
  assert.strictEqual(rej.category, 'execution_domain');
  assert.ok(rej.reason && rej.reason.length > 0, 'canonical reason present');
  const order = view.orders.get(0);
  assert.strictEqual(order.state, 'rejected');
  assert.strictEqual(order.category, 'execution_domain');
  assert.strictEqual(countOpen(view), 0);
  assert.strictEqual(view.closedTrades.length, 0);
  ok('j_rejected: rejection category/reason inspectable, nothing filled');
}

// ── Fixture K: expired order ──
{
  const f = loadFixture('k_expired');
  const view = runAll(f);
  const order = view.orders.get(0);
  assert.strictEqual(order.state, 'expired', 'queued-on-last-bar order expires');
  assert.ok(!f.events.some(e => e.type === 'order_filled'), 'no fabricated fill');
  ok('k_expired: expired order not shown as filled');
}

// ── Fixture L: failed run ──
{
  const f = loadFixture('l_failed');
  const view = runAll(f);
  assert.strictEqual(f.status, 'failed');
  assert.ok(view.failed, 'run_failed surfaced');
  assert.strictEqual(view.failed.category, 'strategy');
  assert.ok(!view.completed, 'no run_completed');
  assert.strictEqual(f.events[f.events.length - 1].type, 'run_failed');
  ok('l_failed: failed run renders diagnostics, no completion');
}

// ── Fixture M: open position at end, balance != equity ──
{
  const f = loadFixture('m_open_end');
  const view = runAll(f);
  assert.strictEqual(countOpen(view), 1, 'open position preserved (no fake close)');
  assert.ok(view.account.balance !== view.account.equity, 'balance != equity');
  assert.ok(Math.abs(view.account.balance - 10000) < 1e-6);
  assert.ok(Math.abs(view.account.equity - 60000) < 1e-6);
  assert.strictEqual(view.completed.open_positions_remaining, 1);
  ok('m_open_end: open position kept; balance/equity distinguished');
}

// ── Fixture N: no-trade run ──
{
  const f = loadFixture('n_no_trade');
  const view = runAll(f);
  assert.strictEqual(countOpen(view), 0);
  assert.strictEqual(view.closedTrades.length, 0);
  assert.strictEqual(view.orders.size, 0);
  assert.ok(view.account && Math.abs(view.account.balance - 10000) < 1e-6);
  ok('n_no_trade: no trades, no positions, no crash');
}

// ── Unknown future event types are ignored safely ──
{
  const s = Replay.initialState();
  Replay.applyEvent(s, { event_seq: 999, type: 'future_unknown_event', something: 1 });
  assert.strictEqual(s.failed, null);
  ok('unknown event type ignored without crashing');
}

// ── Deterministic forward/backward navigation (pure rebuild) ──
{
  const f = loadFixture('a_market_trade');
  const idx = Replay.indexEvents(f.events);
  const atBar = k => Replay.stateThrough(f.events, idx.endEventOfBar[k]);
  const b0 = atBar(0);
  assert.strictEqual(countOpen(b0), 1, 'bar0 view has the open position');
  assert.ok(b0.account && Math.abs(b0.account.equity - 10000) < 1e-6, 'bar0 snapshot');
  // non-linear: 0 -> 1 -> 0 -> 1 must be identical each time
  const b0again = atBar(0);
  assert.strictEqual(countOpen(b0again), 1);
  const end = atBar(1);
  assert.strictEqual(end.closedTrades.length, 1);
  ok('deterministic rebuild: backward/forward navigation stable');
}

function countOpen(view) {
  let n = 0;
  view.positions.forEach(p => { if (p.open) n++; });
  return n;
}

console.log('\n' + passed + '/16 replay test groups passed');
process.exit(passed === 16 ? 0 : 1);
