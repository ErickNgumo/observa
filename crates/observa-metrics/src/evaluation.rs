//! Strategy evaluation metrics, schema version 2.
//!
//! One pure function, [`compute_metrics`], turns canonical run data (end-of-bar
//! snapshots, closed trades, fills) into the `metrics.json` object. Metrics are
//! derived, never a financial authority: every input already exists in the
//! canonical run, and nothing here feeds back into execution.
//!
//! Conventions (documented in `docs/metrics.md`):
//!
//! * `S` = starting balance; `E_t` = end-of-bar equity for bars `t = 0..n-1`
//!   (mark-to-market at the bar close, no exit costs); `E_-1 = S`.
//! * Per-bar returns `r_t = E_t / E_{t-1} - 1` (n returns). They are defined
//!   only while equity stays strictly positive.
//! * Annualisation needs `bars_per_year`. It is never guessed for intraday
//!   bars; an annualised metric without it is reported as unavailable with a
//!   reason (see [`resolve_annualisation`]).
//! * A metric that is undefined (e.g. profit factor with no losing trade) is
//!   `null` in the report and its reason is listed under `unavailable`.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde_json::{json, Map, Value};

/// Version of the `metrics.json` schema produced by [`compute_metrics`].
pub const METRICS_SCHEMA_VERSION: u32 = 2;

/// Minimum number of per-bar returns for volatility / Sharpe / Sortino.
pub const MIN_RETURNS_FOR_RATIOS: usize = 30;

/// Minimum sample length, in years, before a return is annualised. Following
/// the GIPS convention, periods shorter than one year are not annualised:
/// extrapolating a few weeks to a year produces arbitrary numbers.
pub const MIN_YEARS_FOR_ANNUALISED_RETURN: f64 = 1.0;

/// Trading days per year assumed for daily bars when `bars_per_year` is not
/// given (a common equity/FX convention; pass `bars_per_year=365` for 24/7
/// markets).
pub const DEFAULT_DAILY_BARS_PER_YEAR: f64 = 252.0;

/// Weeks per year assumed for weekly bars when `bars_per_year` is not given.
pub const DEFAULT_WEEKLY_BARS_PER_YEAR: f64 = 52.0;

/// Accepted range for an explicit `bars_per_year`: from one bar per year to
/// one bar per second (366 days x 86,400 s).
pub const MIN_BARS_PER_YEAR: f64 = 1.0;
pub const MAX_BARS_PER_YEAR: f64 = 31_622_400.0;

/// How the annualisation factor was obtained.
#[derive(Debug, Clone, PartialEq)]
pub struct Annualisation {
    /// Bars per year, when known.
    pub bars_per_year: Option<f64>,
    /// `"explicit"`, `"interval_default"` or `None` when unavailable.
    pub source: Option<&'static str>,
    /// Human-readable explanation (why this factor, or why none).
    pub note: String,
}

/// The declared bar interval, as far as metrics need it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum IntervalKind {
    /// Bars of `n` seconds shorter than a day (minutes / hours).
    Intraday(i64),
    Daily,
    Weekly,
}

/// Resolves the annualisation factor.
///
/// 1. An explicit `bars_per_year` always wins (validated by the caller).
/// 2. Daily (`252`) and weekly (`52`) intervals have a conventional default,
///    but only when the observed median bar spacing is consistent with the
///    declared interval — otherwise the interval is probably just the config
///    default left unchanged (e.g. hourly bars with `interval="1d"`).
/// 3. Intraday intervals have no default: bars per year depends on the
///    market's trading hours, so annualised metrics are unavailable.
pub fn resolve_annualisation(
    explicit: Option<f64>,
    interval_label: &str,
    interval: IntervalKind,
    timestamps: &[DateTime<Utc>],
) -> Annualisation {
    if let Some(bpy) = explicit {
        if !(bpy.is_finite() && (MIN_BARS_PER_YEAR..=MAX_BARS_PER_YEAR).contains(&bpy)) {
            // Callers validate first; the metrics layer never trusts its input.
            return Annualisation {
                bars_per_year: None,
                source: None,
                note: format!(
                    "bars_per_year = {bpy} is outside the accepted range \
                     {MIN_BARS_PER_YEAR}..={MAX_BARS_PER_YEAR}"
                ),
            };
        }
        return Annualisation {
            bars_per_year: Some(bpy),
            source: Some("explicit"),
            note: format!("bars_per_year = {} (set explicitly)", trim_float(bpy)),
        };
    }
    let observed = median_spacing_seconds(timestamps);
    let in_band = |lo: f64, hi: f64| match observed {
        Some(sec) => sec >= lo && sec <= hi,
        None => true,
    };
    let spacing_text = observed
        .map(|sec| format!("bars are a median of {} apart", human_duration(sec)))
        .unwrap_or_default();
    // Bars per calendar year actually observed (only meaningful over a span
    // of at least four weeks).
    let density = match (timestamps.first(), timestamps.last()) {
        (Some(a), Some(b)) => {
            let days = (*b - *a).num_seconds() as f64 / 86_400.0;
            if days >= 28.0 {
                Some((timestamps.len() as f64 - 1.0) / (days / 365.25))
            } else {
                None
            }
        }
        _ => None,
    };
    let unavailable = |why: String| Annualisation { bars_per_year: None, source: None, note: why };
    match interval {
        IntervalKind::Daily => {
            if !in_band(0.75 * 86_400.0, 1.5 * 86_400.0) {
                return unavailable(format!(
                    "interval '{interval_label}' is declared but {spacing_text}; set the correct \
                     interval and/or pass bars_per_year to annualise"
                ));
            }
            match density {
                // Trading-day calendar (weekdays, minus holidays).
                Some(d) if (200.0..=290.0).contains(&d) => Annualisation {
                    bars_per_year: Some(DEFAULT_DAILY_BARS_PER_YEAR),
                    source: Some("interval_default"),
                    note: format!(
                        "daily bars on a trading-day calendar ({} bars per calendar year observed): \
                         252 per year",
                        trim_float(d.round())
                    ),
                },
                None => Annualisation {
                    bars_per_year: Some(DEFAULT_DAILY_BARS_PER_YEAR),
                    source: Some("interval_default"),
                    note: if observed.is_none() {
                        "daily interval: 252 trading days per year (too few bars to check the \
                         spacing or calendar)"
                            .to_string()
                    } else {
                        "daily bars: 252 trading days per year (span too short to check the \
                         calendar; pass bars_per_year=365 for a 24/7 market)"
                            .to_string()
                    },
                },
                // Every calendar day (24/7 markets such as crypto).
                Some(d) if (330.0..=380.0).contains(&d) => Annualisation {
                    bars_per_year: Some(365.0),
                    source: Some("interval_default"),
                    note: format!(
                        "daily bars on every calendar day ({} bars per calendar year observed): \
                         365 per year",
                        trim_float(d.round())
                    ),
                },
                Some(d) => unavailable(format!(
                    "daily bars, but {} bars per calendar year are observed (neither a ~252-day \
                     trading calendar nor a 365-day one); pass bars_per_year to annualise",
                    trim_float(d.round())
                )),
            }
        }
        IntervalKind::Weekly => {
            if in_band(5.0 * 86_400.0, 9.0 * 86_400.0) {
                Annualisation {
                    bars_per_year: Some(DEFAULT_WEEKLY_BARS_PER_YEAR),
                    source: Some("interval_default"),
                    note: "weekly bars: 52 weeks per year".to_string(),
                }
            } else {
                unavailable(format!(
                    "interval '{interval_label}' is declared but {spacing_text}; set the correct \
                     interval and/or pass bars_per_year to annualise"
                ))
            }
        }
        IntervalKind::Intraday(_) => unavailable(format!(
            "intraday interval '{interval_label}': bars per year depends on the market's \
             trading hours (e.g. 24h x 252 days, 24h x 365 days, 6.5h x 252 days), so it \
             is not guessed; pass bars_per_year to annualise"
        )),
    }
}

fn median_spacing_seconds(ts: &[DateTime<Utc>]) -> Option<f64> {
    if ts.len() < 3 {
        return None;
    }
    let mut d: Vec<i64> = ts.windows(2).map(|w| (w[1] - w[0]).num_milliseconds()).collect();
    d.sort_unstable();
    Some(d[d.len() / 2] as f64 / 1000.0)
}

fn human_duration(seconds: f64) -> String {
    if seconds >= 86_400.0 {
        format!("{} day(s)", trim_float(seconds / 86_400.0))
    } else if seconds >= 3_600.0 {
        format!("{} hour(s)", trim_float(seconds / 3_600.0))
    } else {
        format!("{} minute(s)", trim_float(seconds / 60.0))
    }
}

fn trim_float(v: f64) -> String {
    let s = format!("{v:.4}");
    let s = s.trim_end_matches('0').trim_end_matches('.');
    s.to_string()
}

/// One end-of-bar snapshot.
#[derive(Debug, Clone)]
pub struct BarPoint {
    pub timestamp: DateTime<Utc>,
    pub equity: f64,
    pub balance: f64,
    /// Margin of all open positions at the bar close.
    pub used_margin: f64,
    /// Number of open positions at the bar close.
    pub open_positions: usize,
    /// Cumulative commissions booked so far.
    pub commissions_paid: f64,
}

/// One closed position (a "trade").
#[derive(Debug, Clone)]
pub struct TradePoint {
    /// Realised P&L net of commission.
    pub net_pnl: f64,
    /// Bar index of the opening fill, when known.
    pub entry_bar: Option<usize>,
    /// Bar index of the closing fill.
    pub exit_bar: usize,
}

/// Execution costs of one fill, already converted to account currency.
#[derive(Debug, Clone)]
pub struct FillCost {
    pub spread_cost: f64,
    pub slippage_cost: f64,
}

/// Everything [`compute_metrics`] needs.
#[derive(Debug, Clone)]
pub struct MetricsInput {
    pub starting_balance: f64,
    pub leverage: f64,
    pub bars: Vec<BarPoint>,
    /// Closed trades in closing order.
    pub trades: Vec<TradePoint>,
    pub fills: Vec<FillCost>,
    pub annualisation: Annualisation,
    pub interval_label: String,
    /// Account currency (all money metrics are in this currency).
    pub currency: String,
    pub final_balance: f64,
    pub final_equity: f64,
    pub open_positions_remaining: usize,
}

struct Report {
    values: Map<String, Value>,
    unavailable: BTreeMap<String, String>,
}

impl Report {
    fn new() -> Self {
        Self { values: Map::new(), unavailable: BTreeMap::new() }
    }
    fn num(&mut self, key: &str, v: f64) {
        self.values.insert(key.into(), if v.is_finite() { json!(v) } else { Value::Null });
    }
    fn int(&mut self, key: &str, v: usize) {
        self.values.insert(key.into(), json!(v));
    }
    fn set(&mut self, key: &str, v: Value) {
        self.values.insert(key.into(), v);
    }
    /// A metric that is either a finite number or unavailable with a reason.
    fn opt(&mut self, key: &str, v: Result<f64, String>) {
        match v {
            Ok(x) if x.is_finite() => {
                self.values.insert(key.into(), json!(x));
            }
            Ok(_) => {
                self.values.insert(key.into(), Value::Null);
                self.unavailable.insert(key.into(), "not a finite number".into());
            }
            Err(reason) => {
                self.values.insert(key.into(), Value::Null);
                self.unavailable.insert(key.into(), reason);
            }
        }
    }
}

fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

fn sample_std(xs: &[f64]) -> f64 {
    let m = mean(xs);
    (xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (xs.len() as f64 - 1.0)).sqrt()
}

/// Computes the schema-2 metrics report. See `docs/metrics.md` for every
/// definition and edge case.
pub fn compute_metrics(input: &MetricsInput) -> Value {
    let mut r = Report::new();
    let s = input.starting_balance;
    let n = input.bars.len();
    let equity: Vec<f64> = input.bars.iter().map(|b| b.equity).collect();
    let end_equity = equity.last().copied().unwrap_or(s);
    let bpy = input.annualisation.bars_per_year;
    let no_bpy = || input.annualisation.note.clone();

    // ── Returns ────────────────────────────────────────────────────────────
    r.num("net_profit", end_equity - s);
    r.num("total_return_pct", (end_equity / s - 1.0) * 100.0);

    // Per-bar returns are defined only while every base equity is positive.
    let mut bases = vec![s];
    bases.extend(equity.iter().take(n.saturating_sub(1)));
    let equity_positive = equity.iter().all(|e| *e > 0.0);
    let returns: Vec<f64> = equity.iter().zip(&bases).map(|(e, b)| e / b - 1.0).collect();
    let years = bpy.map(|b| n as f64 / b);

    let annualised = (|| {
        let b = bpy.ok_or_else(no_bpy)?;
        let y = n as f64 / b;
        if end_equity <= 0.0 {
            return Err("final equity is not positive".to_string());
        }
        if y < MIN_YEARS_FOR_ANNUALISED_RETURN {
            return Err(format!(
                "the sample covers {:.2} years at {} bars per year; returns over less than one \
                 year are not annualised (GIPS convention) — see total_return_pct",
                y,
                trim_float(b)
            ));
        }
        Ok(((end_equity / s).powf(1.0 / y) - 1.0) * 100.0)
    })();
    r.opt("annualised_return_pct", annualised.clone());

    // ── Risk ───────────────────────────────────────────────────────────────
    let ratio_guard = || -> Result<f64, String> {
        let b = bpy.ok_or_else(no_bpy)?;
        if !equity_positive {
            return Err("equity fell to or below zero, so per-bar returns are undefined \
                        (margin calls are not modelled)"
                .to_string());
        }
        if returns.len() < MIN_RETURNS_FOR_RATIOS {
            return Err(format!(
                "needs at least {MIN_RETURNS_FOR_RATIOS} per-bar returns, the run has {}",
                returns.len()
            ));
        }
        Ok(b)
    };
    let vol = ratio_guard().map(|b| sample_std(&returns) * b.sqrt() * 100.0);
    r.opt("annualised_volatility_pct", vol);
    r.opt(
        "sharpe_ratio",
        ratio_guard().and_then(|b| {
            let sd = sample_std(&returns);
            if sd < 1e-12 {
                return Err("equity never changed, so return volatility is zero".to_string());
            }
            Ok(mean(&returns) / sd * b.sqrt())
        }),
    );
    r.opt(
        "sortino_ratio",
        ratio_guard().and_then(|b| {
            let dd = (returns.iter().map(|x| x.min(0.0).powi(2)).sum::<f64>()
                / returns.len() as f64)
                .sqrt();
            if dd < 1e-12 {
                return Err("no bar had a negative return, so downside deviation is zero"
                    .to_string());
            }
            Ok(mean(&returns) / dd * b.sqrt())
        }),
    );

    // Drawdowns: running peak starts at the starting balance.
    let mut peak = s;
    let mut peak_idx: Option<usize> = None; // None = the starting balance
    let mut max_dd = 0.0_f64;
    let mut max_dd_amount = 0.0_f64;
    let mut max_dd_peak: Option<usize> = None;
    let mut max_dd_trough: Option<usize> = None;
    let mut underwater_start: Option<Option<usize>> = None;
    let mut longest_underwater = 0usize;
    let mut underwater_bars = 0usize;
    for (i, e) in equity.iter().enumerate() {
        if *e >= peak {
            peak = *e;
            peak_idx = Some(i);
            underwater_bars = 0;
            underwater_start = None;
            continue;
        }
        if underwater_start.is_none() {
            underwater_start = Some(peak_idx);
        }
        underwater_bars += 1;
        longest_underwater = longest_underwater.max(underwater_bars);
        let dd = (peak - e) / peak * 100.0;
        if dd > max_dd {
            max_dd = dd;
            max_dd_amount = peak - e;
            max_dd_peak = peak_idx;
            max_dd_trough = Some(i);
        }
    }
    let ts = |i: Option<usize>| -> Value {
        match i {
            Some(i) => json!(input.bars[i].timestamp),
            None => input.bars.first().map(|b| json!(b.timestamp)).unwrap_or(Value::Null),
        }
    };
    r.num("max_drawdown_pct", max_dd);
    r.num("max_drawdown_amount", max_dd_amount);
    if max_dd > 0.0 {
        r.set("max_drawdown_start", ts(max_dd_peak));
        r.set("max_drawdown_end", ts(max_dd_trough));
        // Recovery: first bar after the trough back at (or above) that peak.
        let peak_value = match max_dd_peak {
            Some(i) => equity[i],
            None => s,
        };
        let trough = max_dd_trough.unwrap_or(0);
        let recovered = equity.iter().enumerate().skip(trough + 1).find(|(_, e)| **e >= peak_value);
        r.set(
            "max_drawdown_recovered_at",
            recovered.map(|(i, _)| json!(input.bars[i].timestamp)).unwrap_or(Value::Null),
        );
    } else {
        r.set("max_drawdown_start", Value::Null);
        r.set("max_drawdown_end", Value::Null);
        r.set("max_drawdown_recovered_at", Value::Null);
    }
    r.int("longest_drawdown_bars", longest_underwater);
    r.num(
        "current_drawdown_pct",
        if end_equity < peak { (peak - end_equity) / peak * 100.0 } else { 0.0 },
    );
    r.opt(
        "calmar_ratio",
        annualised.and_then(|a| {
            if max_dd <= 0.0 {
                Err("no drawdown, so the ratio is undefined".to_string())
            } else {
                Ok(a / max_dd)
            }
        }),
    );

    // ── Trades (closed positions, net of commission) ───────────────────────
    // |P&L| at or below this is break-even (float noise from price arithmetic).
    const BREAKEVEN_TOLERANCE: f64 = 1e-9;
    let pnls: Vec<f64> = input.trades.iter().map(|t| t.net_pnl).collect();
    let wins: Vec<f64> = pnls.iter().copied().filter(|p| *p > BREAKEVEN_TOLERANCE).collect();
    let losses: Vec<f64> =
        pnls.iter().copied().filter(|p| *p < -BREAKEVEN_TOLERANCE).map(f64::abs).collect();
    let total = pnls.len();
    r.int("total_trades", total);
    r.int("winning_trades", wins.len());
    r.int("losing_trades", losses.len());
    r.int("breakeven_trades", total - wins.len() - losses.len());
    let no_trades = || "no closed trades".to_string();
    r.opt(
        "win_rate_pct",
        if total > 0 { Ok(wins.len() as f64 / total as f64 * 100.0) } else { Err(no_trades()) },
    );
    let avg_win = if wins.is_empty() { Err("no winning trades".to_string()) } else { Ok(mean(&wins)) };
    let avg_loss = if losses.is_empty() { Err("no losing trades".to_string()) } else { Ok(mean(&losses)) };
    r.opt("avg_win", avg_win.clone());
    r.opt("avg_loss", avg_loss.clone());
    r.opt(
        "payoff_ratio",
        match (&avg_win, &avg_loss) {
            (Ok(w), Ok(l)) => Ok(w / l),
            (Err(e), _) | (_, Err(e)) => Err(e.clone()),
        },
    );
    let gross_profit: f64 = wins.iter().sum();
    let gross_loss: f64 = losses.iter().sum();
    r.opt(
        "profit_factor",
        if total == 0 {
            Err(no_trades())
        } else if gross_loss == 0.0 {
            Err("no losing trades, so the ratio is unbounded".to_string())
        } else {
            Ok(gross_profit / gross_loss)
        },
    );
    r.opt("expectancy", if total > 0 { Ok(mean(&pnls)) } else { Err(no_trades()) });
    r.opt("largest_win", wins.iter().copied().reduce(f64::max).ok_or_else(|| "no winning trades".to_string()));
    r.opt("largest_loss", losses.iter().copied().reduce(f64::max).ok_or_else(|| "no losing trades".to_string()));
    let mut streak = 0usize;
    let mut max_streak = 0usize;
    for p in &pnls {
        if *p < -BREAKEVEN_TOLERANCE {
            streak += 1;
            max_streak = max_streak.max(streak);
        } else {
            streak = 0;
        }
    }
    r.int("max_consecutive_losses", max_streak);
    let holds: Vec<f64> = input
        .trades
        .iter()
        .filter_map(|t| t.entry_bar.map(|e| t.exit_bar.saturating_sub(e) as f64))
        .collect();
    r.opt(
        "avg_holding_bars",
        if total == 0 {
            Err(no_trades())
        } else if holds.is_empty() {
            Err("the entry bar is unknown for every closed trade".to_string())
        } else {
            Ok(mean(&holds))
        },
    );

    // ── Exposure ───────────────────────────────────────────────────────────
    let in_market = input.bars.iter().filter(|b| b.open_positions > 0).count();
    r.opt(
        "time_in_market_pct",
        if n > 0 { Ok(in_market as f64 / n as f64 * 100.0) } else { Err("no bars".to_string()) },
    );
    // Gross notional / equity. Margin is marked at the bar close, so
    // used_margin x leverage = sum of |units| x close over open positions.
    let blown = input.bars.iter().any(|b| b.open_positions > 0 && b.equity <= 0.0);
    let lev = input
        .bars
        .iter()
        .filter(|b| b.equity > 0.0 && b.open_positions > 0)
        .map(|b| b.used_margin.abs() * input.leverage / b.equity)
        .fold(f64::NAN, f64::max);
    r.opt(
        "max_gross_leverage",
        if blown {
            Err("equity fell to or below zero while positions were open, so leverage was \
                 unbounded (margin calls are not modelled)"
                .to_string())
        } else if lev.is_nan() {
            Err("no position was open at a bar close".to_string())
        } else {
            Ok(lev)
        },
    );

    // ── Costs (account currency) ───────────────────────────────────────────
    let commission = input.bars.last().map(|b| b.commissions_paid).unwrap_or(0.0);
    let spread: f64 = input.fills.iter().map(|f| f.spread_cost).sum();
    let slippage: f64 = input.fills.iter().map(|f| f.slippage_cost).sum();
    let costs = commission + spread + slippage;
    r.num("commission_cost", commission);
    r.num("spread_cost", spread);
    r.num("slippage_cost", slippage);
    r.num("total_costs", costs);
    r.num("total_costs_pct_of_starting_balance", costs / s * 100.0);

    // ── End state ──────────────────────────────────────────────────────────
    r.num("final_balance", input.final_balance);
    r.num("final_equity", input.final_equity);
    r.num("unrealised_pnl_end", input.final_equity - input.final_balance);
    r.int("open_positions_remaining", input.open_positions_remaining);

    // ── Sample and assumptions ─────────────────────────────────────────────
    let first = input.bars.first().map(|b| b.timestamp);
    let last = input.bars.last().map(|b| b.timestamp);
    let calendar_days = match (first, last) {
        (Some(a), Some(b)) => json!((b - a).num_seconds() as f64 / 86_400.0),
        _ => Value::Null,
    };
    r.set(
        "sample",
        json!({
            "bars": n,
            "return_periods": returns.len(),
            "closed_trades": total,
            "first_timestamp": first,
            "last_timestamp": last,
            "calendar_days": calendar_days,
            "years": years,
        }),
    );
    r.set(
        "assumptions",
        json!({
            "starting_balance": s,
            "currency": input.currency,
            "interval": input.interval_label,
            "bars_per_year": bpy,
            "bars_per_year_source": input.annualisation.source,
            "annualisation_note": input.annualisation.note,
            "risk_free_rate": 0.0,
            "return_basis": "end-of-bar mark-to-market equity (bar close, before exit costs); \
                             first return measured from the starting balance",
            "min_returns_for_ratios": MIN_RETURNS_FOR_RATIOS,
            "min_years_for_annualised_return": MIN_YEARS_FOR_ANNUALISED_RETURN,
            "trade_pnl_basis": "closed positions, realised P&L net of commission",
            "cost_scope": "commission, spread and slippage as charged by the configured \
                           cost model; financing / swap / funding is not modelled",
        }),
    );

    // Caveats a reader must see next to the numbers.
    let mut warnings: Vec<String> = Vec::new();
    let span_days = match (first, last) {
        (Some(a), Some(b)) => Some((b - a).num_seconds() as f64 / 86_400.0),
        _ => None,
    };
    if let (Some(y), true) = (years, r.values.get("sharpe_ratio").map_or(false, Value::is_f64)) {
        if y < MIN_YEARS_FOR_ANNUALISED_RETURN {
            let span = span_days
                .map(|d| {
                    if d >= 2.0 {
                        format!("{:.0} calendar days", d)
                    } else {
                        format!("{:.1} hours", d * 24.0)
                    }
                })
                .unwrap_or_else(|| "a short sample".to_string());
            warnings.push(format!(
                "Annualised risk ratios are extrapolated from {span} of data ({} returns); \
                 treat them as highly uncertain.",
                returns.len()
            ));
        }
    }
    // An explicit factor is the caller's statement about the market; flag it
    // when the data disagree by more than 2x (over a span of >= 4 weeks).
    if let (Some(b), Some("explicit"), Some(d)) = (bpy, input.annualisation.source, span_days) {
        if d >= 28.0 && n >= 2 {
            let observed = (n as f64 - 1.0) / (d / 365.25);
            if observed > 2.0 * b || observed < 0.5 * b {
                warnings.push(format!(
                    "bars_per_year = {} was given, but the data contain about {} bars per \
                     calendar year; check the factor.",
                    trim_float(b),
                    trim_float(observed.round())
                ));
            }
        }
    }
    if !equity_positive {
        warnings.push(
            "Equity fell to or below zero; no margin call is modelled, so later results \
             assume an account that could not exist."
                .to_string(),
        );
    }
    if input.annualisation.bars_per_year.is_none() {
        warnings.push(format!("Not annualised: {}", input.annualisation.note));
    }
    r.set("warnings", json!(warnings));

    let mut out = Map::new();
    out.insert("metrics_schema_version".into(), json!(METRICS_SCHEMA_VERSION));
    out.extend(r.values);
    out.insert(
        "unavailable".into(),
        Value::Object(r.unavailable.into_iter().map(|(k, v)| (k, Value::String(v))).collect()),
    );
    Value::Object(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn t(i: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(1_735_689_600 + i * 86_400, 0).unwrap()
    }

    fn bar(i: i64, equity: f64, open: usize) -> BarPoint {
        BarPoint { timestamp: t(i), equity, balance: equity, used_margin: 0.0, open_positions: open, commissions_paid: 0.0 }
    }

    fn input(equity: &[f64], bpy: Option<f64>) -> MetricsInput {
        MetricsInput {
            starting_balance: 100.0,
            leverage: 1.0,
            bars: equity.iter().enumerate().map(|(i, e)| bar(i as i64, *e, 1)).collect(),
            trades: vec![],
            fills: vec![],
            annualisation: Annualisation {
                bars_per_year: bpy,
                source: bpy.map(|_| "explicit"),
                note: "test".into(),
            },
            interval_label: "1d".into(),
            currency: "USD".into(),
            final_balance: *equity.last().unwrap(),
            final_equity: *equity.last().unwrap(),
            open_positions_remaining: 0,
        }
    }

    #[test]
    fn drawdown_from_the_starting_balance_is_recorded() {
        // Equity never regains the starting balance: the old tracker could
        // miss this drawdown entirely.
        let m = compute_metrics(&input(&[90.0, 80.0, 85.0], None));
        assert!((m["max_drawdown_pct"].as_f64().unwrap() - 20.0).abs() < 1e-12);
        assert!((m["max_drawdown_amount"].as_f64().unwrap() - 20.0).abs() < 1e-12);
        assert_eq!(m["max_drawdown_start"], json!(t(0)));
        assert_eq!(m["max_drawdown_end"], json!(t(1)));
        assert_eq!(m["max_drawdown_recovered_at"], Value::Null);
        assert_eq!(m["longest_drawdown_bars"], json!(3));
        assert!((m["current_drawdown_pct"].as_f64().unwrap() - 15.0).abs() < 1e-12);
    }

    #[test]
    fn short_samples_are_not_annualised() {
        let eq: Vec<f64> = (1..=40).map(|i| 100.0 + i as f64).collect();
        let m = compute_metrics(&input(&eq, Some(252.0)));
        assert_eq!(m["annualised_return_pct"], Value::Null);
        assert!(m["unavailable"]["annualised_return_pct"].as_str().unwrap().contains("one year"));
        // Sharpe is still defined (enough returns), annualised with sqrt(252).
        assert!(m["sharpe_ratio"].is_f64());
        assert_eq!(m["calmar_ratio"], Value::Null);
    }

    #[test]
    fn missing_bars_per_year_makes_annualised_metrics_unavailable() {
        let eq: Vec<f64> = (1..=400).map(|i| 100.0 + (i % 7) as f64).collect();
        let m = compute_metrics(&input(&eq, None));
        for k in ["annualised_return_pct", "sharpe_ratio", "sortino_ratio", "annualised_volatility_pct"] {
            assert_eq!(m[k], Value::Null, "{k}");
            assert_eq!(m["unavailable"][k], json!("test"), "{k}");
        }
        assert!(m["total_return_pct"].is_f64());
    }

    #[test]
    fn non_positive_equity_disables_return_ratios() {
        let mut eq: Vec<f64> = (0..40).map(|i| 100.0 - i as f64 * 3.0).collect();
        eq.push(-5.0);
        let m = compute_metrics(&input(&eq, Some(252.0)));
        assert_eq!(m["sharpe_ratio"], Value::Null);
        assert!(m["unavailable"]["sharpe_ratio"].as_str().unwrap().contains("zero"));
    }

    #[test]
    fn interval_default_requires_consistent_spacing() {
        let daily: Vec<_> = (0..10).map(t).collect();
        let a = resolve_annualisation(None, "1d", IntervalKind::Daily, &daily);
        assert_eq!(a.bars_per_year, Some(252.0));
        let hourly: Vec<_> = (0..10).map(|i| Utc.timestamp_opt(i * 3600, 0).unwrap()).collect();
        let b = resolve_annualisation(None, "1d", IntervalKind::Daily, &hourly);
        assert_eq!(b.bars_per_year, None);
        assert!(b.note.contains("1 hour"));
        let c = resolve_annualisation(None, "15m", IntervalKind::Intraday(900), &hourly);
        assert_eq!(c.bars_per_year, None);
        let d = resolve_annualisation(Some(24_192.0), "15m", IntervalKind::Intraday(900), &hourly);
        assert_eq!(d.bars_per_year, Some(24_192.0));
        assert_eq!(d.source, Some("explicit"));
        for bad in [0.0, 1e-300, 1e300, f64::NAN, -5.0] {
            let e = resolve_annualisation(Some(bad), "15m", IntervalKind::Intraday(900), &hourly);
            assert_eq!(e.bars_per_year, None, "{bad}");
        }
    }

    #[test]
    fn daily_default_follows_the_observed_calendar() {
        let day = |i: i64| Utc.timestamp_opt(1_735_689_600 + i * 86_400, 0).unwrap();
        // Weekdays only for ~6 months -> trading-day calendar -> 252.
        let weekdays: Vec<_> = (0..180).map(day).filter(|t| t.format("%u").to_string().parse::<u32>().unwrap() <= 5).collect();
        let a = resolve_annualisation(None, "1d", IntervalKind::Daily, &weekdays);
        assert_eq!(a.bars_per_year, Some(252.0), "{}", a.note);
        // Every calendar day -> 365.
        let every: Vec<_> = (0..180).map(day).collect();
        let b = resolve_annualisation(None, "1d", IntervalKind::Daily, &every);
        assert_eq!(b.bars_per_year, Some(365.0), "{}", b.note);
        // Bars two days apart labelled daily -> refused.
        let sparse: Vec<_> = (0..90).map(|i| day(i * 2)).collect();
        let c = resolve_annualisation(None, "1d", IntervalKind::Daily, &sparse);
        assert_eq!(c.bars_per_year, None);
        // Weekly bars labelled weekly -> 52; daily bars labelled weekly -> refused.
        let weekly: Vec<_> = (0..60).map(|i| day(i * 7)).collect();
        assert_eq!(resolve_annualisation(None, "1w", IntervalKind::Weekly, &weekly).bars_per_year, Some(52.0));
        assert_eq!(resolve_annualisation(None, "1w", IntervalKind::Weekly, &every).bars_per_year, None);
    }

    #[test]
    fn leverage_is_unavailable_after_equity_goes_non_positive() {
        let mut inp = input(&[100.0, 50.0, -10.0], None);
        for b in inp.bars.iter_mut() {
            b.used_margin = 20.0;
        }
        let m = compute_metrics(&inp);
        assert_eq!(m["max_gross_leverage"], Value::Null);
        assert!(m["unavailable"]["max_gross_leverage"].as_str().unwrap().contains("zero"));
        assert!(m["warnings"].as_array().unwrap().iter().any(|w| w.as_str().unwrap().contains("margin call")));
    }

    #[test]
    fn trade_statistics_and_edge_cases() {
        let mut inp = input(&[100.0, 101.0], None);
        inp.trades = vec![
            TradePoint { net_pnl: 10.0, entry_bar: Some(0), exit_bar: 4 },
            TradePoint { net_pnl: -5.0, entry_bar: Some(5), exit_bar: 7 },
            TradePoint { net_pnl: -5.0, entry_bar: Some(8), exit_bar: 9 },
            TradePoint { net_pnl: 0.0, entry_bar: Some(9), exit_bar: 10 },
        ];
        let m = compute_metrics(&inp);
        assert_eq!(m["winning_trades"], json!(1));
        assert_eq!(m["losing_trades"], json!(2));
        assert_eq!(m["breakeven_trades"], json!(1));
        assert_eq!(m["win_rate_pct"], json!(25.0));
        assert_eq!(m["payoff_ratio"], json!(2.0));
        assert_eq!(m["profit_factor"], json!(1.0));
        assert_eq!(m["expectancy"], json!(0.0));
        assert_eq!(m["max_consecutive_losses"], json!(2));
        assert_eq!(m["avg_holding_bars"], json!(2.0));
        let empty = compute_metrics(&input(&[100.0], None));
        for k in ["win_rate_pct", "profit_factor", "avg_win", "avg_loss", "payoff_ratio", "expectancy"] {
            assert_eq!(empty[k], Value::Null, "{k}");
            assert!(empty["unavailable"][k].is_string(), "{k}");
        }
    }
}
