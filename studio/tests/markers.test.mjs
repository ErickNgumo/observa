import test from 'node:test';
import assert from 'node:assert/strict';
import { CompactMarkers } from '../src/CompactMarkers.ts';

test('marker primitive redraws smaller on zoom out and groups overlapping executions', () => {
  let range = { from: 0, to: 100 }, draws = [], path = [];
  const ctx = { save() {}, restore() {}, beginPath() { path = []; }, moveTo(x, y) { path.push([x, y]); }, lineTo(x, y) { path.push([x, y]); }, closePath() {}, fill() { draws.push({ path, color: this.fillStyle }); }, stroke() {} };
  const target = { useMediaCoordinateSpace(fn) { fn({ context: ctx, mediaSize: { width: 500 } }); } };
  const layer = new CompactMarkers();
  layer.attached({ chart: { timeScale: () => ({ width: () => 500, getVisibleLogicalRange: () => range, timeToCoordinate: () => 30 }) }, series: { priceToCoordinate: () => 100 }, requestUpdate() {} });
  layer.setData([
    { time: 1, position: 'belowBar', shape: 'arrowUp', color: 'green' },
    { time: 1, position: 'belowBar', shape: 'arrowUp', color: 'purple', selected: true },
  ], [{ time: 1, low: 10, high: 12 }]);
  const draw = () => layer.paneViews()[0].renderer().draw(target);
  draw();
  assert.equal(draws.length, 1);
  assert.equal(draws[0].color, 'purple');
  const narrow = Math.abs(draws[0].path[2][0] - draws[0].path[1][0]);
  range = { from: 0, to: 10 }; draws = []; draw();
  const wide = Math.abs(draws[0].path[2][0] - draws[0].path[1][0]);
  assert.ok(narrow < wide);
  assert.ok(wide <= 8);
  layer.detached(); draws = []; draw(); assert.equal(draws.length, 0);
});
