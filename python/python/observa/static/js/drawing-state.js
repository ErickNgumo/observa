// ══════════════════════════════════════════════
// STRATEGY ANNOTATION STATE (OBS-AI-02)
// Pure, DOM-free reducer that reconstructs strategy annotations from the
// canonical `drawings` array of the replay payload.
//
// The payload's `drawings` is index-aligned with `bars` (bar i -> the
// instructions emitted on bar i). `fold()` rebuilds the whole annotation state
// from bar 0 to a target bar; `applyInstructions()` folds a single bar so the
// forward play loop can stay incremental. Folding is always the source of
// truth — backward seeks simply fold again rather than undoing.
//
// Exposed as `ObservaDrawings`; also usable from Node for tests.
// ══════════════════════════════════════════════
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  root.ObservaDrawings = api;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  // Seconds since epoch — the time unit Lightweight Charts expects.
  function toUnix(iso) {
    if (iso === null || iso === undefined) return null;
    var ms = new Date(iso).getTime();
    return isNaN(ms) ? null : Math.floor(ms / 1000);
  }

  function initialState() {
    return {
      series: {},      // id -> { id, options, points: [{ time, value }] }
      primitives: {},  // id -> { id, spec }
      markers: [],     // strategy markers, ordered by bar
      barColors: {},   // unix time -> colour
      barIndex: -1
    };
  }

  function seriesOptions(spec) {
    return {
      color: spec.color,
      width: spec.width,
      line_style: spec.line_style,
      series_type: spec.series_type || 'line',
      pane: spec.pane || 'price',
      label: spec.label || null
    };
  }

  // Applies one bar's instructions to `state` in place and returns it.
  // Unknown drawing types are ignored defensively (an older replay client must
  // never crash on a newer payload).
  function applyInstructions(state, instructions, barIndex, barTime) {
    if (!instructions || !instructions.length) { state.barIndex = barIndex; return state; }
    for (var i = 0; i < instructions.length; i++) {
      var d = instructions[i];
      if (!d || !d.id) continue;
      var action = d.action || 'add';
      var type = d.type;

      if (action === 'remove') {
        delete state.series[d.id];
        delete state.primitives[d.id];
        removeMarker(state, d.id);
        continue;
      }

      if (type === 'series') {
        var entry = state.series[d.id];
        if (!entry) {
          entry = { id: d.id, options: seriesOptions(d), points: [] };
          state.series[d.id] = entry;
        } else {
          // Style may be re-emitted each bar. `label` is optional, so keep the
          // last one a strategy provided instead of clearing it every bar.
          var merged = seriesOptions(d);
          if (merged.label === null) merged.label = entry.options.label;
          entry.options = merged;
        }
        // null / missing value is a gap: never zero, never interpolated.
        if (d.value !== null && d.value !== undefined && barTime !== null && barTime !== undefined) {
          entry.points.push({ time: barTime, value: d.value });
        }
        continue;
      }

      if (type === 'marker') {
        var mtime = toUnix(d.time);
        if (mtime === null) continue;
        removeMarker(state, d.id);
        state.markers.push({
          id: d.id,
          time: mtime,
          barIndex: barIndex,
          position: d.position || 'below',
          shape: d.shape || 'circle',
          color: d.color || '#58a6ff',
          text: d.text || ''
        });
        continue;
      }

      if (type === 'bar_color') {
        var bt = toUnix(d.time);
        if (bt !== null) state.barColors[bt] = d.color;
        continue;
      }

      if (type === 'series' || !type) continue;
      // rectangle / region / hline / line / label (and any unknown future type:
      // the renderer decides whether it can draw it).
      state.primitives[d.id] = { id: d.id, spec: d, barIndex: barIndex };
    }
    state.barIndex = barIndex;
    return state;
  }

  function removeMarker(state, id) {
    for (var i = state.markers.length - 1; i >= 0; i--) {
      if (state.markers[i].id === id) state.markers.splice(i, 1);
    }
  }

  // Rebuilds state from bar 0 through `uptoBarIndex` inclusive.
  // `instructionsByBar` is the payload's `drawings` array.
  function fold(instructionsByBar, uptoBarIndex, barTimes) {
    var state = initialState();
    if (!instructionsByBar) return state;
    var last = Math.min(uptoBarIndex, instructionsByBar.length - 1);
    for (var i = 0; i <= last; i++) {
      applyInstructions(state, instructionsByBar[i], i, barTimes ? barTimes[i] : null);
    }
    state.barIndex = last;
    return state;
  }

  // Counts of what is currently visible (legend / diagnostics).
  function summary(state) {
    var series = [];
    for (var id in state.series) {
      if (Object.prototype.hasOwnProperty.call(state.series, id)) {
        series.push({
          id: id,
          label: state.series[id].options.label || id,
          color: state.series[id].options.color,
          points: state.series[id].points.length,
          pane: state.series[id].options.pane
        });
      }
    }
    series.sort(function (a, b) { return a.id < b.id ? -1 : a.id > b.id ? 1 : 0; });
    var primitives = 0;
    for (var p in state.primitives) {
      if (Object.prototype.hasOwnProperty.call(state.primitives, p)) primitives++;
    }
    return {
      series: series,
      primitiveCount: primitives,
      markerCount: state.markers.length,
      barColorCount: Object.keys(state.barColors).length
    };
  }

  return {
    initialState: initialState,
    applyInstructions: applyInstructions,
    fold: fold,
    summary: summary,
    toUnix: toUnix
  };
});
