// OBS-AI-02 strategy-annotation tests (Node, no browser needed).
// Loads the pure annotation reducer + the pure renderer helpers and verifies:
// series accumulation, gaps, add/update/remove, every primitive, seek rebuild
// equivalence, progressive visibility, marker merge with canonical markers,
// toggle behaviour, colour handling, and defensive handling of unknown types.
'use strict';

const assert = require('assert');
const path = require('path');

const Drawings = require('../python/observa/static/js/drawing-state.js');
const Renderer = require('../python/observa/static/js/drawing-renderer.js');

let passed = 0;
function ok(name) { passed++; console.log('PASS ' + name); }

const T0 = 1700000000;
const times = [T0, T0 + 900, T0 + 1800, T0 + 2700, T0 + 3600, T0 + 4500];
const iso = (i) => new Date(times[i] * 1000).toISOString();

function bar(t, instructions) { return instructions; }

// ── series accumulation + gaps ──
{
  const perBar = [
    bar(0, [{ id: 'ema', type: 'series', value: null, color: '#58a6ff', label: 'EMA 20' }]),
    bar(1, [{ id: 'ema', type: 'series', value: 1.1, color: '#58a6ff' }]),
    bar(2, [{ id: 'ema', type: 'series', value: 1.2, color: '#58a6ff' }]),
    bar(3, []), // no emission at all is also a gap
    bar(4, [{ id: 'ema', type: 'series', value: null, color: '#58a6ff' }]),
    bar(5, [{ id: 'ema', type: 'series', value: 1.3, color: '#58a6ff' }]),
  ];
  const s = Drawings.fold(perBar, 5, times);
  assert.strictEqual(Object.keys(s.series).length, 1, 'one series identity across bars');
  assert.deepStrictEqual(s.series.ema.points, [
    { time: times[1], value: 1.1 },
    { time: times[2], value: 1.2 },
    { time: times[5], value: 1.3 },
  ], 'null and missing emissions are gaps, never zero/interpolated');
  assert.strictEqual(s.series.ema.options.label, 'EMA 20');
  ok('series: accumulation, identity across bars, null/missing gaps');
}

// ── every primitive folds into primitives[] ──
{
  const perBar = [[
    { id: 'z', type: 'rectangle', time_start: iso(0), time_end: null, price_top: 1.1, price_bot: 1.0, color: '#3fb950', opacity: 0.14, label: 'FVG' },
    { id: 'g', type: 'region', time_start: iso(0), time_end: iso(1), color: '#58a6ff' },
    { id: 'h', type: 'hline', price: 1.05, color: '#d29922', label: 'POC' },
    { id: 't', type: 'line', x1: iso(0), y1: 1.0, x2: iso(1), y2: 1.1, color: '#8957e5' },
    { id: 'l', type: 'label', time: iso(0), price: 1.02, text: 'RSI 27', color: '#f85149', position: 'left' },
    { id: 'c', type: 'bar_color', time: iso(0), color: '#d29922' },
  ]];
  const s = Drawings.fold(perBar, 0, times);
  assert.deepStrictEqual(Object.keys(s.primitives).sort(), ['g', 'h', 'l', 't', 'z']);
  assert.strictEqual(s.barColors[times[0]], '#d29922', 'bar colour keyed by bar time');
  assert.strictEqual(Renderer.drawingSupportsPrimitive('marker'), false, 'markers are not primitives');
  assert.strictEqual(Renderer.drawingSupportsPrimitive('series'), false, 'series are native chart series');
  ok('primitives: rectangle/region/hline/line/label + bar_color map');
}

// ── add / update / remove lifecycle ──
{
  const perBar = [
    [{ id: 'z', type: 'rectangle', time_start: iso(0), price_top: 1.1, price_bot: 1.0, color: '#3fb950' }],
    [{ id: 'z', type: 'rectangle', action: 'update', time_start: iso(0), price_top: 1.2, price_bot: 1.0, color: '#3fb950' }],
    [{ id: 'z', action: 'remove' }],
  ];
  assert.strictEqual(Drawings.fold(perBar, 1, times).primitives.z.spec.price_top, 1.2, 'update replaces the spec');
  assert.deepStrictEqual(Object.keys(Drawings.fold(perBar, 2, times).primitives), [], 'remove deletes the id');
  ok('lifecycle: add -> update -> remove');
}

// ── series remove stops the series ──
{
  const perBar = [
    [{ id: 's', type: 'series', value: 1.0, color: '#58a6ff' }],
    [{ id: 's', type: 'series', value: 2.0, color: '#58a6ff' }],
    [{ id: 's', action: 'remove' }],
    [{ id: 's', type: 'series', value: 3.0, color: '#58a6ff' }],
  ];
  const afterRemove = Drawings.fold(perBar, 2, times);
  assert.deepStrictEqual(Object.keys(afterRemove.series), [], 'remove deletes the series');
  const restarted = Drawings.fold(perBar, 3, times);
  assert.deepStrictEqual(restarted.series.s.points, [{ time: times[3], value: 3 }], 're-added series restarts empty');
  ok('series: remove stops the series; re-add starts fresh');
}

// ── seek rebuild equivalence ──
{
  const perBar = [];
  for (let i = 0; i < times.length; i++) {
    perBar.push([
      { id: 'ema', type: 'series', value: 1.0 + i, color: '#58a6ff' },
      { id: 'zone', type: 'rectangle', time_start: iso(0), price_top: 1.1 + i, price_bot: 1.0, color: '#3fb950' },
    ]);
  }
  // walk forward incrementally
  let incremental = Drawings.initialState();
  for (let i = 0; i < times.length; i++) {
    Drawings.applyInstructions(incremental, perBar[i], i, times[i]);
  }
  const rebuilt = Drawings.fold(perBar, times.length - 1, times);
  assert.deepStrictEqual(incremental.series.ema.points, rebuilt.series.ema.points, 'forward walk == rebuild (series)');
  assert.deepStrictEqual(incremental.primitives.zone.spec, rebuilt.primitives.zone.spec, 'forward walk == rebuild (primitives)');
  assert.deepStrictEqual(Drawings.summary(incremental), Drawings.summary(rebuilt), 'summaries agree');
  // backward seek simply folds again
  const back = Drawings.fold(perBar, 2, times);
  assert.strictEqual(back.series.ema.points.length, 3, 'backward seek rebuilds to the target bar');
  ok('seek: forward incremental == full rebuild; backward rebuild is exact');
}

// ── progressive visibility ──
{
  const perBar = [
    [],
    [],
    [],
    [],
    [],
    [{ id: 'z', type: 'rectangle', time_start: iso(5), price_top: 1.1, price_bot: 1.0, color: '#3fb950' }],
  ];
  assert.deepStrictEqual(Object.keys(Drawings.fold(perBar, 4, times).primitives), [], 'nothing before it is emitted');
  assert.deepStrictEqual(Object.keys(Drawings.fold(perBar, 5, times).primitives), ['z'], 'visible from its bar onward');
  ok('progressive visibility: annotations appear only from their bar');
}

// ── markers: add/remove + shape mapping + coexistence with canonical ──
{
  const perBar = [
    [{ id: 'm1', type: 'marker', time: iso(0), position: 'above', shape: 'arrow_up', color: '#3fb950', text: 'long' }],
    [{ id: 'm2', type: 'marker', time: iso(1), position: 'below', shape: 'square', color: '#f85149' }],
    [{ id: 'm1', action: 'remove' }],
  ];
  const s = Drawings.fold(perBar, 2, times);
  assert.strictEqual(s.markers.length, 1, 'removed marker is gone');
  assert.strictEqual(s.markers[0].id, 'm2');

  const chartMarkers = Renderer.drawingMarkersFor(s, true);
  assert.strictEqual(chartMarkers.length, 1);
  assert.strictEqual(chartMarkers[0].position, 'belowBar');
  assert.strictEqual(chartMarkers[0].shape, 'square');
  assert.strictEqual(chartMarkers[0].time, times[1]);
  assert.deepStrictEqual(Renderer.drawingMarkersFor(s, false), [], 'toggle off hides strategy markers');

  // events.js merges the two layers by concatenation; canonical markers survive.
  const canonical = [{ time: times[0], position: 'belowBar', shape: 'arrowUp', color: '#3fb950', text: 'B @ 1.1' }];
  const merged = canonical.concat(Renderer.drawingMarkersFor(s, true));
  assert.strictEqual(merged.length, 2, 'strategy markers coexist with canonical execution markers');
  assert.strictEqual(merged[0].text, 'B @ 1.1', 'canonical markers are preserved');
  ok('markers: lifecycle, chart shape mapping, canonical coexistence, toggle');
}

// ── colour handling (8-digit hex + opacity) ──
{
  assert.strictEqual(Renderer.drawingFillColor('#3fb950', 0.14), 'rgba(63,185,80,0.14)');
  assert.strictEqual(Renderer.drawingFillColor('#3fb95080', null), 'rgba(63,185,80,' + (0x80 / 255) + ')', '8-digit hex alpha honoured');
  assert.strictEqual(Renderer.drawingFillColor(null, null, 'rgba(1,2,3,0.1)'), 'rgba(1,2,3,0.1)', 'fallback when unset');
  assert.strictEqual(Renderer.drawingStrokeColor('#f85149ff'), '#f85149', 'stroke strips alpha');
  ok('colour: 8-digit hex alpha, explicit opacity, fallbacks');
}

// ── defensive: unknown persisted drawing type never crashes an old client ──
{
  const perBar = [
    [{ id: 'future', type: 'hypercube', value: 1, color: '#ffffff' }],
    [{ id: 'ema', type: 'series', value: 1.0, color: '#58a6ff' }],
  ];
  const s = Drawings.fold(perBar, 1, times);
  assert.deepStrictEqual(Object.keys(s.primitives), ['future'], 'unknown types are kept as inert primitives');
  assert.strictEqual(Renderer.drawingSupportsPrimitive('hypercube'), false, 'renderer refuses to draw them');
  assert.strictEqual(s.series.ema.points.length, 1, 'known drawings in the same run still work');
  const empty = Drawings.fold(null, 3, times);
  assert.deepStrictEqual(Object.keys(empty.series), [], 'a payload with no drawings folds to empty state');
  ok('defensive: unknown types ignored by the renderer, empty payload safe');
}

// ── summary drives the legend ──
{
  const perBar = [[
    { id: 'b', type: 'series', value: 2, color: '#f78166', label: 'Slow' },
    { id: 'a', type: 'series', value: 1, color: '#58a6ff', pane: 'separate' },
  ]];
  const summary = Drawings.summary(Drawings.fold(perBar, 0, times));
  assert.deepStrictEqual(summary.series.map(function (s) { return s.id; }), ['a', 'b'], 'legend is deterministic by id');
  assert.strictEqual(summary.series[1].label, 'Slow', 'label falls back to id when absent');
  assert.strictEqual(summary.series[0].label, 'a', 'id used when no label');
  assert.strictEqual(summary.series[0].pane, 'separate');
  ok('legend: deterministic series summary with label fallback');
}

// ── Lightweight Charts primitive/renderer contract ──
// Regression guard for the defect that blanked EVERY series (price pane and
// secondary pane): Lightweight Charts 5.0.9 calls renderer.draw() on every
// pane view unconditionally and drawBackground() only when present, so a
// background-only renderer throws "draw is not a function" and aborts the
// whole render pass.
{
  const prim = new Renderer.StrategyDrawingPrimitive({ type: 'rectangle', price_top: 1, price_bot: 0 });
  const views = prim.paneViews();
  assert.ok(Array.isArray(views) && views.length >= 1, 'paneViews returns views');
  for (const view of views) {
    assert.strictEqual(typeof view.renderer, 'function', 'each view exposes renderer()');
    const r = view.renderer();
    assert.strictEqual(typeof r.draw, 'function',
      'every pane renderer MUST implement draw() (LWC calls it unconditionally)');
    if (r.drawBackground !== undefined) {
      assert.strictEqual(typeof r.drawBackground, 'function', 'drawBackground must be callable when present');
    }
  }
  const background = views.find((v) => v.zOrder() === 'bottom').renderer();
  assert.strictEqual(typeof background.drawBackground, 'function', 'background view paints via drawBackground');
  assert.strictEqual(typeof background.draw, 'function', 'background view still satisfies draw()');
  const top = views.find((v) => v.zOrder() === 'top').renderer();
  assert.strictEqual(typeof top.draw, 'function', 'top view draws strokes/labels');
  ok('renderer contract: every pane view renderer implements draw()');
}

console.log('\n' + passed + ' drawing test groups passed');
