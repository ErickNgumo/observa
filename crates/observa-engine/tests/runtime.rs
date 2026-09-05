//! Engine-level runtime integration tests (OBS-0007 §33/§34).
//!
//! These tests exercise the canonical Engine (one replay loop) rather than
//! only the OBS-0006 semantics helpers. All expected values are hand-derived
//! from the accepted OBS-0004/5/6 contracts.

use std::collections::BTreeMap;

use chrono::{DateTime, TimeZone, Utc};
use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig,
    StrategyConfig,
};
use observa_core::types::{Direction, OrderKind, OrderState};
use observa_engine::engine::{Engine, FillReason};
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use serde_json::json;

const EPS: f64 = 1e-6;

fn ts(i: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
}

fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
    Bar::new(ts(i), o, h, l, c, None)
}

fn config(fill_mode: FillMode, commission: Option<f64>) -> BacktestConfig {
    BacktestConfig {
        version: 1,
        account: AccountConfig {
            starting_balance: 10_000.0,
            currency: "USD".to_string(),
            leverage: 100.0,
        },
        instrument: InstrumentConfig {
            symbol: "EURUSD".to_string(),
            base_currency: "EUR".to_string(),
            quote_currency: "USD".to_string(),
            contract_size: 100_000.0,
            min_quantity: 0.01,
            max_quantity: 100.0,
            quantity_step: 0.01,
            ..Default::default()
        },
        execution: CoreExecutionConfig {
            fill_mode,
            spread: 0.0002,
            slippage: 0.0001,
            commission: CommissionConfig {
                mode: CommissionMode::PerSide,
                flat_per_fill: commission.unwrap_or(0.0),
                rate_per_unit: 0.0,
            },
            order_model: OrderModelConfig::default(),
        },
        dataset: Some(DatasetConfig {
            source: "test.csv".to_string(),
            hash: None,
            interval: BarInterval::Minute(15),
            start: None,
            end: None,
            bar_count: None,
        }),
        strategy: Some(StrategyConfig {
            name: "TestStrategy".to_string(),
            source: None,
            source_hash: None,
            parameters: BTreeMap::new(),
        }),
    }
}

/// Strategy helpers.
fn buy_signal(bar: &Bar) -> StrategySignal {
    StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: bar.close,
        sl: None,
        tp: None,
        reason: "buy".to_string(),
        ticket: None,
    }
}

/// Emits a signal exactly once at `emit_bar` (0-based bar counter), then
/// nothing.
struct OnceOnBar {
    emit_at: usize,
    seen: usize,
    signals: Vec<StrategySignal>,
}

impl OnceOnBar {
    fn new(emit_at: usize, signals: Vec<StrategySignal>) -> Self {
        Self {
            emit_at,
            seen: 0,
            signals,
        }
    }
}

impl Strategy for OnceOnBar {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        _portfolio: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        let seen = self.seen;
        self.seen += 1;
        if seen == self.emit_at {
            std::mem::take(&mut self.signals)
        } else {
            vec![]
        }
    }
}

/// Never signals.
struct Noop;
impl Strategy for Noop {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        _portfolio: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        vec![]
    }
}

// ── A. No-trade run ─────────────────────────────

#[test]
fn no_trade_run_replays_fully() {
    let bars = vec![
        bar(0, 1.10, 1.11, 1.09, 1.105),
        bar(1, 1.10, 1.11, 1.09, 1.10),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = Noop;
    let result = engine.run(&bars, &mut s).unwrap();
    assert_eq!(result.total_bars, 2);
    assert_eq!(result.bars.len(), 2);
    assert!(result.fills.is_empty());
    assert!((result.final_state.final_balance - 10_000.0).abs() < EPS);
    assert!((result.final_state.final_equity - 10_000.0).abs() < EPS);
    assert_eq!(result.final_state.open_positions_remaining, 0);
}

// ── B. BAR_CLOSE market fill ─────────────────────

#[test]
fn bar_close_market_fills_from_observed_bar_close() {
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1010, 1.1020, 1.1000, 1.1010),
    ];
    let engine = Engine::new(config(FillMode::BarClose, None)).unwrap();
    let mut s = OnceOnBar::new(0, vec![buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000))]);
    let result = engine.run(&bars, &mut s).unwrap();
    assert_eq!(result.fills.len(), 1);
    let f = &result.fills[0];
    assert_eq!(f.bar_index, 0); // executed on the observed bar
                                // reference = bar0.close = 1.1000; buy = + half spread + slippage
    assert!((f.raw_reference - 1.1000).abs() < EPS);
    assert!((f.executed_price - 1.1002).abs() < EPS);
    assert_eq!(f.reason, FillReason::MarketEntry);
}

// ── C. NEXT_BAR_OPEN regression ──────────────────

#[test]
fn next_bar_open_fills_from_next_bar_open_not_signal() {
    // Signal bar N: open 1.0000, close 1.1000. Next bar N+1: open 1.2500.
    let bars = vec![
        bar(0, 1.0000, 1.1500, 0.9900, 1.1000),
        bar(1, 1.2500, 1.2600, 1.2400, 1.2550),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal_bar = bar(0, 1.0000, 1.1500, 0.9900, 1.1000);
    let mut s = OnceOnBar::new(0, vec![buy_signal(&signal_bar)]);
    let result = engine.run(&bars, &mut s).unwrap();
    assert_eq!(result.fills.len(), 1);
    let f = &result.fills[0];
    assert_eq!(f.bar_index, 1);
    // reference = N+1 open = 1.2500, NEVER bar N open (1.0000) or close
    // (1.1000).
    assert!((f.raw_reference - 1.2500).abs() < EPS);
    assert_ne!(f.raw_reference, 1.0000);
    assert_ne!(f.raw_reference, 1.1000);
}

// ── D. Last-bar NEXT_BAR_OPEN: no fabricated fill ─

#[test]
fn last_bar_next_bar_open_does_not_fabricate_fill() {
    let bars = vec![
        bar(0, 1.10, 1.11, 1.09, 1.105),
        bar(1, 1.10, 1.11, 1.09, 1.10),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = OnceOnBar::new(1, vec![buy_signal(&bar(1, 1.1, 1.11, 1.09, 1.10))]);
    let result = engine.run(&bars, &mut s).unwrap();
    assert!(
        result.fills.is_empty(),
        "no fill may be fabricated on the final bar"
    );
    assert_eq!(result.orders.len(), 1);
    assert_eq!(result.orders[0].state, OrderState::Expired);
    assert!((result.final_state.final_balance - 10_000.0).abs() < EPS);
    assert_eq!(result.final_state.open_positions_remaining, 0);
}

// ── E. LIMIT pending then fill ───────────────────

#[test]
fn limit_pending_then_fills_when_touched() {
    // Limit BUY at 1.0900 far below the market; bars stay above until bar 5
    // touches 1.0900 intrabar.
    let mut bars: Vec<Bar> = Vec::new();
    for i in 0..6 {
        bars.push(bar(
            i,
            1.1000,
            1.1010,
            if i == 5 { 1.0895 } else { 1.0990 },
            1.1005,
        ));
    }
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Limit,
        size: 1.0,
        intended_price: 1.0900,
        sl: None,
        tp: None,
        reason: "limit".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    let limit_order = result
        .orders
        .iter()
        .find(|o| o.order_type == OrderKind::Limit)
        .unwrap();
    assert_eq!(limit_order.state, OrderState::Filled);
    assert_eq!(limit_order.filled_bar, Some(5));
    let f = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::LimitEntry)
        .unwrap();
    assert_eq!(f.bar_index, 5);
    assert!((f.executed_price - 1.0900).abs() < EPS);
    assert_eq!(f.slippage_applied, 0.0);
}

// ── F. STOP pending then gap-through ─────────────

#[test]
fn stop_pending_gap_through_uses_gap_price() {
    // BUY STOP at 1.1100; bar 4 opens 1.1150 (gap through) → raw 1.1150.
    let mut bars: Vec<Bar> = Vec::new();
    for i in 0..5 {
        let o = if i == 4 { 1.1150 } else { 1.1000 };
        bars.push(bar(i, o, o + 0.0010, o - 0.0010, o + 0.0005));
    }
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Stop,
        size: 1.0,
        intended_price: 1.1100,
        sl: None,
        tp: None,
        reason: "stop".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    let f = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::StopEntry)
        .unwrap();
    assert_eq!(f.bar_index, 4);
    assert!((f.raw_reference - 1.1150).abs() < EPS);
    assert!((f.executed_price - 1.1152).abs() < EPS);
}

// ── G. Protective SL gap ─────────────────────────

#[test]
fn protective_sl_gap_exits_at_open() {
    // Strategy buys bar 0 with SL 1.0950 (attached at open, NEXT_BAR_OPEN so
    // entry occurs bar 1). Bar 2 opens below the SL → SL gap exit.
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
        bar(1, 1.1005, 1.1010, 1.0995, 1.1000),
        bar(2, 1.0930, 1.0940, 1.0920, 1.0935),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(1.0950),
        tp: None,
        reason: "buy with SL".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    let sl_fill = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::StopLoss)
        .unwrap();
    // SL exit at the open 1.0930 (not the stale 1.0950), sell-adjusted.
    assert!((sl_fill.raw_reference - 1.0930).abs() < EPS);
    assert!((sl_fill.executed_price - 1.0928).abs() < EPS);
    let trade = result
        .trades
        .iter()
        .find(|t| t.exit_reason == observa_core::types::ExitReason::StopLoss)
        .unwrap();
    assert!((trade.exit_price - 1.0928).abs() < EPS);
}

// ── H. Protective TP gap (favorable) ─────────────

#[test]
fn protective_tp_gap_is_favorable_no_slippage() {
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
        bar(1, 1.1005, 1.1010, 1.0995, 1.1000),
        bar(2, 1.1130, 1.1140, 1.1120, 1.1135), // open above TP 1.1100
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(1.0900),
        tp: Some(1.1100),
        reason: "buy with TP".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    let tp_fill = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::TakeProfit)
        .unwrap();
    assert!((tp_fill.executed_price - 1.1130).abs() < EPS);
    assert_eq!(tp_fill.slippage_applied, 0.0);
    assert_eq!(tp_fill.spread_applied, 0.0);
}

// ── I. Same-bar SL/TP → SL first ─────────────────

#[test]
fn same_bar_sl_tp_resolves_sl_first() {
    // SL = 1.0960, TP = 1.1050; the bar ranges over both (low 1.0950,
    // high 1.1060) → deterministic SL-first close.
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1000, 1.1060, 1.0950, 1.1000),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(1.0960),
        tp: Some(1.1050),
        reason: "both".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    // Entry on bar 1; same bar low reaches SL → SL-first close on bar 1.
    let sl_fill = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::StopLoss)
        .unwrap();
    assert!((sl_fill.raw_reference - 1.0960).abs() < EPS);
    assert!(result
        .fills
        .iter()
        .all(|f| f.reason != FillReason::TakeProfit));
    // SL exit price = 1.0960 - half spread - slippage.
    assert!((sl_fill.executed_price - (1.0960 - 0.0001 - 0.0001)).abs() < EPS);
}

// ── J/K. Multiple positions + hedging ────────────

#[test]
fn multiple_and_hedged_positions_are_independent() {
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1010, 1.1020, 1.1000, 1.1015),
        bar(2, 1.1020, 1.1030, 1.1010, 1.1025),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = OnceOnBar::new(
        0,
        vec![
            buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000)),
            StrategySignal {
                direction: Direction::Sell,
                order_type: OrderKind::Market,
                size: 0.5,
                intended_price: 0.0,
                sl: None,
                tp: None,
                reason: "short".to_string(),
                ticket: None,
            },
            buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000)),
        ],
    );
    let result = engine.run(&bars, &mut s).unwrap();
    // Three entries (1 long, 1 short, 1 long) at bar 1 open; all coexist.
    let entries: Vec<_> = result
        .fills
        .iter()
        .filter(|f| f.reason == FillReason::MarketEntry)
        .collect();
    assert_eq!(entries.len(), 3);
    let ids: std::collections::BTreeSet<_> =
        entries.iter().map(|f| f.position_id.unwrap()).collect();
    assert_eq!(ids.len(), 3);
    // End-of-run: all three still open (no closes emitted).
    assert_eq!(result.final_state.open_positions_remaining, 3);
    // Bar snapshots list all three.
    let last = result.bars.last().unwrap();
    assert_eq!(last.snapshot.open_positions.len(), 3);
}

// ── L. Margin rejection stays structured ────────

#[test]
fn margin_rejection_is_structured_and_creates_no_position() {
    // balance 1,000; 1 lot EURUSD @~1.10 requires 1,100 margin > free.
    let mut cfg = config(FillMode::NextBarOpen, None);
    cfg.account.starting_balance = 1_000.0;
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1000, 1.1010, 1.0990, 1.1000),
    ];
    let engine = Engine::new(cfg).unwrap();
    let mut s = OnceOnBar::new(0, vec![buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000))]);
    let result = engine.run(&bars, &mut s).unwrap();
    assert!(result.trades.is_empty());
    assert_eq!(result.final_state.open_positions_remaining, 0);
    let rejected = result
        .orders
        .iter()
        .find(|o| o.state == OrderState::Rejected)
        .expect("order must be recorded as rejected");
    assert!(
        rejected
            .rejection
            .as_deref()
            .unwrap()
            .contains("insufficient margin"),
        "rejection should be a financial (portfolio) rejection: {:?}",
        rejected.rejection
    );
}

// ── M. Order sequence strictly increasing ────────

#[test]
fn order_seq_is_strictly_increasing_and_deterministic() {
    let run = |shuffled: bool| -> Vec<u64> {
        let bars = vec![
            bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
            bar(1, 1.1010, 1.1020, 1.1000, 1.1010),
        ];
        let engine = Engine::new(config(FillMode::BarClose, None)).unwrap();
        let a = buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000));
        let b = StrategySignal {
            direction: Direction::Sell,
            ..buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000))
        };
        let c = buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000));
        let signals = if shuffled {
            vec![c, a, b]
        } else {
            vec![a, b, c]
        };
        let mut s = OnceOnBar::new(0, signals);
        let result = engine.run(&bars, &mut s).unwrap();
        result.orders.iter().map(|o| o.seq).collect()
    };
    // Sequences are 0,1,2 in BOTH signal orders (assigned in returned order).
    assert_eq!(run(false), vec![0, 1, 2]);
    assert_eq!(run(true), vec![0, 1, 2]);
}

// ── N. Strategy parameters reach initialization ───

#[test]
fn strategy_parameters_reach_initialization() {
    struct ParamCapture {
        params: Option<BTreeMap<String, serde_json::Value>>,
    }
    impl Strategy for ParamCapture {
        fn initialize_with_params(&mut self, params: Option<&BTreeMap<String, serde_json::Value>>) {
            self.params = params.cloned();
        }
        fn on_bar(
            &mut self,
            _bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            vec![]
        }
    }
    let mut cfg = config(FillMode::NextBarOpen, None);
    let mut params = BTreeMap::new();
    params.insert("period".to_string(), json!(5));
    cfg.strategy.as_mut().unwrap().parameters = params;

    let bars = vec![bar(0, 1.1, 1.11, 1.09, 1.105)];
    let engine = Engine::new(cfg).unwrap();
    let mut s = ParamCapture { params: None };
    let _ = engine.run(&bars, &mut s).unwrap();
    let got = s.params.expect("params must reach the strategy");
    assert_eq!(got.get("period"), Some(&json!(5)));
}

// ── O. Strategy failure surfaces as Engine error ──

#[test]
fn strategy_error_fails_the_run() {
    struct Failing;
    impl Strategy for Failing {
        fn on_bar(
            &mut self,
            _bar: &Bar,
            _portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            vec![]
        }
        fn take_strategy_error(&mut self) -> Option<String> {
            Some("strategy exploded".to_string())
        }
    }
    let bars = vec![bar(0, 1.1, 1.11, 1.09, 1.105)];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = Failing;
    let err = engine.run(&bars, &mut s).unwrap_err();
    match err {
        observa_engine::error::EngineError::StrategyFailure { message, .. } => {
            assert!(message.contains("strategy exploded"));
        }
        other => panic!("expected StrategyFailure, got {other:?}"),
    }
}

// ── P. End-of-run open position ──────────────────

#[test]
fn end_of_run_open_position_is_reported_not_liquidated() {
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1010, 1.1020, 1.1005, 1.1015),
        bar(2, 1.1030, 1.1040, 1.1020, 1.1035),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = OnceOnBar::new(0, vec![buy_signal(&bar(0, 1.1, 1.101, 1.099, 1.1000))]);
    let result = engine.run(&bars, &mut s).unwrap();
    assert_eq!(result.final_state.open_positions_remaining, 1);
    assert!(result.trades.is_empty());
    // Position entered at bar1 open (1.1010 + 0.0001 + 0.0001 = 1.1012);
    // final equity at 1.1035 includes unrealized gain.
    assert!((result.final_state.final_balance - 10_000.0).abs() < EPS);
    let expected_equity = 10_000.0 + (1.1035 - 1.1012) * 100_000.0;
    assert!((result.final_state.final_equity - expected_equity).abs() < 1e-3);
    assert!(result.final_state.final_equity > result.final_state.final_balance);
}

// ── Known-answer mini scenario (OBS-0007 §34) ────

#[test]
fn known_answer_next_bar_open_entry_then_tp_exit() {
    // balance 10,000; lev 100; contract 100k; spread .0002; slippage .0001
    // (half spread .0001); zero commission.
    // bar0: strategy BUY 1 lot (NEXT_BAR_OPEN)
    // bar1: open 1.1010 → entry 1.1012 (ref 1.1010 + .0001 + .0001)
    // bar2: open 1.1015, high 1.1025 ≥ TP 1.1020 → intrabar TP exit 1.1020
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1010, 1.1020, 1.1000, 1.1010),
        bar(2, 1.1015, 1.1025, 1.1005, 1.1022),
        bar(3, 1.1010, 1.1020, 1.1000, 1.1010),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(1.0990),
        tp: Some(1.1020),
        reason: "known answer".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    // Entry fill.
    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::MarketEntry)
        .unwrap();
    assert!((entry.executed_price - 1.1012).abs() < EPS);
    // TP exit.
    let tp = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::TakeProfit)
        .unwrap();
    assert!((tp.executed_price - 1.1020).abs() < EPS);
    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    // realized = (1.1020 - 1.1012) * 1 * 100,000 = 80
    assert!((trade.gross_realized_pnl - 80.0).abs() < EPS);
    assert!((trade.net_realized_pnl - 80.0).abs() < EPS);
    assert!((result.final_state.final_balance - 10_080.0).abs() < 1e-6);
    assert!((result.final_state.final_equity - 10_080.0).abs() < 1e-6);
    assert_eq!(result.final_state.open_positions_remaining, 0);
}

#[test]
fn explicit_close_uses_ticket_and_closes_exact_position() {
    // Strategy opens 2 longs on bar 0 (NEXT_BAR_OPEN fills bar 1), then on
    // bar 2 closes the SECOND ticket explicitly (close queues to bar 3 open).
    let bars = vec![
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1010, 1.1020, 1.1000, 1.1010),
        bar(2, 1.1015, 1.1025, 1.1005, 1.1020),
        bar(3, 1.1020, 1.1030, 1.1010, 1.1025),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();

    struct OpenTwoThenCloseSecond;
    impl Strategy for OpenTwoThenCloseSecond {
        fn on_bar(
            &mut self,
            bar: &Bar,
            portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            let first_call = portfolio.open_positions.is_empty();
            if first_call {
                let mut a = buy_signal(bar);
                let mut b = buy_signal(bar);
                b.size = 2.0;
                vec![a, b]
            } else if portfolio.open_positions.len() == 2 {
                // Close the most recent (second) ticket.
                let second = portfolio.open_positions[1].ticket.clone();
                vec![StrategySignal {
                    direction: Direction::Close,
                    order_type: OrderKind::Market,
                    size: portfolio.open_positions[1].size,
                    intended_price: 0.0,
                    sl: None,
                    tp: None,
                    reason: "close second".to_string(),
                    ticket: Some(second),
                }]
            } else {
                vec![]
            }
        }
    }

    let mut s = OpenTwoThenCloseSecond;
    let result = engine.run(&bars, &mut s).unwrap();
    assert_eq!(result.trades.len(), 1);
    assert_eq!(result.final_state.open_positions_remaining, 1);
    // The closed position was the 2-lot second entry.
    assert!((result.trades[0].quantity_lots - 2.0).abs() < EPS);
}

// ─────────────────────────────────────────────────
// OBS-0007 corrective regression tests
// ─────────────────────────────────────────────────

/// BUY LIMIT with attached TP: TP survives the pending lifecycle and closes
/// the position on a later eligible bar (correction #1).
#[test]
fn limit_preserves_tp_and_closes_later() {
    let bars = vec![
        bar(0, 1.1050, 1.1060, 1.1030, 1.1050),
        bar(1, 1.1040, 1.1045, 1.0990, 1.1010), // low <= 1.1000 -> fill at 1.1000
        bar(2, 1.1010, 1.1035, 1.1005, 1.1025), // high >= 1.1020 -> TP at 1.1020
        bar(3, 1.1000, 1.1010, 1.0990, 1.1005),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Limit,
        size: 1.0,
        intended_price: 1.1000,
        sl: Some(1.0950),
        tp: Some(1.1020),
        reason: "limit with tp".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    // Pending order filled with the original TP attached.
    let limit = result
        .orders
        .iter()
        .find(|o| o.order_type == OrderKind::Limit)
        .unwrap();
    assert_eq!(limit.state, OrderState::Filled);
    assert_eq!(limit.filled_bar, Some(1));

    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::LimitEntry)
        .unwrap();
    assert!((entry.executed_price - 1.1000).abs() < EPS);

    // TP later closes the position at the original level.
    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(
        trade.exit_reason,
        observa_core::types::ExitReason::TakeProfit
    );
    assert!((trade.exit_price - 1.1020).abs() < EPS);
    assert!((trade.gross_realized_pnl - 200.0).abs() < EPS);
    assert!((result.final_state.final_balance - 10_200.0).abs() < 1e-6);
}

/// BUY STOP with SL/TP: both levels survive the pending lifecycle (correction
/// #1) and the TP closes the position later.
#[test]
fn stop_preserves_sl_and_tp() {
    let bars = vec![
        bar(0, 1.0100, 1.0120, 1.0080, 1.0100), // create stop @1.0200
        bar(1, 1.0150, 1.0220, 1.0130, 1.0180), // intrabar trigger, fill raw 1.0200
        bar(2, 1.0700, 1.0820, 1.0690, 1.0800), // TP 1.0800 reachable
        bar(3, 1.0600, 1.0700, 1.0580, 1.0650),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Stop,
        size: 1.0,
        intended_price: 1.0200,
        sl: Some(0.9800),
        tp: Some(1.0800),
        reason: "stop with levels".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    assert_eq!(result.fills.len(), 2); // StopEntry + TakeProfit
    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::StopEntry)
        .unwrap();
    assert!((entry.executed_price - 1.0202).abs() < EPS);

    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(
        trade.exit_reason,
        observa_core::types::ExitReason::TakeProfit
    );
    assert!((trade.exit_price - 1.0800).abs() < EPS);
    // (1.0800 - 1.0202) * 1 * 100000 = 5980
    assert!((trade.gross_realized_pnl - 5980.0).abs() < EPS);
    assert!((result.final_state.final_balance - 15_980.0).abs() < 1e-6);
}

/// Direct no-silent-loss check: after a resting STOP fills, the position's
/// protective fields equal the original signal values (observed through the
/// read-only strategy view).
#[test]
fn resting_fill_position_levels_equal_signal() {
    struct Capture {
        emitted: bool,
        sl: Option<f64>,
        tp: Option<f64>,
    }
    impl Strategy for Capture {
        fn on_bar(
            &mut self,
            bar: &Bar,
            portfolio: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            if !self.emitted {
                self.emitted = true;
                return vec![StrategySignal {
                    direction: Direction::Buy,
                    order_type: OrderKind::Stop,
                    size: 1.0,
                    intended_price: 1.0200,
                    sl: Some(0.9800),
                    tp: Some(1.0800),
                    reason: "stop".to_string(),
                    ticket: None,
                }];
            }
            if let Some(first) = portfolio.open_positions.first() {
                self.sl = first.sl;
                self.tp = first.tp;
            }
            let _ = bar;
            vec![]
        }
    }
    let bars = vec![
        bar(0, 1.0100, 1.0120, 1.0080, 1.0100),
        bar(1, 1.0150, 1.0220, 1.0130, 1.0180), // trigger/fill
        bar(2, 1.0100, 1.0200, 1.0050, 1.0150), // observation bar for capture
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let mut s = Capture {
        emitted: false,
        sl: None,
        tp: None,
    };
    let result = engine.run(&bars, &mut s).unwrap();
    assert!(
        result
            .fills
            .iter()
            .any(|f| f.reason == FillReason::StopEntry),
        "expected the resting stop to fill"
    );
    assert_eq!(s.sl, Some(0.9800), "SL must survive pending lifecycle");
    assert_eq!(s.tp, Some(1.0800), "TP must survive pending lifecycle");
}

/// NEXT_BAR_OPEN entry filled at the open MAY be protected on the same bar
/// (chronology requirement A) — TP closes on the entry bar itself.
#[test]
fn next_bar_open_entry_can_tp_same_bar() {
    let bars = vec![
        bar(0, 1.0000, 1.0010, 0.9990, 1.0000), // strategy signals
        bar(1, 1.0000, 1.0060, 0.9990, 1.0055), // fill at open; TP 1.0050 reachable
        bar(2, 1.0000, 1.0010, 0.9990, 1.0005),
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(0.9900),
        tp: Some(1.0050),
        reason: "open entry".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();
    // Entry at bar1 open: 1.0000 + 0.0001 + 0.0001 = 1.0002.
    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::MarketEntry)
        .unwrap();
    assert!((entry.executed_price - 1.0002).abs() < EPS);
    // Same bar TP (high 1.0060 >= 1.0050) is legitimate for an open fill.
    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(trade.bar_index, 1);
    assert_eq!(
        trade.exit_reason,
        observa_core::types::ExitReason::TakeProfit
    );
    assert!((trade.exit_price - 1.0050).abs() < EPS);
    assert!((trade.gross_realized_pnl - 480.0).abs() < EPS);
}

/// LIMIT intrabar fill must NOT be retroactively stopped on the same bar even
/// if that bar's low crossed the SL (chronology requirement B).
#[test]
fn limit_intrabar_fill_not_same_bar_protected() {
    let bars = vec![
        bar(0, 1.0500, 1.0600, 1.0400, 1.0550), // create BUY LIMIT 1.0000 sl 0.9700
        bar(1, 1.0500, 1.1000, 0.9500, 1.0600), // fill at 1.0000; low 0.95 <= sl
        bar(2, 1.0100, 1.0200, 1.0005, 1.0150), // benign
        bar(3, 1.0050, 1.0100, 0.9600, 0.9800), // low <= 0.9700 -> SL (next bar)
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Limit,
        size: 1.0,
        intended_price: 1.0000,
        sl: Some(0.9700),
        tp: None,
        reason: "limit".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::LimitEntry)
        .unwrap();
    assert_eq!(entry.bar_index, 1);
    assert!((entry.executed_price - 1.0000).abs() < EPS);

    // No same-bar protective stop on bar 1 (low 0.95) — the intrabar-filled
    // position becomes eligible on the NEXT bar only.
    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(
        trade.bar_index, 3,
        "stop must occur on a later bar, not the fill bar"
    );
    assert_eq!(trade.exit_reason, observa_core::types::ExitReason::StopLoss);
    // SL exit: raw 0.9700, sell-adjusted by half-spread+slippage.
    assert!((trade.exit_price - 0.9698).abs() < EPS);
}

/// STOP intrabar fill must NOT be retroactively TP/SL'd on the same bar
/// (chronology requirement C).
#[test]
fn stop_intrabar_fill_not_same_bar_protected() {
    let bars = vec![
        bar(0, 1.0100, 1.0120, 1.0080, 1.0100), // create BUY STOP 1.0200 sl0.98 tp1.08
        bar(1, 1.0100, 1.0250, 0.9550, 1.0200), // intrabar trigger at 1.0200; low 0.955
        bar(2, 1.0200, 1.0300, 1.0150, 1.0250), // benign
        bar(3, 1.0400, 1.0850, 1.0300, 1.0800), // TP 1.0800 reachable (next bar)
    ];
    let engine = Engine::new(config(FillMode::NextBarOpen, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Stop,
        size: 1.0,
        intended_price: 1.0200,
        sl: Some(0.9800),
        tp: Some(1.0800),
        reason: "stop".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::StopEntry)
        .unwrap();
    assert_eq!(entry.bar_index, 1);
    assert!((entry.executed_price - 1.0202).abs() < EPS);

    // bar 1 low 0.955 <= SL and yet no same-bar stop/TP close occurs.
    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(
        trade.bar_index, 3,
        "protective exit must happen on a later bar"
    );
    assert_eq!(
        trade.exit_reason,
        observa_core::types::ExitReason::TakeProfit
    );
    assert!((trade.exit_price - 1.0800).abs() < EPS);
}

/// BAR_CLOSE market fill must NOT be protective-evaluated against the same
/// (already completed) bar's high/low (chronology requirement D).
#[test]
fn bar_close_no_retroactive_protective() {
    let bars = vec![
        bar(0, 1.1000, 1.1060, 1.0940, 1.1000), // strategy signal; fill at close
        bar(1, 1.1000, 1.1030, 1.0920, 1.0970), // SL 1.0950 reachable (next bar)
        bar(2, 1.1000, 1.1020, 1.1000, 1.1010),
    ];
    let engine = Engine::new(config(FillMode::BarClose, None)).unwrap();
    let signal = StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size: 1.0,
        intended_price: 0.0,
        sl: Some(1.0950),
        tp: Some(1.1050),
        reason: "close entry".to_string(),
        ticket: None,
    };
    let mut s = OnceOnBar::new(0, vec![signal]);
    let result = engine.run(&bars, &mut s).unwrap();

    // Entry at bar0 close: 1.1000 + 0.0002 = 1.1002 (bar0 high/low ignored).
    let entry = result
        .fills
        .iter()
        .find(|f| f.reason == FillReason::MarketEntry)
        .unwrap();
    assert_eq!(entry.bar_index, 0);
    assert!((entry.executed_price - 1.1002).abs() < EPS);

    assert_eq!(result.trades.len(), 1);
    let trade = &result.trades[0];
    assert_eq!(trade.bar_index, 1, "no retroactive close on the entry bar");
    assert_eq!(trade.exit_reason, observa_core::types::ExitReason::StopLoss);
    assert!((trade.exit_price - 1.0948).abs() < EPS);
}
