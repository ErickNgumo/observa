//! Generates canonical replay fixtures (bars + canonical events) for the
//! OBS-0010 frontend tests.
//!
//! Usage: cargo run -p observa-engine --example gen_replay_fixtures -- <outdir>
//!
//! Every fixture is produced by the real canonical Engine — the fixtures are
//! not hand-authored JSON.

use std::collections::BTreeMap;
use std::path::Path;

use chrono::{TimeZone, Utc};
use serde_json::json;

use observa_core::bar::Bar;
use observa_core::config::{
    AccountConfig, BacktestConfig, BarInterval, CommissionConfig, CommissionMode, DatasetConfig,
    ExecutionConfig, FillMode, InstrumentConfig, OrderModelConfig, StrategyConfig,
};
use observa_core::types::{Direction, OrderKind};
use observa_engine::engine::Engine;
use observa_engine::strategy::{PortfolioView, Strategy, StrategySignal};

fn ts(i: i64) -> chrono::DateTime<Utc> {
    Utc.timestamp_opt(1_700_000_000 + i * 900, 0).unwrap()
}

fn bar(i: i64, o: f64, h: f64, l: f64, c: f64) -> Bar {
    Bar::new(ts(i), o, h, l, c, None)
}

fn config(fill_mode: FillMode, balance: f64, leverage: f64) -> BacktestConfig {
    BacktestConfig {
        version: 1,
        account: AccountConfig {
            starting_balance: balance,
            currency: "USD".to_string(),
            leverage,
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
        execution: ExecutionConfig {
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
            source: "fixture.csv".to_string(),
            hash: None,
            interval: BarInterval::Minute(15),
            start: None,
            end: None,
            bar_count: None,
        }),
        strategy: Some(StrategyConfig {
            name: "Fixture".to_string(),
            source: None,
            source_hash: None,
            parameters: BTreeMap::new(),
        }),
    }
}

fn buy(
    bar: &Bar,
    size: f64,
    order_type: OrderKind,
    price: f64,
    sl: Option<f64>,
    tp: Option<f64>,
) -> StrategySignal {
    StrategySignal {
        direction: Direction::Buy,
        order_type,
        size,
        intended_price: price,
        sl,
        tp,
        reason: "fixture".to_string(),
        ticket: None,
    }
}

fn close(ticket: &str, size: f64) -> StrategySignal {
    StrategySignal {
        direction: Direction::Close,
        order_type: OrderKind::Market,
        size,
        intended_price: 0.0,
        sl: None,
        tp: None,
        reason: "fixture-close".to_string(),
        ticket: Some(ticket.to_string()),
    }
}

/// Runs a scenario and writes {bars, events} for a completed (or failed) run.
fn emit(
    dir: &Path,
    name: &str,
    bars: Vec<Bar>,
    strategy: &mut dyn Strategy,
    fill_mode: FillMode,
    balance: f64,
    leverage: f64,
) {
    let mut engine = match Engine::new(config(fill_mode, balance, leverage)) {
        Ok(e) => e,
        Err(err) => panic!("{name}: engine: {err}"),
    };
    let outcome = engine.run(&bars, strategy);
    let (events, run_status) = match &outcome {
        Ok(result) => (result.events.clone(), "completed".to_string()),
        Err(_) => (engine.events().to_vec(), "failed".to_string()),
    };
    let payload = json!({
        "fixture": name,
        "status": run_status,
        "bars": bars.iter().map(|b| json!({
            "time": b.timestamp.to_rfc3339(), "open": b.open, "high": b.high,
            "low": b.low, "close": b.close, "volume": b.volume
        })).collect::<Vec<_>>(),
        "events": events.iter().map(|e| serde_json::to_value(e).unwrap()).collect::<Vec<_>>(),
    });
    std::fs::write(
        dir.join(format!("{name}.json")),
        serde_json::to_string_pretty(&payload).unwrap(),
    )
    .unwrap();
    println!(
        "wrote {name}: {} bars, {} events, {}",
        bars.len(),
        events.len(),
        run_status
    );
}

fn main() {
    let outdir = std::env::args()
        .nth(1)
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("frontend/tests/fixtures"));
    std::fs::create_dir_all(&outdir).unwrap();
    run_all(&outdir);
}

fn run_all(dir: &Path) {
    // ── Fixture A: one MARKET round trip (BAR_CLOSE) ──
    struct A {
        bought: bool,
        closed: bool,
    }
    impl Strategy for A {
        fn on_bar(&mut self, bar: &Bar, view: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.bought {
                self.bought = true;
                return vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)];
            }
            if !self.closed {
                if let Some(p) = view.open_positions.first() {
                    self.closed = true;
                    return vec![close(&p.ticket, p.size)];
                }
            }
            vec![]
        }
    }
    emit(
        dir,
        "a_market_trade",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.5, 1.5, 1.5, 1.5)],
        &mut A {
            bought: false,
            closed: false,
        },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture B: NEXT_BAR_OPEN — decision bar 0, fill bar 1 ──
    struct B {
        sent: bool,
    }
    impl Strategy for B {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "b_next_bar_open",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.25, 1.5, 1.25, 1.5)],
        &mut B { sent: false },
        FillMode::NextBarOpen,
        10_000.0,
        100.0,
    );

    // ── Fixture C: LIMIT pending then fill at 0.95 ──
    struct C {
        sent: bool,
    }
    impl Strategy for C {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(bar, 1.0, OrderKind::Limit, 0.95, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "c_limit",
        vec![bar(0, 1.0, 1.05, 1.0, 1.0), bar(1, 1.0, 1.0, 0.9, 0.95)],
        &mut C { sent: false },
        FillMode::NextBarOpen,
        10_000.0,
        100.0,
    );

    // ── Fixture D: STOP protective gap — SL 0.995, bar1 opens 0.985 ──
    struct D {
        sent: bool,
    }
    impl Strategy for D {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(
                    bar,
                    1.0,
                    OrderKind::Market,
                    bar.close,
                    Some(0.995),
                    None,
                )];
            }
            vec![]
        }
    }
    emit(
        dir,
        "d_sl_gap",
        vec![bar(0, 1.0, 1.01, 1.0, 1.0), bar(1, 0.985, 0.99, 0.97, 0.98)],
        &mut D { sent: false },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture E: three simultaneous positions ──
    struct E {
        n: usize,
    }
    impl Strategy for E {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if self.n < 3 {
                self.n += 1;
                return vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "e_multi_position",
        vec![
            bar(0, 1.0, 1.0, 1.0, 1.0),
            bar(1, 1.0, 1.0, 1.0, 1.0),
            bar(2, 1.0, 1.0, 1.0, 1.0),
            bar(3, 1.0, 1.0, 1.0, 1.0),
        ],
        &mut E { n: 0 },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture F: hedge — long then short ──
    struct F {
        step: usize,
    }
    impl Strategy for F {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            self.step += 1;
            match self.step {
                1 => vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)],
                2 => vec![StrategySignal {
                    direction: Direction::Sell,
                    order_type: OrderKind::Market,
                    size: 1.0,
                    intended_price: bar.close,
                    sl: None,
                    tp: None,
                    reason: "fixture".to_string(),
                    ticket: None,
                }],
                _ => vec![],
            }
        }
    }
    emit(
        dir,
        "f_hedge",
        vec![
            bar(0, 1.0, 1.0, 1.0, 1.0),
            bar(1, 1.0, 1.0, 1.0, 1.0),
            bar(2, 1.0, 1.0, 1.0, 1.0),
        ],
        &mut F { step: 0 },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture G: open A, B, C; close exactly B (size 2) ──
    struct G {
        step: usize,
    }
    impl Strategy for G {
        fn on_bar(&mut self, bar: &Bar, view: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            self.step += 1;
            match self.step {
                1 => vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)],
                2 => vec![buy(bar, 2.0, OrderKind::Market, bar.close, None, None)],
                3 => vec![buy(bar, 3.0, OrderKind::Market, bar.close, None, None)],
                4 => {
                    for p in &view.open_positions {
                        if (p.size - 2.0).abs() < 1e-12 {
                            return vec![close(&p.ticket, p.size)];
                        }
                    }
                    vec![]
                }
                _ => vec![],
            }
        }
    }
    emit(
        dir,
        "g_close_exact_ticket",
        vec![
            bar(0, 1.0, 1.0, 1.0, 1.0),
            bar(1, 1.0, 1.0, 1.0, 1.0),
            bar(2, 1.0, 1.0, 1.0, 1.0),
            bar(3, 1.0, 1.0, 1.0, 1.0),
        ],
        &mut G { step: 0 },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture H: intrabar SL execution at 0.995 ──
    struct H {
        sent: bool,
    }
    impl Strategy for H {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(
                    bar,
                    1.0,
                    OrderKind::Market,
                    bar.close,
                    Some(0.995),
                    None,
                )];
            }
            vec![]
        }
    }
    emit(
        dir,
        "h_sl_intrabar",
        vec![bar(0, 1.0, 1.01, 1.0, 1.0), bar(1, 1.0, 1.005, 0.99, 0.995)],
        &mut H { sent: false },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture I: TP execution at 1.005 ──
    struct I {
        sent: bool,
    }
    impl Strategy for I {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(
                    bar,
                    1.0,
                    OrderKind::Market,
                    bar.close,
                    None,
                    Some(1.005),
                )];
            }
            vec![]
        }
    }
    emit(
        dir,
        "i_tp",
        vec![bar(0, 1.0, 1.01, 1.0, 1.0), bar(1, 1.0, 1.01, 1.0, 1.0)],
        &mut I { sent: false },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture J: rejected order (oversize → execution_domain) ──
    struct J {
        sent: bool,
    }
    impl Strategy for J {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(bar, 1_000.0, OrderKind::Market, bar.close, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "j_rejected",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)],
        &mut J { sent: false },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture K: expired order (queued on the final bar) ──
    struct K {
        n: usize,
    }
    impl Strategy for K {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            self.n += 1;
            if self.n == 2 {
                // Queued on the LAST bar -> cannot fill -> OrderExpired.
                return vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "k_expired",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)],
        &mut K { n: 0 },
        FillMode::NextBarOpen,
        10_000.0,
        100.0,
    );

    // ── Fixture L: failed run ──
    struct L;
    impl Strategy for L {
        fn on_bar(&mut self, _bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            vec![]
        }
        fn take_strategy_error(&mut self) -> Option<String> {
            Some("scripted failure in fixture L".to_string())
        }
    }
    emit(
        dir,
        "l_failed",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)],
        &mut L,
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // ── Fixture M: end with an open position, balance != equity ──
    struct M {
        sent: bool,
    }
    impl Strategy for M {
        fn on_bar(&mut self, bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            if !self.sent {
                self.sent = true;
                return vec![buy(bar, 1.0, OrderKind::Market, bar.close, None, None)];
            }
            vec![]
        }
    }
    emit(
        dir,
        "m_open_end",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.5, 1.5, 1.5, 1.5)],
        &mut M { sent: false },
        FillMode::BarClose,
        10_000.0,
        100.0,
    );

    // Fixture M2: no-trade run (bars only).
    struct NoTrade;
    impl Strategy for NoTrade {
        fn on_bar(&mut self, _bar: &Bar, _v: &PortfolioView, _h: &[Bar]) -> Vec<StrategySignal> {
            vec![]
        }
    }
    emit(
        dir,
        "n_no_trade",
        vec![bar(0, 1.0, 1.0, 1.0, 1.0), bar(1, 1.0, 1.0, 1.0, 1.0)],
        &mut NoTrade,
        FillMode::BarClose,
        10_000.0,
        100.0,
    );
}
