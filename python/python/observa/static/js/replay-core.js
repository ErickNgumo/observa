// ══════════════════════════════════════════════
// OBS-0010 REPLAY CORE (pure, DOM-free)
// A deterministic view of canonical OBS-0008 events.
// The frontend derives ALL displayed economics from these events; nothing is
// inferred in JavaScript (no fills, no P&L, no SL/TP outcomes, no pairing).
// Exposed as `ObservaReplay`; also usable from Node for tests.
// ══════════════════════════════════════════════
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  root.ObservaReplay = api;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  // ── Event indexing ───────────────────────────
  // Assigns every canonical event to the bar currently open in the replay
  // chronology. Events before the first `bar_processed` form the preamble.
  // End-of-run events (run_completed / run_failed / strategy_error) attach to
  // the bar whose `bar_processed` opened the current bucket.
  function indexEvents(events) {
    var preamble = [];
    var bars = [];   // bars[i] = events belonging to bar i (chronological)
    var endEventOfBar = []; // cumulative last event index per bar
    var barEndIdx = -1;
    var currentBar = -1;
    var idx = -1;

    for (var i = 0; i < events.length; i++) {
      var e = events[i];
      idx++;
      if (e.type === 'bar_processed') {
        currentBar = e.bar_index;
        bars.push([]);
      }
      if (currentBar < 0) {
        preamble.push(e);
      } else {
        bars[currentBar].push(e);
      }
    }
    // Cumulative event pointer at the end of each bar (events are globally
    // indexed 0..n-1, so the running index starts after the preamble).
    var running = preamble.length - 1;
    for (var b = 0; b < bars.length; b++) {
      running += bars[b].length;
      endEventOfBar.push(running);
    }
    return { preamble: preamble, bars: bars, endEventOfBar: endEventOfBar };
  }

  // ── Pure reducer ─────────────────────────────
  // state is mutated in place and returned; callers start from initialState().
  function initialState() {
    return {
      strategyName: null,
      barIndex: -1,
      decisionsByBar: {},          // barIndex -> signal_count
      account: null,               // last canonical portfolio_snapshot
      positions: new Map(),        // position_id -> { ..., open }
      closedTrades: [],            // closed position records (canonical)
      orders: new Map(),           // order_seq -> order record
      failed: null,                // { category, message } from run_failed
      completed: null              // { total_bars, final_balance, ... }
    };
  }

  function orderLabel(type) {
    return type === 'limit' ? 'Limit' : type === 'stop' ? 'Stop' : 'Market';
  }

  function applyEvent(state, e) {
    switch (e.type) {
      case 'run_started':
        state.strategyName = e.strategy_name != null ? e.strategy_name : state.strategyName;
        break;
      case 'strategy_initialized':
      case 'run_completed':
        if (e.type === 'run_completed') {
          state.completed = {
            total_bars: e.total_bars,
            final_balance: e.final_balance,
            final_equity: e.final_equity,
            open_positions_remaining: e.open_positions_remaining
          };
        }
        break;
      case 'bar_processed':
        state.barIndex = e.bar_index;
        break;
      case 'strategy_decision':
        state.decisionsByBar[e.bar_index] = e.signal_count;
        break;
      case 'portfolio_snapshot':
        state.account = {
          balance: e.balance,
          equity: e.equity,
          used_margin: e.used_margin,
          free_margin: e.free_margin,
          unrealised_pnl: e.unrealised_pnl,
          realised_pnl: e.realised_pnl,
          commissions_paid: e.commissions_paid,
          open_positions: e.open_positions,
          bar_index: e.bar_index
        };
        break;
      case 'order_created': {
        var order = {
          seq: e.order_seq,
          type: orderLabel(e.order_type),
          order_type: e.order_type,
          side: e.side,
          quantity_lots: e.quantity_lots,
          created_bar: e.created_bar,
          state: 'created',
          position_id: null,
          executed_price: null,
          filled_bar: null,
          category: null,
          reason: null
        };
        state.orders.set(e.order_seq, order);
        break;
      }
      case 'order_pending': {
        var p = state.orders.get(e.order_seq);
        if (p) p.state = 'pending';
        break;
      }
      case 'order_triggered': {
        var t = state.orders.get(e.order_seq);
        if (t) t.state = 'triggered';
        break;
      }
      case 'order_filled': {
        var f = state.orders.get(e.order_seq);
        if (f) {
          f.state = 'filled';
          f.executed_price = e.executed_price;
          f.filled_bar = e.bar_index;
          if (e.side) f.side = e.side;
        }
        break;
      }
      case 'order_rejected': {
        var r = state.orders.get(e.order_seq);
        if (r) {
          r.state = 'rejected';
          r.category = e.category;
          r.reason = e.reason;
        }
        break;
      }
      case 'order_expired': {
        var x = state.orders.get(e.order_seq);
        if (x) x.state = 'expired';
        break;
      }
      case 'position_opened': {
        state.positions.set(e.position_id, {
          position_id: e.position_id,
          symbol: e.symbol || null,
          side: e.side,
          quantity_lots: e.quantity_lots,
          entry_price: e.entry_price,
          stop_loss: e.stop_loss,
          take_profit: e.take_profit,
          order_seq: e.order_seq,
          opened_bar: e.bar_index,
          open: true,
          exit: null
        });
        break;
      }
      case 'position_closed': {
        var pos = state.positions.get(e.position_id);
        var record = {
          position_id: e.position_id,
          side: e.side,
          quantity_lots: e.quantity_lots,
          entry_price: e.entry_price,
          exit_price: e.exit_price,
          exit_reason: e.exit_reason,
          gross_realized_pnl: e.gross_realized_pnl,
          total_commission: e.total_commission,
          net_realized_pnl: e.net_realized_pnl,
          closed_bar: e.bar_index,
          opened_bar: pos ? pos.opened_bar : null,
          stop_loss: pos ? pos.stop_loss : null,
          take_profit: pos ? pos.take_profit : null
        };
        if (pos) {
          pos.open = false;
          pos.exit = record;
        }
        state.closedTrades.push(record);
        break;
      }
      case 'strategy_error':
        // Intermediate; the run_failed event carries the authoritative reason.
        break;
      case 'run_failed':
        state.failed = { category: e.category, message: e.message };
        break;
      default:
        // Unknown/future canonical event types: ignore safely (never crash).
        break;
    }
    return state;
  }

  // Rebuilds the view from the start through events[0 .. uptoInclusiveIndex].
  function stateThrough(events, uptoInclusiveIndex) {
    var state = initialState();
    var limit = Math.min(uptoInclusiveIndex, events.length - 1);
    for (var i = 0; i <= limit; i++) {
      applyEvent(state, events[i]);
    }
    return state;
  }

  return {
    indexEvents: indexEvents,
    initialState: initialState,
    applyEvent: applyEvent,
    stateThrough: stateThrough
  };
});
