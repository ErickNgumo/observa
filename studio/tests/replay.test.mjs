import test from 'node:test';
import assert from 'node:assert/strict';
import { executionMarkers, tradeRange, replayDelays, markerPixels, indicatorSamples, tradeConnections, lineExplanation } from '../src/replay.ts';

test('canonical markers preserve sides, cursor visibility and selected position identity', () => {
  const bars = [0, 1, 2].map(i => ({ time: new Date(1700000000000 + i * 900000).toISOString() }));
  const events = [
    { type: 'position_opened', bar_index: 1, side: 'Sell', position_id: 'short' },
    { type: 'position_closed', bar_index: 2, side: 'Sell', position_id: 'short', net_realized_pnl: -2 },
    { type: 'position_opened', bar_index: 0, side: 'Buy', position_id: 'long' },
    { type: 'order_rejected', bar_index: 0, side: 'Buy' },
  ];
  assert.equal(executionMarkers(events, bars, -1, null).length, 0);
  const markers = executionMarkers(events, bars, 1, 'short');
  assert.deepEqual(markers.map(m => m.shape), ['arrowUp', 'arrowDown']);
  assert.deepEqual(markers.map(m => m.position), ['belowBar', 'aboveBar']);
  assert.equal(markers[1].selected, true);
  const exit = executionMarkers(events, bars, 2, null).at(-1);
  assert.equal(exit.shape, 'arrowUp');
  assert.equal(exit.color, '#2878c8');
  assert.equal(exit.position, 'belowBar');
});

test('trade focus includes entry and only the known portion of an exit', () => {
  const position = { opened_bar: 30, closed_bar: 100 };
  assert.deepEqual(tradeRange(position, 40), { from: 22, to: 48 });
  assert.deepEqual(tradeRange(position, 100), { from: 16, to: 114 });
  assert.deepEqual(tradeRange({ opened_bar: 30 }, 40), { from: 22, to: 48 });
  assert.ok(replayDelays['0.5×'] > replayDelays['1×']);
  assert.ok(replayDelays['1×'] > replayDelays['10×']);
});


test('arrow dimensions remain legible and support user scaling', () => {
  assert.equal(markerPixels(1), 10);
  assert.ok(markerPixels(6) < markerPixels(20));
  assert.equal(markerPixels(100), 16);
  assert.ok(markerPixels(10, 1.3) > markerPixels(10));
  assert.ok(markerPixels(10, 0.8) < markerPixels(10));
  const event = { type: 'position_opened', bar_index: 0, position_id: 'p', side: 'Buy' };
  const bar = { time: '2024-01-01T00:00:00Z' };
  const normal = executionMarkers([event], [bar], 0, null)[0];
  const selected = executionMarkers([event], [bar], 0, 'p')[0];
  assert.equal(selected.selected, true);
  assert.equal(normal.size, selected.size);
});

test('indicator tooltips use exact samples and leave gaps unavailable', () => {
  const state = { series: { sma: { id: 'sma', options: { label: 'SMA', pane: 'price' }, points: [{ time: 1, value: 123 }, { time: 3, value: 456 }] } } };
  assert.equal(indicatorSamples(state, 1)[0].value, 123);
  assert.equal(indicatorSamples(state, 2)[0].value, undefined);
  assert.equal(indicatorSamples(state, 0)[0].value, undefined);
  assert.equal(indicatorSamples(state, 3)[0].label, 'SMA');
});


test('execution arrows use deal direction and exact canonical fill prices', () => {
  const bars = [0, 1].map(i => ({ time: new Date(1700000000000 + i * 900000).toISOString() }));
  const events = [
    { type: 'position_opened', position_id: 'long', side: 'Buy', entry_price: 10.5, bar_index: 0 },
    { type: 'position_closed', position_id: 'long', side: 'Buy', exit_price: 11.2, bar_index: 1 },
    { type: 'position_opened', position_id: 'short', side: 'Sell', entry_price: 10.8, bar_index: 0 },
    { type: 'position_closed', position_id: 'short', side: 'Sell', exit_price: 10.1, bar_index: 1 },
  ];
  const markers = executionMarkers(events, bars, 1, null);
  assert.deepEqual(markers.map(m => [m.positionId, m.shape, m.price]), [
    ['long', 'arrowUp', 10.5], ['short', 'arrowDown', 10.8],
    ['long', 'arrowDown', 11.2], ['short', 'arrowUp', 10.1],
  ]);
});

test('trade paths pair exact tickets, exclude future exits and respect display filters', () => {
  const bars = [0, 1, 2].map(i => ({ time: new Date(1700000000000 + i * 900000).toISOString() }));
  const events = [
    { type: 'position_opened', position_id: 'a', side: 'Buy', entry_price: 10, bar_index: 0 },
    { type: 'position_opened', position_id: 'b', side: 'Buy', entry_price: 11, bar_index: 0 },
    { type: 'position_closed', position_id: 'b', exit_price: 12, bar_index: 1 },
    { type: 'position_closed', position_id: 'a', exit_price: 13, bar_index: 2 },
    { type: 'position_closed', position_id: 'unknown', exit_price: 14, bar_index: 2 },
  ];
  assert.deepEqual(tradeConnections(events, bars, 0, null), []);
  assert.deepEqual(tradeConnections(events, bars, 1, null).map(p => [p.positionId, p.entry, p.exit]), [['b', 11, 12]]);
  assert.deepEqual(tradeConnections(events, bars, 2, 'a', 'selected').map(p => p.positionId), ['a']);
  assert.equal(tradeConnections(events, bars, 2, 'a')[1].selected, true);
  assert.deepEqual(tradeConnections(events, bars, 2, 'a', 'hidden'), []);
});

test('line help explains known concepts without inventing a custom formula', () => {
  assert.match(lineExplanation('SMA 3'), /simple moving average/);
  assert.match(lineExplanation('EMA 20'), /more weight to recent prices/);
  assert.match(lineExplanation('Alpha score'), /exact calculation is defined in the strategy source/);
  assert.match(lineExplanation('Support', 'hline'), /horizontal reference price/);
});
