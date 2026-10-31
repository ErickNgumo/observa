import test from 'node:test';
import assert from 'node:assert/strict';
import { executionMarkers, tradeRange, replayDelays, markerPixels, indicatorSamples } from '../src/replay.ts';

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
  assert.match(markers[1].text, /selected/);
  const exit = executionMarkers(events, bars, 2, null).at(-1);
  assert.equal(exit.shape, 'circle');
  assert.equal(exit.color, '#c35449');
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


test('compact marker dimensions follow spacing without growing on selection', () => {
  assert.equal(markerPixels(1), 2);
  assert.ok(markerPixels(6) < markerPixels(12));
  assert.equal(markerPixels(100), 8);
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
