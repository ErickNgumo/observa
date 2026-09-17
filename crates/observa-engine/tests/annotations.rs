//! OBS-AI-02 — canonical strategy annotation tests (engine level).
//!
//! Annotations are descriptive only. These tests lock in:
//!
//! * `drawings_emitted` is emitted **only** when a strategy returned at least
//!   one instruction (no-drawing runs stay byte-identical),
//! * the event sits between `strategy_decision` and that bar's order events,
//! * `event_seq` stays dense,
//! * drawing events are persisted and reconstructable, including from failure
//!   artifacts,
//! * annotations never change fills, positions or final economics.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, TimeZone, Utc};
use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig,
    StrategyConfig,
};
use observa_core::drawings::{
    DrawingAction, DrawingInstruction, DrawingKind, HLineDrawing, LabelDrawing, LabelPosition,
    LineDrawing, LineStyle, MarkerDrawing, RectangleDrawing,
};
use observa_core::types::Direction;
use observa_engine::engine::Engine;
use observa_engine::error::EngineError;
use observa_engine::persistence;
use observa_engine::replay;
use observa_engine::runevents::{EngineEvent, EngineEventPayload};
use observa_engine::strategy::{PortfolioView, Strategy, StrategyFailure, StrategySignal};

fn ts(i: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
}

fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
    Bar::new(ts(i), o, h, l, c, None)
}

fn config() -> BacktestConfig {
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
            fill_mode: FillMode::BarClose,
            spread: 0.0002,
            slippage: 0.0001,
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
            name: "AnnotationStrategy".to_string(),
            source: None,
            source_hash: None,
            parameters: BTreeMap::new(),
        }),
    }
}

fn hline(id: &str, _time: DateTime<Utc>, price: f64) -> DrawingInstruction {
    DrawingInstruction {
        id: id.to_string(),
        action: DrawingAction::Add,
        kind: Some(DrawingKind::Hline(HLineDrawing {
            price,
            color: "#d29922".to_string(),
            line_style: LineStyle::Dashed,
            width: 1,
            label: None,
        })),
    }
}

fn zone(id: &str, start: DateTime<Utc>, top: f64, bot: f64) -> DrawingInstruction {
    DrawingInstruction {
        id: id.to_string(),
        action: DrawingAction::Add,
        kind: Some(DrawingKind::Rectangle(RectangleDrawing {
            time_start: start.to_rfc3339(),
            time_end: None,
            price_top: top,
            price_bot: bot,
            color: "#3fb950".to_string(),
            opacity: Some(0.14),
            border: Some("#3fb950".to_string()),
            label: None,
        })),
    }
}

fn note(id: &str, time: DateTime<Utc>, price: f64, text: &str) -> DrawingInstruction {
    DrawingInstruction {
        id: id.to_string(),
        action: DrawingAction::Add,
        kind: Some(DrawingKind::Label(LabelDrawing {
            time: time.to_rfc3339(),
            price,
            text: text.to_string(),
            color: "#f85149".to_string(),
            position: LabelPosition::Below,
        })),
    }
}

/// Buys on the first bar and optionally emits annotations every bar.
struct Annotator {
    emit: bool,
    bought: bool,
    fail_at: Option<usize>,
    seen: usize,
    error: Option<StrategyFailure>,
    pending: Vec<DrawingInstruction>,
}

impl Annotator {
    fn new(emit: bool) -> Self {
        Self {
            emit,
            bought: false,
            fail_at: None,
            seen: 0,
            error: None,
            pending: Vec::new(),
        }
    }
}

impl Strategy for Annotator {
    fn on_bar(
        &mut self,
        bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        let index = self.seen;
        self.seen += 1;
        if Some(index) == self.fail_at {
            self.error = Some(StrategyFailure::new("scripted strategy failure"));
            return vec![];
        }
        if self.emit {
            self.pending = vec![
                hline("level", bar.timestamp, bar.close),
                zone("zone", bar.timestamp, bar.high, bar.low),
                note("note", bar.timestamp, bar.low, "signal"),
            ];
        }
        if !self.bought {
            self.bought = true;
            return vec![StrategySignal {
                direction: Direction::Buy,
                order_type: observa_core::types::OrderKind::Market,
                size: 1.0,
                intended_price: bar.close,
                sl: None,
                tp: None,
                reason: "entry".to_string(),
                ticket: None,
            }];
        }
        vec![]
    }

    fn take_drawings(&mut self) -> Vec<DrawingInstruction> {
        std::mem::take(&mut self.pending)
    }

    fn take_strategy_error(&mut self) -> Option<StrategyFailure> {
        self.error.take()
    }
}

fn run(emit: bool) -> (Vec<Bar>, observa_engine::engine::RunResult) {
    let bars: Vec<Bar> = (0..4)
        .map(|i| {
            let base = 1.1000 + i as f64 * 0.001;
            bar(i, base, base + 0.0005, base - 0.0005, base + 0.0002)
        })
        .collect();
    let mut engine = Engine::new(config()).unwrap();
    let result = engine.run(&bars, &mut Annotator::new(emit)).unwrap();
    (bars, result)
}

fn drawing_events(events: &[EngineEvent]) -> Vec<&EngineEvent> {
    events
        .iter()
        .filter(|e| matches!(e.payload, EngineEventPayload::DrawingsEmitted { .. }))
        .collect()
}

fn tag(e: &EngineEvent) -> &'static str {
    match &e.payload {
        EngineEventPayload::BarProcessed { .. } => "bar_processed",
        EngineEventPayload::StrategyDecision { .. } => "strategy_decision",
        EngineEventPayload::DrawingsEmitted { .. } => "drawings_emitted",
        EngineEventPayload::OrderCreated { .. } => "order_created",
        EngineEventPayload::OrderPending { .. } => "order_pending",
        EngineEventPayload::OrderFilled { .. } => "order_filled",
        EngineEventPayload::PositionOpened { .. } => "position_opened",
        _ => "other",
    }
}

#[test]
fn drawings_emitted_only_when_non_empty() {
    let (_, quiet) = run(false);
    assert!(
        drawing_events(&quiet.events).is_empty(),
        "a strategy that draws nothing must add no drawing events"
    );

    let (_, drawing) = run(true);
    assert_eq!(
        drawing_events(&drawing.events).len(),
        4,
        "one drawing event per bar that returned annotations"
    );
}

#[test]
fn no_drawing_run_event_count_is_unchanged() {
    // A run that draws nothing must contain exactly the events it contained
    // before OBS-AI-02: the annotated run differs only by its drawing events.
    let (_, quiet) = run(false);
    let (_, drawing) = run(true);
    assert!(drawing_events(&quiet.events).is_empty());
    assert_eq!(
        drawing.events.len(),
        quiet.events.len() + 4,
        "annotations add exactly one event per annotated bar and nothing else"
    );
    // Every non-drawing event is unchanged, in the same order.
    let quiet_tags: Vec<String> = quiet
        .events
        .iter()
        .map(|e| format!("{}", serde_json::to_value(&e.payload).unwrap()["type"]))
        .collect();
    let drawing_tags: Vec<String> = drawing
        .events
        .iter()
        .filter(|e| !matches!(e.payload, EngineEventPayload::DrawingsEmitted { .. }))
        .map(|e| format!("{}", serde_json::to_value(&e.payload).unwrap()["type"]))
        .collect();
    assert_eq!(quiet_tags, drawing_tags, "non-drawing event stream unchanged");
}

#[test]
fn drawing_event_order_is_decision_then_drawings_then_orders() {
    let (_, result) = run(true);
    let bar0: Vec<&EngineEvent> = result
        .events
        .iter()
        .filter(|e| match &e.payload {
            EngineEventPayload::BarProcessed { bar_index, .. } => *bar_index == 0,
            EngineEventPayload::StrategyDecision { bar_index, .. } => *bar_index == 0,
            EngineEventPayload::DrawingsEmitted { bar_index, .. } => *bar_index == 0,
            EngineEventPayload::OrderCreated { created_bar, .. } => *created_bar == 0,
            _ => false,
        })
        .collect();
    let tags: Vec<&str> = bar0.iter().map(|e| tag(e)).collect();
    assert_eq!(
        tags,
        vec![
            "bar_processed",
            "strategy_decision",
            "drawings_emitted",
            "order_created"
        ],
        "drawings must follow strategy_decision and precede order processing"
    );
}

#[test]
fn event_seq_stays_dense_with_drawing_events() {
    let (_, result) = run(true);
    let seqs: Vec<u64> = result.events.iter().map(|e| e.event_seq).collect();
    assert_eq!(
        seqs,
        (0..seqs.len() as u64).collect::<Vec<u64>>(),
        "event_seq must be dense 0..n-1"
    );
}

#[test]
fn annotations_do_not_change_economics() {
    let (_, quiet) = run(false);
    let (_, drawing) = run(true);

    assert_eq!(quiet.total_bars, drawing.total_bars);
    assert_eq!(quiet.fills.len(), drawing.fills.len());
    assert_eq!(quiet.orders.len(), drawing.orders.len());
    assert_eq!(quiet.trades.len(), drawing.trades.len());
    assert_eq!(
        quiet.final_state.final_balance,
        drawing.final_state.final_balance
    );
    assert_eq!(
        quiet.final_state.final_equity,
        drawing.final_state.final_equity
    );
    assert_eq!(
        quiet.final_state.open_positions_remaining,
        drawing.final_state.open_positions_remaining
    );
}

#[test]
fn drawings_round_trip_through_persisted_artifacts() {
    let (bars, result) = run(true);
    let dir = tempdir("annotations-roundtrip").join("run");
    persistence::persist_completed_run(
        &dir,
        &config(),
        &bars,
        &result.events,
        &result,
        252.0,
        "test.csv",
    )
    .unwrap();

    let loaded = replay::load_persisted_run(&dir).unwrap();
    assert_eq!(loaded.events.len(), result.events.len(), "no event loss");

    let in_process = replay::drawings_by_bar(bars.len(), &result.events);
    let persisted = replay::drawings_by_bar(bars.len(), &loaded.events);
    assert!(in_process.iter().all(|d| d.len() == 3), "3 instructions per bar");

    // NOTE: values are compared with a tiny numeric tolerance. serde_json
    // 1.0.151's float *parser* is off by one ulp for some literals (e.g.
    // "1.0995000000000001" parses to the neighbouring double), so a persisted
    // f64 can differ from the in-process original in the last bit. All other
    // structure must match exactly.
    assert!(
        json_close(&serde_json::to_value(&in_process).unwrap(), &serde_json::to_value(&persisted).unwrap()),
        "persisted drawings must match in-process drawings: {in_process:?} vs {persisted:?}"
    );

    // The replay payload for both paths must be equivalent too.
    let meta_a = replay::run_meta_from_run_json(&serde_json::json!({ "status": "completed" }));
    let payload_in_process = replay::replay_payload(&bars, &result.events, &meta_a, None);
    let payload_persisted = replay::replay_payload(&bars, &loaded.events, &meta_a, None);
    assert!(
        json_close(&payload_in_process["drawings"], &payload_persisted["drawings"]),
        "payload drawings are derived from canonical events on both paths"
    );
    assert_eq!(payload_persisted["drawings"].as_array().unwrap().len(), 4);
    assert_eq!(
        payload_persisted["drawings"][0].as_array().unwrap().len(),
        3,
        "drawings are index-aligned with bars"
    );

    fs::remove_dir_all(&dir).ok();
}

#[test]
fn failure_artifacts_preserve_prior_drawing_events() {
    let bars: Vec<Bar> = (0..4)
        .map(|i| {
            let base = 1.1000 + i as f64 * 0.001;
            bar(i, base, base + 0.0005, base - 0.0005, base + 0.0002)
        })
        .collect();
    let mut strategy = Annotator::new(true);
    strategy.fail_at = Some(2);
    let mut engine = Engine::new(config()).unwrap();
    let error = engine.run(&bars, &mut strategy).unwrap_err();

    // Partial canonical history stays on the engine for failure persistence.
    let events = engine.events().to_vec();
    let drawings = replay::drawings_by_bar(bars.len(), &events);
    assert_eq!(drawings[0].len(), 3, "bar 0 annotations survive the failure");
    assert_eq!(drawings[1].len(), 3, "bar 1 annotations survive the failure");
    assert!(drawings[2].is_empty(), "the failing bar emitted nothing");
    assert!(format!("{error}").contains("scripted strategy failure"));
}

/// Bar timestamps for the future-timestamp test (free functions so the
/// closures below stay `'static`).
fn draw_ts_unix(i: i64) -> i64 {
    1_700_000_000 + i * 900
}

fn draw_ts(i: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(draw_ts_unix(i), 0).unwrap()
}

#[test]
fn future_bar_drawing_timestamps_are_rejected() {
    // At bar N: N and N-1 are accepted; N+1 and N+50 are rejected even though
    // both are real bar timestamps in the dataset. `time_end: None` stays
    // valid because it names no timestamp (extend-right as replay advances).
    const BARS: usize = 60;
    let bars: Vec<Bar> = (0..BARS)
        .map(|i| {
            let base = 1.1000 + (i as f64) * 0.0001;
            bar(i as i64, base, base + 0.0005, base - 0.0005, base + 0.0002)
        })
        .collect();

    struct Annotating {
        make: Box<dyn Fn(&Bar) -> Vec<DrawingInstruction>>,
        seen: usize,
        pending: Vec<DrawingInstruction>,
    }
    impl Strategy for Annotating {
        fn on_bar(
            &mut self,
            bar: &Bar,
            _view: &PortfolioView,
            _history: &[Bar],
        ) -> Vec<StrategySignal> {
            let index = self.seen;
            self.seen += 1;
            if index == 1 {
                self.pending = (self.make)(bar);
            }
            vec![]
        }
        fn take_drawings(&mut self) -> Vec<DrawingInstruction> {
            std::mem::take(&mut self.pending)
        }
    }

    fn run_with(
        bars: &[Bar],
        make: Box<dyn Fn(&Bar) -> Vec<DrawingInstruction>>,
    ) -> Result<(), EngineError> {
        let mut engine = Engine::new(config()).unwrap();
        let mut strategy = Annotating {
            make,
            seen: 0,
            pending: Vec::new(),
        };
        engine.run(bars, &mut strategy).map(|_| ())
    }


    // accepted: current bar N and previous bar N-1
    assert!(run_with(&bars, Box::new(move |b| vec![note("n_now", b.timestamp, 1.1, "x")])).is_ok());
    assert!(run_with(&bars, Box::new(move |_b| vec![note("n_prev", draw_ts(0), 1.1, "x")])).is_ok());
    // accepted: extend-right rectangle (no timestamp)
    assert!(run_with(
        &bars,
        Box::new(move |b| vec![DrawingInstruction {
            id: "z".to_string(),
            action: DrawingAction::Add,
            kind: Some(DrawingKind::Rectangle(RectangleDrawing {
                time_start: b.timestamp.to_rfc3339(),
                time_end: None,
                price_top: 1.2,
                price_bot: 1.1,
                color: "#3fb950".to_string(),
                opacity: None,
                border: None,
                label: None,
            })),
        }])
    )
    .is_ok());

    fn expect_future(err: EngineError, label: &str) {
        match err {
            EngineError::StrategyFailure {
                code,
                message,
                bar_index,
                ..
            } => {
                assert_eq!(code.as_deref(), Some("DRAWING_TIME_INVALID"), "{label}: {message}");
                assert!(
                    message.contains("future bar"),
                    "{label}: expected a future-bar message, got: {message}"
                );
                assert_eq!(bar_index, Some(1), "{label}");
            }
            other => panic!("{label}: expected a strategy failure, got {other}"),
        }
    }

    // rejected: one bar ahead (N+1, a real dataset bar)
    expect_future(
        run_with(&bars, Box::new(move |_b| vec![note("n_next", draw_ts(2), 1.1, "x")])).unwrap_err(),
        "N+1 label",
    );
    // rejected: far ahead (N+50, also a real dataset bar)
    expect_future(
        run_with(&bars, Box::new(move |_b| vec![note("n_far", draw_ts(51), 1.1, "x")])).unwrap_err(),
        "N+50 label",
    );
    // rejected: future marker
    expect_future(
        run_with(
            &bars,
            Box::new(move |_b| vec![DrawingInstruction {
                id: "m".to_string(),
                action: DrawingAction::Add,
                kind: Some(DrawingKind::Marker(MarkerDrawing {
                    time: draw_ts(2).to_rfc3339(),
                    position: Default::default(),
                    shape: Default::default(),
                    color: "#3fb950".to_string(),
                    text: None,
                })),
            }]),
        )
        .unwrap_err(),
        "N+1 marker",
    );
    // rejected: future line endpoint (x2)
    expect_future(
        run_with(
            &bars,
            Box::new(move |b| vec![DrawingInstruction {
                id: "t".to_string(),
                action: DrawingAction::Add,
                kind: Some(DrawingKind::Line(LineDrawing {
                    x1: b.timestamp.to_rfc3339(),
                    y1: 1.1,
                    x2: draw_ts(51).to_rfc3339(),
                    y2: 1.2,
                    color: "#8957e5".to_string(),
                    line_style: LineStyle::Solid,
                    width: 1,
                })),
            }]),
        )
        .unwrap_err(),
        "future line x2",
    );
    // rejected: future region end
    expect_future(
        run_with(
            &bars,
            Box::new(move |b| vec![DrawingInstruction {
                id: "g".to_string(),
                action: DrawingAction::Add,
                kind: Some(DrawingKind::Region(observa_core::drawings::RegionDrawing {
                    time_start: b.timestamp.to_rfc3339(),
                    time_end: draw_ts(10).to_rfc3339(),
                    color: "#58a6ff".to_string(),
                    opacity: None,
                    label: None,
                })),
            }]),
        )
        .unwrap_err(),
        "future region end",
    );
    // rejected: a timestamp that is not in the dataset at all
    let missing = run_with(
        &bars,
        Box::new(move |_b| vec![note("n_missing", Utc.timestamp_opt(1_800_000_000, 0).unwrap(), 1.1, "x")]),
    )
    .unwrap_err();
    match missing {
        EngineError::StrategyFailure { code, .. } => {
            assert_eq!(code.as_deref(), Some("DRAWING_TIME_INVALID"))
        }
        other => panic!("expected a strategy failure, got {other}"),
    }
}

// ── helpers ─────────────────────────────────────

/// Structural equality with a relative tolerance on numbers (see the note in
/// `drawings_round_trip_through_persisted_artifacts`).
fn json_close(a: &serde_json::Value, b: &serde_json::Value) -> bool {
    match (a, b) {
        (serde_json::Value::Number(x), serde_json::Value::Number(y)) => {
            let (x, y) = (x.as_f64().unwrap(), y.as_f64().unwrap());
            (x - y).abs() <= 1e-12 * x.abs().max(y.abs()).max(1.0)
        }
        (serde_json::Value::Array(x), serde_json::Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(a, b)| json_close(a, b))
        }
        (serde_json::Value::Object(x), serde_json::Value::Object(y)) => {
            x.len() == y.len()
                && x.iter()
                    .all(|(k, v)| y.get(k).map(|w| json_close(v, w)).unwrap_or(false))
        }
        _ => a == b,
    }
}

fn tempdir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("observa-{name}-{}", std::process::id()));
    fs::remove_dir_all(&dir).ok();
    fs::create_dir_all(&dir).unwrap();
    dir
}

#[allow(dead_code)]
fn assert_path(path: &Path) -> &Path {
    path
}
