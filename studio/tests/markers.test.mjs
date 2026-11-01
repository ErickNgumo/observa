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
    { time: 1, position: 'belowBar', shape: 'arrowUp', color: 'green', price: 11, positionId: 'p' },
    { time: 1, position: 'belowBar', shape: 'arrowUp', color: 'purple', selected: true, price: 11, positionId: 'p' },
  ], [{ time: 1, low: 10, high: 12 }]);
  const draw = () => layer.paneViews()[0].renderer().draw(target);
  draw();
  assert.equal(draws.length, 1);
  assert.equal(draws[0].color, 'purple');
  const narrow = Math.abs(draws[0].path[6][0] - draws[0].path[1][0]);
  range = { from: 0, to: 10 }; draws = []; draw();
  const wide = Math.abs(draws[0].path[6][0] - draws[0].path[1][0]);
  assert.ok(narrow < wide);
  assert.ok(wide <= 16);
  assert.equal(layer.hitTest(30, 105).externalId, 'trade:p');
  assert.equal(layer.hitTest(100, 200), null);
  layer.detached(); draws = []; draw(); assert.equal(draws.length, 0);
});


test('connector geometry joins recorded fill coordinates and supplies trade hit targets', () => {
  let points = [];
  const ctx = { save() {}, restore() {}, setLineDash() {}, beginPath() {}, moveTo(x, y) { points.push([x, y]); }, lineTo(x, y) { points.push([x, y]); }, stroke() {} };
  const layer = new CompactMarkers();
  layer.attached({ chart: { timeScale: () => ({ width: () => 500, getVisibleLogicalRange: () => ({ from: 0, to: 10 }), timeToCoordinate: t => t * 10 }) }, series: { priceToCoordinate: p => p * 5 }, requestUpdate() {} });
  layer.setData([], [], [{ positionId: 'exact-ticket', start: 1, end: 3, entry: 10, exit: 20, color: 'blue' }]);
  layer.paneViews()[0].renderer().draw({ useMediaCoordinateSpace(fn) { fn({ context: ctx, mediaSize: { width: 500 } }); } });
  assert.deepEqual(points, [[10, 50], [30, 100]]);
  assert.equal(layer.hitTest(20, 75).externalId, 'trade:exact-ticket');
  assert.equal(layer.hitTest(200, 75), null);
  layer.updateAllViews(); assert.equal(layer.hitTest(20, 75), null);
});
