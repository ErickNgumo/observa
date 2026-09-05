//! OBS-0008 run persistence & deterministic-verification integration tests.
//!
//! These tests exercise the canonical Engine's event history end-to-end:
//!   * artifact persistence (`run.json` / `events.jsonl` / `metrics.json`);
//!   * EventSeq ordering and structural invariants;
//!   * known-answer economics (hand-derived from OBS-0005/6 contracts);
//!   * repeated-run determinism (UUID-normalized byte comparisons);
//!   * dataset / strategy content-hash sensitivity;
//!   * no-silent-overwrite and failure artifacts.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use chrono::{DateTime, TimeZone, Utc};
use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig as CoreExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig,
    StrategyConfig,
};
use observa_core::types::{Direction, OrderKind, OrderState};
use observa_engine::engine::{Engine, RunResult};
use observa_engine::persistence::{self, PersistenceError};
use observa_engine::runevents::{EngineEvent, EngineEventPayload, RejectionCategory};
use observa_engine::sha256::Sha256;
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};
use serde_json::Value;

const EPS: f64 = 1e-9;

fn ts(i: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
}

fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
    Bar::new(ts(i), o, h, l, c, None)
}

/// Exact-binary-price fixture: bar0 close 1.0, bar1 close 1.5 — all
/// arithmetic (×100k contract) is exact, giving hand-derivable answers.
fn fixture_bars() -> Vec<Bar> {
    vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.5, 1.5, 1.5, 1.5)]
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
            name: "TestStrategy".to_string(),
            source: None,
            source_hash: None,
            parameters: BTreeMap::new(),
        }),
    }
}

fn buy_signal(bar: &Bar, size: f64) -> StrategySignal {
    StrategySignal {
        direction: Direction::Buy,
        order_type: OrderKind::Market,
        size,
        intended_price: bar.close,
        sl: None,
        tp: None,
        reason: "buy".to_string(),
        ticket: None,
    }
}

fn close_signal(bar: &Bar, ticket: &str, size: f64) -> StrategySignal {
    StrategySignal {
        direction: Direction::Close,
        order_type: OrderKind::Market,
        size,
        intended_price: bar.close,
        sl: None,
        tp: None,
        reason: "close".to_string(),
        ticket: Some(ticket.to_string()),
    }
}

/// Buys once on bar 0 (BAR_CLOSE fills), then closes that position from the
/// portfolio view as soon as it appears (bar 1).
struct BuyThenCloseFromView {
    bought: bool,
    closing: bool,
    size: f64,
}

impl Strategy for BuyThenCloseFromView {
    fn on_bar(&mut self, bar: &Bar, view: &PortfolioView, _history: &[Bar]) -> Vec<StrategySignal> {
        if !self.bought {
            self.bought = true;
            return vec![buy_signal(bar, self.size)];
        }
        if !self.closing {
            if let Some(p) = view.open_positions.first() {
                self.closing = true;
                return vec![close_signal(bar, &p.ticket, p.size)];
            }
        }
        vec![]
    }
}

/// Buys once on bar 0 and holds to dataset end.
struct BuyAndHold {
    bought: bool,
    size: f64,
}

impl Strategy for BuyAndHold {
    fn on_bar(
        &mut self,
        bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        if !self.bought {
            self.bought = true;
            return vec![buy_signal(bar, self.size)];
        }
        vec![]
    }
}

/// Never signals.
struct Noop;
impl Strategy for Noop {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        vec![]
    }
}

/// Fails (structured strategy error) on the `fail_after`-th `on_bar` call.
struct FailAfter {
    seen: usize,
    fail_after: usize,
    error: Option<String>,
}

impl Strategy for FailAfter {
    fn on_bar(
        &mut self,
        _bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        let seen = self.seen;
        self.seen += 1;
        if seen >= self.fail_after {
            self.error = Some(format!("scripted failure at call {seen}"));
        }
        vec![]
    }

    fn take_strategy_error(&mut self) -> Option<String> {
        self.error.take()
    }
}

// ── Artifact reading helpers ────────────────────

fn read_run_json(dir: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(dir.join("run.json")).unwrap()).unwrap()
}

fn read_events(dir: &Path) -> Vec<Value> {
    fs::read_to_string(dir.join("events.jsonl"))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn read_metrics(dir: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(dir.join("metrics.json")).unwrap()).unwrap()
}

/// Snake-case event type tag (matches the persisted `"type"` discriminator).
fn event_tag(payload: &EngineEventPayload) -> &'static str {
    match payload {
        EngineEventPayload::RunStarted { .. } => "run_started",
        EngineEventPayload::RunCompleted { .. } => "run_completed",
        EngineEventPayload::RunFailed { .. } => "run_failed",
        EngineEventPayload::StrategyInitialized { .. } => "strategy_initialized",
        EngineEventPayload::StrategyError { .. } => "strategy_error",
        EngineEventPayload::StrategyTeardown { .. } => "strategy_teardown",
        EngineEventPayload::BarProcessed { .. } => "bar_processed",
        EngineEventPayload::StrategyDecision { .. } => "strategy_decision",
        EngineEventPayload::OrderCreated { .. } => "order_created",
        EngineEventPayload::OrderPending { .. } => "order_pending",
        EngineEventPayload::OrderTriggered { .. } => "order_triggered",
        EngineEventPayload::OrderFilled { .. } => "order_filled",
        EngineEventPayload::OrderRejected { .. } => "order_rejected",
        EngineEventPayload::OrderExpired { .. } => "order_expired",
        EngineEventPayload::PositionOpened { .. } => "position_opened",
        EngineEventPayload::PositionClosed { .. } => "position_closed",
        EngineEventPayload::PortfolioSnapshot { .. } => "portfolio_snapshot",
    }
}

/// Deterministic-normalized event value: economics are deterministic, but
/// position tickets are random UUIDs; drop them so two runs compare cleanly.
fn normalized_event(v: &Value) -> Value {
    let mut v = v.clone();
    if let Value::Object(map) = &mut v {
        map.remove("position_id");
    }
    v
}

fn run_once(bars: &[Bar], config: &BacktestConfig, strategy: &mut dyn Strategy) -> RunResult {
    let mut engine = Engine::new(config.clone()).unwrap();
    engine.run(bars, strategy).unwrap()
}

fn persist(dir: &Path, result: &RunResult, bars: &[Bar], config: &BacktestConfig) {
    persistence::persist_completed_run(
        dir,
        config,
        bars,
        &result.events,
        result,
        24.0 * 252.0,
        "test.csv",
    )
    .unwrap();
}

// ── 1. Known-answer persistence ─────────────────

#[test]
fn known_answer_run_persists_canonical_artifacts() {
    // Buy at bar0 close 1.0, close at bar1 close 1.5, no costs:
    //   gross = (1.5 − 1.0) × 100 000 × 1 = +50 000; net = +50 000.
    //   final balance = 60 000, final equity = 60 000, 1 trade.
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("run-ka");
    let result = run_once(
        &bars,
        &config,
        &mut BuyThenCloseFromView {
            bought: false,
            closing: false,
            size: 1.0,
        },
    );

    persist(&dir, &result, &bars, &config);

    // events.jsonl — one canonical event per line, all parse.
    let events = read_events(&dir);
    assert_eq!(events.len(), result.events.len());

    // run.json — resolved config + reproducibility + economics.
    let run_json = read_run_json(&dir);
    assert_eq!(run_json["run_schema_version"], 1);
    assert_eq!(run_json["status"], "completed");
    assert_eq!(run_json["dataset"]["source"], "test.csv");
    assert_eq!(run_json["dataset"]["bar_count"], 2);
    assert_eq!(run_json["event_count"], events.len() as u64);
    let balance = run_json["config"]["account"]["starting_balance"]
        .as_f64()
        .unwrap();
    assert!((balance - 10_000.0).abs() < EPS);
    assert_eq!(run_json["strategy"]["name"], "TestStrategy");
    assert!((run_json["final_balance"].as_f64().unwrap() - 60_000.0).abs() < EPS);
    assert!((run_json["final_equity"].as_f64().unwrap() - 60_000.0).abs() < EPS);
    assert_eq!(run_json["open_positions_remaining"], 0);

    // metrics.json — derived, never authoritative, present on success.
    let metrics = read_metrics(&dir);
    assert_eq!(metrics["metrics_schema_version"], 1);
    assert_eq!(metrics["total_trades"], 1);
    assert_eq!(metrics["winning_trades"], 1);
    assert!((metrics["final_balance"].as_f64().unwrap() - 60_000.0).abs() < EPS);
    assert!((metrics["final_equity"].as_f64().unwrap() - 60_000.0).abs() < EPS);
    assert_eq!(metrics["open_positions_remaining"], 0);

    // Dataset identity is recorded and recomputable through the public API.
    let identity = persistence::dataset_identity(&bars).unwrap();
    assert_eq!(run_json["dataset"]["sha256"], identity.sha256);
    assert!(run_json["dataset"]["first_timestamp"]
        .as_str()
        .unwrap()
        .starts_with("2023-11-14T"));
}

// ── 2. Event sequence invariants ────────────────

#[test]
fn event_seq_strictly_increasing_with_expected_choreography() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let result = run_once(
        &bars,
        &config,
        &mut BuyThenCloseFromView {
            bought: false,
            closing: false,
            size: 1.0,
        },
    );

    let events = &result.events;
    assert_eq!(events.first().unwrap().event_seq, 0);
    for (i, ev) in events.iter().enumerate() {
        assert_eq!(ev.event_seq as usize, i, "EventSeq must be dense 0..n");
    }

    let types: Vec<&str> = events.iter().map(|e| event_tag(&e.payload)).collect();
    assert_eq!(types.first().unwrap().to_string(), "run_started");
    assert_eq!(types.last().unwrap().to_string(), "run_completed");

    // Hand-derived choreography for the closed-trade fixture (15 events):
    // run_started, strategy_initialized,
    // bar0: bar_processed, strategy_decision, order_created, order_filled,
    //       position_opened, portfolio_snapshot,
    // bar1: bar_processed, strategy_decision, order_created, order_filled,
    //       position_closed, portfolio_snapshot,
    // run_completed.
    assert_eq!(types.len(), 15, "actual types: {types:?}");
    assert_eq!(
        types,
        vec![
            "run_started",
            "strategy_initialized",
            "bar_processed",
            "strategy_decision",
            "order_created",
            "order_filled",
            "position_opened",
            "portfolio_snapshot",
            "bar_processed",
            "strategy_decision",
            "order_created",
            "order_filled",
            "position_closed",
            "portfolio_snapshot",
            "run_completed",
        ]
    );

    // Order-level invariants: created precedes filled; bar work is preceded
    // by the bar's BarProcessed.
    let order_created_at = |seq: u64| {
        events
            .iter()
            .position(|e| {
                matches!(&e.payload, EngineEventPayload::OrderCreated { order_seq, .. } if *order_seq == seq)
            })
            .unwrap()
    };
    let order_filled_at = |seq: u64| {
        events
            .iter()
            .position(|e| {
                matches!(&e.payload, EngineEventPayload::OrderFilled { order_seq, .. } if *order_seq == seq)
            })
            .unwrap()
    };
    assert!(order_created_at(0) < order_filled_at(0));
    assert!(order_created_at(1) < order_filled_at(1));
    let bar1 = events
        .iter()
        .position(|e| {
            matches!(
                &e.payload,
                EngineEventPayload::BarProcessed { bar_index: 1, .. }
            )
        })
        .unwrap();
    assert!(bar1 < order_created_at(1));

    // RunCompleted carries the same economics as the result.
    if let Some(EngineEventPayload::RunCompleted {
        total_bars,
        final_balance,
        final_equity,
        open_positions_remaining,
    }) = events.last().map(|e| &e.payload)
    {
        assert_eq!(*total_bars, 2);
        assert!((*final_balance - 60_000.0).abs() < EPS);
        assert!((*final_equity - 60_000.0).abs() < EPS);
        assert_eq!(*open_positions_remaining, 0);
    } else {
        panic!("last event is not RunCompleted");
    }
}

// ── 3. Repeated-run determinism ─────────────────

#[test]
fn repeated_runs_are_deterministic_after_uuid_normalization() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let bars = bars.clone();

    let make_run = || {
        let mut engine = Engine::new(config.clone()).unwrap();
        engine
            .run(
                &bars,
                &mut BuyThenCloseFromView {
                    bought: false,
                    closing: false,
                    size: 1.0,
                },
            )
            .unwrap()
    };
    let a = make_run();
    let b = make_run();

    // Economic result equality (fills/trades/snapshots are bit-exact).
    assert_eq!(a.fills.len(), b.fills.len());
    assert_eq!(a.trades.len(), b.trades.len());
    assert!((a.final_state.final_equity - b.final_state.final_equity).abs() < EPS);
    for (x, y) in a.trades.iter().zip(b.trades.iter()) {
        assert!((x.net_realized_pnl - y.net_realized_pnl).abs() < EPS);
    }

    // Event histories: same length and identical after position-id stripping.
    assert_eq!(a.events.len(), b.events.len());
    for (x, y) in a.events.iter().zip(b.events.iter()) {
        let vx = normalized_event(&serde_json::to_value(x).unwrap());
        let vy = normalized_event(&serde_json::to_value(y).unwrap());
        assert_eq!(vx, vy);
    }

    // Persisted artifacts: byte-identical for run.json/metrics.json; events
    // identical modulo position UUIDs.
    let (ta, tb) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let (da, db) = (ta.path().join("a"), tb.path().join("b"));
    persist(&da, &a, &bars, &config);
    persist(&db, &b, &bars, &config);
    assert_eq!(
        fs::read(da.join("run.json")).unwrap(),
        fs::read(db.join("run.json")).unwrap()
    );
    assert_eq!(
        fs::read(da.join("metrics.json")).unwrap(),
        fs::read(db.join("metrics.json")).unwrap()
    );
    let ea = read_events(&da);
    let eb = read_events(&db);
    assert_eq!(ea.len(), eb.len());
    for (x, y) in ea.iter().zip(eb.iter()) {
        assert_eq!(normalized_event(x), normalized_event(y));
    }
}

// ── 4. Content-hash sensitivity ─────────────────

#[test]
fn dataset_change_changes_dataset_sha256() {
    let cfg = base_config(FillMode::BarClose);
    let bars_a = fixture_bars();
    let mut bars_b = fixture_bars();
    bars_b[0].close = 1.25; // exact binary fraction, different dataset

    let tmp = tempfile::tempdir().unwrap();
    let (da, db) = (tmp.path().join("ds-a"), tmp.path().join("ds-b"));
    let ra = run_once(
        &bars_a,
        &cfg,
        &mut BuyAndHold {
            bought: false,
            size: 1.0,
        },
    );
    let rb = run_once(
        &bars_b,
        &cfg,
        &mut BuyAndHold {
            bought: false,
            size: 1.0,
        },
    );
    persist(&da, &ra, &bars_a, &cfg);
    persist(&db, &rb, &bars_b, &cfg);

    let sha_a = read_run_json(&da)["dataset"]["sha256"]
        .as_str()
        .unwrap()
        .to_string();
    let sha_b = read_run_json(&db)["dataset"]["sha256"]
        .as_str()
        .unwrap()
        .to_string();
    assert_ne!(sha_a, sha_b);
    // Hash is stable for identical input, and recomputable via the API.
    assert_eq!(
        sha_a,
        persistence::dataset_identity(&bars_a).unwrap().sha256
    );
}

#[test]
fn strategy_parameter_change_changes_strategy_hash() {
    let mut cfg_a = base_config(FillMode::BarClose);
    cfg_a
        .strategy
        .as_mut()
        .unwrap()
        .parameters
        .insert("fast".to_string(), serde_json::json!(10));
    let mut cfg_b = cfg_a.clone();
    cfg_b
        .strategy
        .as_mut()
        .unwrap()
        .parameters
        .insert("fast".to_string(), serde_json::json!(20));

    let bars = fixture_bars();
    let tmp = tempfile::tempdir().unwrap();
    let (da, db) = (tmp.path().join("s-a"), tmp.path().join("s-b"));
    let ra = run_once(&bars, &cfg_a, &mut Noop);
    let rb = run_once(&bars, &cfg_b, &mut Noop);
    persist(&da, &ra, &bars, &cfg_a);
    persist(&db, &rb, &bars, &cfg_b);

    let sha_a = read_run_json(&da)["strategy"]["params_sha256"]
        .as_str()
        .unwrap()
        .to_string();
    let sha_b = read_run_json(&db)["strategy"]["params_sha256"]
        .as_str()
        .unwrap()
        .to_string();
    assert_ne!(sha_a, sha_b);
    assert_eq!(sha_a, persistence::strategy_identity(&cfg_a).unwrap());
}

#[test]
fn strategy_source_file_bytes_are_hashed() {
    // A writable strategy source file is hashed by bytes, not name/params.
    let tmp = tempfile::tempdir().unwrap();
    let source = tmp.path().join("strat.py");
    let content = b"class S:\n    pass\n# deterministic source\n";
    fs::write(&source, content).unwrap();

    let mut cfg = base_config(FillMode::BarClose);
    let strat = cfg.strategy.as_mut().unwrap();
    strat.source = Some(source.display().to_string());
    strat.parameters = BTreeMap::new();

    assert_eq!(
        persistence::strategy_identity(&cfg).unwrap(),
        Sha256::hex(content)
    );
}

// ── 5. Structured rejections ────────────────────

#[test]
fn rejected_order_is_recorded_with_execution_domain_category() {
    // size 1_000 lots exceeds the instrument max of 100 → domain rejection.
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let result = run_once(
        &bars,
        &config,
        &mut BuyThenCloseFromView {
            bought: false,
            closing: false,
            size: 1_000.0,
        },
    );

    let rejected: Vec<&EngineEvent> = result
        .events
        .iter()
        .filter(|e| matches!(e.payload, EngineEventPayload::OrderRejected { .. }))
        .collect();
    assert_eq!(rejected.len(), 1);
    match &rejected[0].payload {
        EngineEventPayload::OrderRejected {
            category,
            reason,
            bar_index,
            ..
        } => {
            assert_eq!(*category, RejectionCategory::ExecutionDomain);
            assert!(!reason.is_empty());
            assert_eq!(*bar_index, 0);
        }
        _ => unreachable!(),
    }
    // Order log agrees and no position was opened.
    assert!(result
        .orders
        .iter()
        .all(|o| o.state == OrderState::Rejected));
    assert!(result.fills.is_empty());
    assert!(result.trades.is_empty());
}

#[test]
fn insufficient_margin_is_a_financial_rejection() {
    // leverage 1 with a tiny balance cannot cover 100k units at 1.0.
    let mut config = base_config(FillMode::BarClose);
    config.account.leverage = 1.0;
    config.account.starting_balance = 500.0;
    let bars = fixture_bars();
    let result = run_once(
        &bars,
        &config,
        &mut BuyAndHold {
            bought: false,
            size: 1.0,
        },
    );

    let rejected: Vec<&EngineEvent> = result
        .events
        .iter()
        .filter(|e| matches!(e.payload, EngineEventPayload::OrderRejected { .. }))
        .collect();
    assert_eq!(rejected.len(), 1);
    match &rejected[0].payload {
        EngineEventPayload::OrderRejected {
            category, reason, ..
        } => {
            assert_eq!(*category, RejectionCategory::Financial);
            assert!(reason.contains("insufficient margin"), "reason: {reason}");
        }
        _ => unreachable!(),
    }
    assert!(result.orders[0].state == OrderState::Rejected);
    assert!(result.fills.is_empty());
}

// ── 6. Open-position end-of-run state ───────────

#[test]
fn open_position_run_reports_final_state_and_metrics() {
    // Buy at bar0 close 1.0, hold through bar1 close 1.5:
    //   final balance 10 000 (nothing realized), equity 60 000, 1 open.
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("run-open");
    let result = run_once(
        &bars,
        &config,
        &mut BuyAndHold {
            bought: false,
            size: 1.0,
        },
    );

    persist(&dir, &result, &bars, &config);
    assert_eq!(result.final_state.open_positions_remaining, 1);
    assert!((result.final_state.final_balance - 10_000.0).abs() < EPS);
    assert!((result.final_state.final_equity - 60_000.0).abs() < EPS);

    let run_json = read_run_json(&dir);
    assert_eq!(run_json["open_positions_remaining"], 1);
    assert!((run_json["final_balance"].as_f64().unwrap() - 10_000.0).abs() < EPS);
    assert!((run_json["final_equity"].as_f64().unwrap() - 60_000.0).abs() < EPS);

    let metrics = read_metrics(&dir);
    assert!((metrics["final_equity"].as_f64().unwrap() - 60_000.0).abs() < EPS);
    assert_eq!(metrics["open_positions_remaining"], 1);

    // The canonical RunCompleted event mirrors the persisted summary.
    if let Some(EngineEventPayload::RunCompleted {
        final_balance,
        final_equity,
        open_positions_remaining,
        ..
    }) = result.events.last().map(|e| &e.payload)
    {
        assert!((*final_balance - 10_000.0).abs() < EPS);
        assert!((*final_equity - 60_000.0).abs() < EPS);
        assert_eq!(*open_positions_remaining, 1);
    } else {
        panic!("last event is not RunCompleted");
    }
}

// ── 7. No silent overwrite ──────────────────────

#[test]
fn persistence_refuses_to_overwrite_existing_output() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("existing");
    fs::create_dir(&dir).unwrap();
    fs::write(dir.join("sentinel.txt"), b"do not clobber").unwrap();

    let result = run_once(&bars, &config, &mut Noop);
    let err = persistence::persist_completed_run(
        &dir,
        &config,
        &bars,
        &result.events,
        &result,
        24.0 * 252.0,
        "test.csv",
    )
    .unwrap_err();
    assert!(matches!(err, PersistenceError::OutputAlreadyExists { .. }));

    // Pre-existing content untouched (no silent overwrite; we never clean up
    // a directory we did not create).
    assert_eq!(
        fs::read(dir.join("sentinel.txt")).unwrap(),
        b"do not clobber"
    );
    assert!(!dir.join("run.json").exists());

    // Persisting the same run twice to the same fresh path also fails.
    let fresh = tmp.path().join("twice");
    persist(&fresh, &result, &bars, &config);
    let err2 = persistence::persist_completed_run(
        &fresh,
        &config,
        &bars,
        &result.events,
        &result,
        24.0 * 252.0,
        "test.csv",
    )
    .unwrap_err();
    assert!(matches!(err2, PersistenceError::OutputAlreadyExists { .. }));
}

// ── 8. Failure artifacts ────────────────────────

#[test]
fn failed_run_keeps_partial_history_and_persists_failure_artifacts() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config.clone()).unwrap();
    let mut strategy = FailAfter {
        seen: 0,
        fail_after: 1, // fails on the first on_bar (bar 0)
        error: None,
    };
    let err = engine.run(&bars, &mut strategy).unwrap_err();
    assert!(matches!(
        err,
        observa_engine::error::EngineError::StrategyFailure { .. }
    ));

    // The Engine retains the partial canonical history, ending in RunFailed.
    let events: Vec<&EngineEvent> = engine.events().iter().collect();
    assert!(!events.is_empty());
    assert!(matches!(
        events.first().map(|e| &e.payload),
        Some(EngineEventPayload::RunStarted { .. })
    ));
    assert!(matches!(
        events.last().map(|e| &e.payload),
        Some(EngineEventPayload::RunFailed { .. })
    ));
    let strategy_errors = events
        .iter()
        .filter(|e| matches!(e.payload, EngineEventPayload::StrategyError { .. }))
        .count();
    assert_eq!(strategy_errors, 1);

    // Failure artifacts: run.json (failed) + events.jsonl, no metrics.json.
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("run-failed");
    persistence::persist_failed_run(
        &dir,
        &config,
        &bars,
        engine.events(),
        &err.to_string(),
        "test.csv",
    )
    .unwrap();

    let run_json = read_run_json(&dir);
    assert_eq!(run_json["status"], "failed");
    assert!(run_json["error"]
        .as_str()
        .unwrap()
        .contains("strategy failure"));
    assert_eq!(run_json["event_count"], events.len() as u64);

    let persisted = read_events(&dir);
    assert_eq!(persisted.len(), events.len());
    assert_eq!(persisted.last().unwrap()["type"], "run_failed");
    assert!(!dir.join("metrics.json").exists());

    // No economic events are fabricated on a failed run (no fills recorded).
    let fabricated = persisted
        .iter()
        .filter(|e| e["type"] == "order_filled" || e["type"] == "position_opened")
        .count();
    assert_eq!(fabricated, 0);
}

// ── 10. Queued / resting order lifecycle events ──

/// Buys (market) once on bar 0; NEXT_BAR_OPEN queues it for bar 1's open.
struct BuyOnceMarket {
    sent: bool,
}

impl Strategy for BuyOnceMarket {
    fn on_bar(
        &mut self,
        bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        if !self.sent {
            self.sent = true;
            return vec![buy_signal(bar, 1.0)];
        }
        vec![]
    }
}

/// Sends one resting LIMIT order on bar 0 at `price`.
struct LimitOnce {
    price: f64,
    sent: bool,
}

impl Strategy for LimitOnce {
    fn on_bar(
        &mut self,
        bar: &Bar,
        _view: &PortfolioView,
        _history: &[Bar],
    ) -> Vec<StrategySignal> {
        if !self.sent {
            self.sent = true;
            return vec![StrategySignal {
                direction: Direction::Buy,
                order_type: OrderKind::Limit,
                size: 1.0,
                intended_price: self.price,
                sl: None,
                tp: None,
                reason: "limit".to_string(),
                ticket: None,
            }];
        }
        vec![]
    }
}

#[test]
fn queued_market_order_lifecycle_events() {
    // NEXT_BAR_OPEN buy on bar0 queues (order_pending); bar1's open fills it.
    let bars = vec![bar(0, 1.0, 1.25, 1.0, 1.0), bar(1, 1.25, 1.5, 1.25, 1.5)];
    let config = base_config(FillMode::NextBarOpen);
    let result = run_once(&bars, &config, &mut BuyOnceMarket { sent: false });

    let types: Vec<&str> = result
        .events
        .iter()
        .map(|e| event_tag(&e.payload))
        .collect();
    assert_eq!(
        types,
        vec![
            "run_started",
            "strategy_initialized",
            "bar_processed",
            "strategy_decision",
            "order_created",
            "order_pending",
            "portfolio_snapshot",
            "bar_processed",
            "order_filled",
            "position_opened",
            "strategy_decision",
            "portfolio_snapshot",
            "run_completed",
        ],
        "actual: {types:?}"
    );
    // The pending event carries the created order's seq.
    let pending_seqs: Vec<u64> = result
        .events
        .iter()
        .filter_map(|e| match &e.payload {
            EngineEventPayload::OrderPending { order_seq } => Some(*order_seq),
            _ => None,
        })
        .collect();
    assert_eq!(pending_seqs, vec![0]);
}

#[test]
fn resting_limit_trigger_emits_trigger_before_fill() {
    // Limit buy at 1.25 created on bar0; bar1's low 1.0 reaches it.
    let bars = vec![bar(0, 1.0, 1.5, 1.0, 1.25), bar(1, 1.25, 1.5, 1.0, 1.25)];
    let config = base_config(FillMode::NextBarOpen);
    let result = run_once(
        &bars,
        &config,
        &mut LimitOnce {
            price: 1.25,
            sent: false,
        },
    );

    let types: Vec<&str> = result
        .events
        .iter()
        .map(|e| event_tag(&e.payload))
        .collect();
    // Between bar1's bar_processed and strategy_decision the resting order
    // triggers and fills (stage 2 precedes stage 4).
    assert_eq!(
        types,
        vec![
            "run_started",
            "strategy_initialized",
            "bar_processed",
            "strategy_decision",
            "order_created",
            "order_pending",
            "portfolio_snapshot",
            "bar_processed",
            "order_triggered",
            "order_filled",
            "position_opened",
            "strategy_decision",
            "portfolio_snapshot",
            "run_completed",
        ],
        "actual: {types:?}"
    );
    // Trigger and fill share the resting order's seq.
    let triggered = result
        .events
        .iter()
        .find_map(|e| match &e.payload {
            EngineEventPayload::OrderTriggered { order_seq, .. } => Some(*order_seq),
            _ => None,
        })
        .unwrap();
    let filled = result
        .events
        .iter()
        .find_map(|e| match &e.payload {
            EngineEventPayload::OrderFilled { order_seq, .. } => Some(*order_seq),
            _ => None,
        })
        .unwrap();
    assert_eq!(triggered, 0);
    assert_eq!(filled, 0);
}

#[test]
fn unfilled_resting_order_expires_at_dataset_end() {
    // Limit buy far below every bar low: never triggered, expires at the end.
    let bars = vec![bar(0, 1.0, 1.5, 1.0, 1.25), bar(1, 1.25, 1.5, 1.0, 1.25)];
    let config = base_config(FillMode::NextBarOpen);
    let result = run_once(
        &bars,
        &config,
        &mut LimitOnce {
            price: 0.5,
            sent: false,
        },
    );

    let types: Vec<&str> = result
        .events
        .iter()
        .map(|e| event_tag(&e.payload))
        .collect();
    // No trigger/fill anywhere; the order expires after the last snapshot and
    // before run_completed.
    assert!(!types.contains(&"order_triggered"));
    assert!(!types.contains(&"order_filled"));
    assert!(!types.contains(&"position_opened"));
    assert_eq!(types[types.len() - 2], "order_expired");
    assert_eq!(types[types.len() - 1], "run_completed");
    assert_eq!(result.orders.len(), 1);
    assert_eq!(
        result.orders[0].state,
        OrderState::Expired,
        "unfilled order must expire, not stay pending"
    );
}

// ── 9. Single-run guard ─────────────────────────

#[test]
fn engine_instance_is_single_run() {
    let (bars, config) = (fixture_bars(), base_config(FillMode::BarClose));
    let mut engine = Engine::new(config).unwrap();
    let mut s = Noop;
    engine.run(&bars, &mut s).unwrap();
    let err = engine.run(&bars, &mut s).unwrap_err();
    let msg = err.to_string();
    assert!(
        msg.contains("already been run"),
        "second run must be refused, got: {msg}"
    );
}
