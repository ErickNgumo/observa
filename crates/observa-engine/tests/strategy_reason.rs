//! OBS-SCHEMA-01 — persisted strategy decision reasons.
//!
//! Exercises the canonical `strategy_decision.signals` payload end-to-end:
//! shape and index alignment, omission when no reason exists, verbatim text
//! preservation, the UTF-8 byte limit, all-or-nothing validation, survival
//! across order rejection, the signal→order invariant, and byte determinism.

use std::collections::BTreeMap;

use chrono::{DateTime, TimeZone, Utc};
use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig,
    StrategyConfig,
};
use observa_core::types::{Direction, OrderKind};
use observa_engine::engine::Engine;
use observa_engine::error::EngineError;
use observa_engine::persistence;
use observa_engine::runevents::{EngineEventPayload, SignalReason, MAX_STRATEGY_REASON_BYTES};
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use serde_json::Value;

// ── fixtures ────────────────────────────────────────────────────────────────

fn ts(i: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
}

fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
    Bar::new(ts(i), o, h, l, c, None)
}

fn fixture_bars() -> Vec<Bar> {
    vec![
        bar(0, 1.0, 1.0, 1.0, 1.0),
        bar(1, 1.5, 1.5, 1.5, 1.5),
        bar(2, 1.5, 1.5, 1.5, 1.5),
    ]
}

fn base_config(fill_mode: FillMode) -> BacktestConfig {
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
            spread: 0.0,
            slippage: 0.0,
            commission: CommissionConfig {
                mode: CommissionMode::PerSide,
                flat_per_fill: 0.0,
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
            name: "ReasonStrategy".to_string(),
            source: None,
            source_hash: None,
            parameters: BTreeMap::new(),
        }),
    }
}

fn open_signal(size: f64, reason: &str) -> StrategySignal {
    StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size,
        intended_price: 0.0,
        sl: None,
        tp: None,
        reason: reason.to_string(),
        ticket: None,
    }
}

fn open_signal_with_sl(size: f64, sl: f64, reason: &str) -> StrategySignal {
    StrategySignal {
        sl: Some(sl),
        ..open_signal(size, reason)
    }
}

fn close_signal(ticket: &str, size: f64, reason: &str) -> StrategySignal {
    StrategySignal {
        direction: Direction::Close,
        order_type: OrderKind::Market,
        size,
        intended_price: 0.0,
        sl: None,
        tp: None,
        reason: reason.to_string(),
        ticket: Some(ticket.to_string()),
    }
}

/// Emits a fixed signal list on one chosen bar, nothing elsewhere.
struct EmitOn {
    at: usize,
    signals: Vec<StrategySignal>,
    seen: usize,
}

impl Strategy for EmitOn {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        let i = self.seen;
        self.seen += 1;
        if i == self.at {
            self.signals.clone()
        } else {
            vec![]
        }
    }
}

/// Opens on bar 0, then on bar 1 emits: a close of that position, an invalid
/// (rejected) entry, and a valid entry — three signals, mixed outcomes.
struct MixedOutcomes {
    seen: usize,
    reason: &'static str,
}

impl Strategy for MixedOutcomes {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        let i = self.seen;
        self.seen += 1;
        if i == 0 {
            return vec![open_signal(1.0, "entry")];
        }
        if i == 1 {
            let ticket = view.open_positions.first().map(|p| p.ticket.clone());
            let mut out = vec![
                // rejected: invalid quantity
                open_signal(0.0, "rejected size"),
                // rejected later: invalid protective level for a long
                open_signal_with_sl(1.0, 9_999.0, "rejected sl"),
                // accepted
                open_signal(2.0, self.reason),
            ];
            if let Some(t) = ticket {
                // accepted close (prepended so the ordering is close-first)
                out.insert(0, close_signal(&t, 1.0, "exit"));
            }
            return out;
        }
        vec![]
    }
}

// ── helpers ─────────────────────────────────────────────────────────────────

fn decision_of<'a>(
    events: &'a [observa_engine::runevents::EngineEvent],
    bar_index: usize,
) -> &'a EngineEventPayload {
    events
        .iter()
        .map(|e| &e.payload)
        .find(|p| matches!(p, EngineEventPayload::StrategyDecision { bar_index: b, .. } if *b == bar_index))
        .expect("a strategy_decision for that bar")
}

fn reason_str(s: &SignalReason) -> Option<&str> {
    s.reason.as_deref()
}

// ── shape ───────────────────────────────────────────────────────────────────

#[test]
fn reason_is_persisted_verbatim() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(1.0, "price crossed above VWAP")],
                seen: 0,
            },
        )
        .unwrap();

    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision {
            signal_count,
            signals,
            ..
        } => {
            assert_eq!(*signal_count, 1);
            assert_eq!(signals.len(), 1);
            assert_eq!(signals[0].signal_index, 0);
            assert_eq!(reason_str(&signals[0]), Some("price crossed above VWAP"));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}

#[test]
fn signal_without_a_reason_omits_the_field() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(1.0, "")],
                seen: 0,
            },
        )
        .unwrap();

    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision {
            signal_count,
            signals,
            ..
        } => {
            assert_eq!(*signal_count, 1);
            assert!(signals.is_empty(), "no reason must omit the array");
        }
        other => panic!("unexpected payload {other:?}"),
    }

    // and the serialized event has no `signals` key at all
    let json = serde_json::to_value(decision_of(&result.events, 0)).unwrap();
    assert!(json.get("signals").is_none(), "got {json}");
    assert_eq!(json["signal_count"], 1);
}

#[test]
fn zero_signals_omit_the_field() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(&bars, &mut EmitOn { at: 0, signals: vec![], seen: 0 })
        .unwrap();

    let json = serde_json::to_value(decision_of(&result.events, 1)).unwrap();
    assert_eq!(json["signal_count"], 0);
    assert!(json.get("signals").is_none(), "got {json}");
}

#[test]
fn a_partly_reasoned_bar_omits_the_array() {
    // Two signals, neither with a reason → still omitted (not `[]`).
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(1.0, ""), open_signal(1.0, "")],
                seen: 0,
            },
        )
        .unwrap();

    let json = serde_json::to_value(decision_of(&result.events, 0)).unwrap();
    assert_eq!(json["signal_count"], 2);
    assert!(json.get("signals").is_none(), "got {json}");
}

#[test]
fn multiple_signals_are_dense_and_index_aligned() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![
                    open_signal(1.0, "first"),
                    open_signal(1.0, ""),
                    open_signal(1.0, "third"),
                ],
                seen: 0,
            },
        )
        .unwrap();

    let json = serde_json::to_value(decision_of(&result.events, 0)).unwrap();
    assert_eq!(json["signal_count"], 3);
    let signals = json["signals"].as_array().expect("signals array");
    assert_eq!(signals.len(), 3, "dense: one entry per signal");
    assert_eq!(signals[0]["signal_index"], 0);
    assert_eq!(signals[0]["reason"], "first");
    assert_eq!(signals[1]["signal_index"], 1);
    assert!(signals[1]["reason"].is_null(), "missing reason is JSON null");
    assert_eq!(signals[2]["signal_index"], 2);
    assert_eq!(signals[2]["reason"], "third");
}

#[test]
fn authored_text_is_preserved_exactly() {
    let text = "  spaced  \n line2\ttab \"quoted\" back\\slash é中文😀  ";
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(1.0, text)],
                seen: 0,
            },
        )
        .unwrap();

    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(reason_str(&signals[0]), Some(text));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}

// ── byte limit ──────────────────────────────────────────────────────────────

#[test]
fn reason_at_the_byte_limit_is_accepted() {
    let reason = "a".repeat(MAX_STRATEGY_REASON_BYTES);
    assert_eq!(reason.len(), 1024);
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn { at: 0, signals: vec![open_signal(1.0, &reason)], seen: 0 },
        )
        .unwrap();

    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(reason_str(&signals[0]).map(str::len), Some(1024));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}

#[test]
fn reason_over_the_byte_limit_is_rejected_with_details() {
    let reason = "a".repeat(MAX_STRATEGY_REASON_BYTES + 1);
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let err = engine
        .run(
            &bars,
            &mut EmitOn { at: 0, signals: vec![open_signal(1.0, &reason)], seen: 0 },
        )
        .unwrap_err();

    match err {
        EngineError::StrategyFailure {
            code, details, ..
        } => {
            assert_eq!(code.as_deref(), Some("STRATEGY_REASON_TOO_LONG"));
            let details = details.expect("details");
            assert_eq!(details["signal_index"], 0);
            assert_eq!(details["actual_bytes"], 1025);
            assert_eq!(details["max_bytes"], MAX_STRATEGY_REASON_BYTES);
        }
        other => panic!("unexpected error {other:?}"),
    }
}

#[test]
fn the_limit_counts_encoded_utf8_bytes_not_characters() {
    // 400 × '€' = 1200 encoded bytes, but only 400 characters.
    let reason = "€".repeat(400);
    assert_eq!(reason.chars().count(), 400);
    assert_eq!(reason.len(), 1200);
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let err = engine
        .run(
            &bars,
            &mut EmitOn { at: 0, signals: vec![open_signal(1.0, &reason)], seen: 0 },
        )
        .unwrap_err();
    match err {
        EngineError::StrategyFailure { code, details, .. } => {
            assert_eq!(code.as_deref(), Some("STRATEGY_REASON_TOO_LONG"));
            assert_eq!(details.unwrap()["actual_bytes"], 1200);
        }
        other => panic!("unexpected error {other:?}"),
    }

    // …and the same character count within the byte budget is accepted.
    let ok = "€".repeat(300); // 900 bytes
    assert!(ok.len() <= MAX_STRATEGY_REASON_BYTES);
    let mut engine = Engine::new(base_config(FillMode::BarClose)).unwrap();
    let result = engine
        .run(&bars, &mut EmitOn { at: 0, signals: vec![open_signal(1.0, &ok)], seen: 0 })
        .unwrap();
    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(reason_str(&signals[0]), Some(ok.as_str()));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}

// ── atomicity ───────────────────────────────────────────────────────────────

#[test]
fn an_invalid_reason_is_all_or_nothing() {
    // signal 0 is valid and would open a position; signal 1's reason is too long.
    let too_long = "x".repeat(MAX_STRATEGY_REASON_BYTES + 1);
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let err = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(1.0, "would be accepted"), open_signal(1.0, &too_long)],
                seen: 0,
            },
        )
        .unwrap_err();
    assert!(matches!(
        err,
        EngineError::StrategyFailure { ref code, .. } if code.as_deref() == Some("STRATEGY_REASON_TOO_LONG")
    ));

    // No partial decision and no economic side effect from signal 0.
    let events = engine.events();
    assert!(
        !events.iter().any(|e| matches!(
            e.payload,
            EngineEventPayload::StrategyDecision { .. }
        )),
        "the decision event must not be emitted on validation failure"
    );
    assert!(
        !events.iter().any(|e| matches!(
            e.payload,
            EngineEventPayload::OrderCreated { .. }
        )),
        "no order may be created from a partially validated callback"
    );
    assert!(
        !events.iter().any(|e| matches!(
            e.payload,
            EngineEventPayload::PositionOpened { .. } | EngineEventPayload::OrderFilled { .. }
        )),
        "no economic side effect is allowed"
    );
    // exactly one run_failed, and the failure is the reason message
    assert!(matches!(
        events.last().map(|e| &e.payload),
        Some(EngineEventPayload::RunFailed { .. })
    ));
}

// ── preservation across rejection, and the signal→order invariant ───────────

#[test]
fn a_rejected_order_still_carries_the_decision_reason() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut EmitOn {
                at: 0,
                signals: vec![open_signal(0.0, "sizing error, reason still mine")],
                seen: 0,
            },
        )
        .unwrap();

    // the order was created and then rejected…
    let rejected = result
        .events
        .iter()
        .any(|e| matches!(e.payload, EngineEventPayload::OrderRejected { .. }));
    assert!(rejected, "the order must be rejected");
    // …and the authored reason is still canonical on the decision
    match decision_of(&result.events, 0) {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(
                reason_str(&signals[0]),
                Some("sizing error, reason still mine")
            );
        }
        other => panic!("unexpected payload {other:?}"),
    }
    // reason is NOT attached to the rejection
    let rej_json = serde_json::to_value(
        result
            .events
            .iter()
            .find(|e| matches!(e.payload, EngineEventPayload::OrderRejected { .. }))
            .unwrap(),
    )
    .unwrap();
    assert!(rej_json.get("signals").is_none());
    assert!(rej_json.get("reason").is_some(), "the rejection keeps its own reason field");
}

#[test]
fn every_signal_produces_exactly_one_order_created_in_signal_order() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let result = engine
        .run(
            &bars,
            &mut MixedOutcomes {
                seen: 0,
                reason: "kept",
            },
        )
        .unwrap();

    // bar 0: one signal (the entry)
    // bar 1: four signals (close, rejected size, rejected sl, accepted)
    for (bar_index, expected) in [(0usize, 1usize), (1usize, 4usize)] {
        let signal_count = match decision_of(&result.events, bar_index) {
            EngineEventPayload::StrategyDecision { signal_count, .. } => *signal_count,
            other => panic!("unexpected payload {other:?}"),
        };
        let created: Vec<u64> = result
            .events
            .iter()
            .filter_map(|e| match &e.payload {
                EngineEventPayload::OrderCreated {
                    order_seq,
                    created_bar,
                    ..
                } if *created_bar == bar_index => Some(*order_seq),
                _ => None,
            })
            .collect();
        assert_eq!(
            signal_count, expected,
            "bar {bar_index}: signal_count must match the emitted signals"
        );
        assert_eq!(
            created.len(),
            expected,
            "bar {bar_index}: every signal must produce exactly one order_created"
        );
        // creation order is the signal order
        let mut sorted = created.clone();
        sorted.sort_unstable();
        assert_eq!(created, sorted, "order_created must follow signal order");
    }

    // the mixed bar really exercised both outcomes
    assert!(result
        .events
        .iter()
        .any(|e| matches!(e.payload, EngineEventPayload::OrderRejected { .. })));
    assert!(result
        .events
        .iter()
        .any(|e| matches!(e.payload, EngineEventPayload::OrderFilled { .. })));
    // and the accepted signal's reason survived alongside the rejected ones
    match decision_of(&result.events, 1) {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(signals.len(), 4);
            assert_eq!(reason_str(&signals[1]), Some("rejected size"));
            assert_eq!(reason_str(&signals[2]), Some("rejected sl"));
            assert_eq!(reason_str(&signals[3]), Some("kept"));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}

// ── determinism ─────────────────────────────────────────────────────────────

#[test]
fn repeated_runs_produce_byte_identical_reason_bytes() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let make = || {
        let mut engine = Engine::new(config.clone()).unwrap();
        engine
            .run(
                &bars,
                &mut EmitOn {
                    at: 0,
                    signals: vec![
                        open_signal(1.0, "deterministic reason"),
                        open_signal(1.0, "é中文😀"),
                    ],
                    seen: 0,
                },
            )
            .unwrap()
    };
    let (a, b) = (make(), make());

    let (ta, tb) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let (da, db) = (ta.path().join("a"), tb.path().join("b"));
    persistence::persist_completed_run(&da, &config, &bars, &a.events, &a, 24.0 * 252.0, "test.csv").unwrap();
    persistence::persist_completed_run(&db, &config, &bars, &b.events, &b, 24.0 * 252.0, "test.csv").unwrap();
    assert_eq!(
        std::fs::read(da.join("events.jsonl")).unwrap(),
        std::fs::read(db.join("events.jsonl")).unwrap(),
        "reason bytes must be byte-identical across identical runs"
    );
}

// ── historical compatibility ────────────────────────────────────────────────

#[test]
fn historical_decisions_without_the_field_still_deserialize() {
    // A pre-OBS-SCHEMA-01 strategy_decision line must load unchanged.
    let old = serde_json::json!({
        "event_seq": 3,
        "type": "strategy_decision",
        "bar_index": 0,
        "signal_count": 2
    });
    let ev: observa_engine::runevents::EngineEvent = serde_json::from_value(old).unwrap();
    match ev.payload {
        EngineEventPayload::StrategyDecision {
            signal_count,
            signals,
            ..
        } => {
            assert_eq!(signal_count, 2);
            assert!(signals.is_empty(), "absent field reads as empty");
        }
        other => panic!("unexpected payload {other:?}"),
    }

    // and a decision carrying the field round-trips
    let new: Value = serde_json::json!({
        "event_seq": 3,
        "type": "strategy_decision",
        "bar_index": 0,
        "signal_count": 1,
        "signals": [{"signal_index": 0, "reason": "kept"}]
    });
    let ev: observa_engine::runevents::EngineEvent = serde_json::from_value(new).unwrap();
    match ev.payload {
        EngineEventPayload::StrategyDecision { signals, .. } => {
            assert_eq!(reason_str(&signals[0]), Some("kept"));
        }
        other => panic!("unexpected payload {other:?}"),
    }
}
