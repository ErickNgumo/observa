//! Execution model — applies spread, slippage, commission.
use chrono::Utc;


use observa_core::bar::Bar;
use observa_core::events::{
    EventMetadata, OrderFilledEvent,
    OrderIntentCreatedEvent, OrderRejectedEvent
};
use observa_core::types::{Direction,RejectionReason};

use crate::error::ExecutionError;

// ────────────────────────────────────────────────
// FillMode
// ────────────────────────────────────────────────
//
// NOTE (OBS-0004): LEGACY type. The canonical fill-mode model is
// `observa_core::config::FillMode` (BAR_CLOSE / NEXT_BAR_OPEN). This enum is
// the historical execution-crate representation and is scheduled for removal
// when the execution model is rebuilt in OBS-0006.

/// Controls when and at what price a market order fills.
#[derive(Debug, Clone, Copy)]
pub enum FillMode {
    ///Fill at close of the signal bar plus spread
    /// Simpler but slightly optimistic
    ThisBarClose,

    ///Fill at open of the next bar plus spread.
    /// More realistic - this is the default.
    NextBarOpen,    
}

// ────────────────────────────────────────────────
// ExecutionConfig
// ────────────────────────────────────────────────
//
// NOTE (OBS-0004): LEGACY type. The canonical execution configuration lives
// in `observa_core::config::ExecutionConfig`. This struct is the historical
// execution-crate representation consumed by the pre-OBS-0007 CLI and is
// scheduled for removal in OBS-0006.

///Configuration of the execution model.
/// All values are fixed for MVP - dynamic models come later.
#[derive(Debug, Clone)]
pub struct ExecutionConfig {
    /// Fixed spread in price units e.g. 0.0002 = 2 pips
    pub spread: f64,

    /// Fixed slippage in price units
    pub slippage: f64,

    /// Commission per trade in account currency
    pub commission: f64,

    /// Minimum stop distance in price units
    pub min_stop_distance: f64,

    /// Minimum lot size
    pub min_lot_size: f64,

    ///Max_lot_size
    pub max_lot_size: f64,

    /// Fill mode - when does a market order fill?
    pub fill_mode: FillMode,
}

impl ExecutionConfig {
    ///Creates a sensible default config for EURUSD
    pub fn default_eurusd() -> Self {
        Self {
            spread: 0.0002, //2 pips
            slippage: 0.0001, //1 pip
            commission: 7.0, //$7 per trade
            min_stop_distance: 0.0010, //10pips
            min_lot_size: 0.01, //micro lot
            max_lot_size: 100.0, //100 lots
            fill_mode: FillMode::NextBarOpen,
        }
    }
}

// ────────────────────────────────────────────────
// FillResult
// ────────────────────────────────────────────────

/// The outcome of processing an order intent.
/// Either a fill or a rejection — never both.
#[derive(Debug)]
pub enum FillResult {
    Filled(OrderFilledEvent),
    Rejected(OrderRejectedEvent),
}

// ────────────────────────────────────────────────
// ExecutionModel
// ────────────────────────────────────────────────

/// The realism layer between intent and fill.
///
/// Takes an OrderIntent and a current bar and
/// returns either a fill or a rejection.
///
/// This is the ONLY place in Observa where spread,
/// slippage, and commission are applied.

pub struct ExecutionModel {
    config: ExecutionConfig,
}

impl ExecutionModel {
    //Creates a new execution model
    pub fn new(config: ExecutionConfig) -> Self {
        Self {config}
    }

    /// Processes an order intent agnaist the  current bar/
    /// 
    /// For NextBarOpen mode, pass the Next bar.
    /// For ThisBarClose mode, pass the current bar.
    pub fn process(
        &self,
        intent: &OrderIntentCreatedEvent,
        fill_bar: &Bar,
    ) -> Result<FillResult, ExecutionError> {

        // Step 1 — calculate fill price first
        let (base_price, slippage_amount) = match intent.direction {
            Direction::Buy => (
                fill_bar.open + self.config.spread,
                self.config.slippage,
            ),
            Direction::Sell => (
                fill_bar.open - self.config.spread,
                -self.config.slippage,
            ),
            Direction::Close => (fill_bar.open, 0.0),
        };

        let executed_price = base_price + slippage_amount;

        // Step 2 — validate AFTER slippage is known
        // This is correct because the trader's SL/TP distances
        // must be valid relative to the actual fill price,
        // not the intended price before market impact
        //
        // NOTE (OBS-0005): the execution layer performs NO margin acceptance.
        // Margin capacity is evaluated exclusively by the canonical portfolio
        // model (`observa_portfolio::portfolio::can_open` / `free_margin`),
        // which is the single financial authority. Any order that passes the
        // validation rules here is returned as a fill; the portfolio decides
        // whether it can actually be opened.
        if let Some(rejection) = self.validate_after_fill(intent, executed_price) {
            return Ok(FillResult::Rejected(rejection));
        }

        // Step 3 — build the fill event
        let fill = OrderFilledEvent {
            metadata:        EventMetadata::new(
                                intent.metadata.run_id,
                                fill_bar.timestamp,
                            ),
            order_id:        intent.order_id,
            signal_id:       intent.signal_id,
            intended_price:  intent.intended_price,
            executed_price,
            slippage:        executed_price - intent.intended_price,
            spread_cost:     self.config.spread * intent.size,
            commission:      self.config.commission,
            size:            intent.size,
            direction:       intent.direction,
            reason:          intent.reason.clone(),
            sl:              intent.sl,
            tp:              intent.tp,
        };

        Ok(FillResult::Filled(fill))
    }

    /// Validates an order intent.
    /// Returns Some(rejection) if invalid, None if valid.
    ///
    /// Validation covers order-domain rules only (quantity bounds, protective
    /// distance). Margin acceptance is deliberately NOT performed here — it is
    /// the exclusive responsibility of the canonical portfolio model (OBS-0005).
    fn validate_after_fill(
        &self,
        intent: &OrderIntentCreatedEvent,
        executed_price: f64,  // ← actual fill price after slippage
    ) -> Option<OrderRejectedEvent> {
        let run_id = intent.metadata.run_id;
        let now    = Utc::now();

        // Close orders bypass all validation
        if intent.direction == Direction::Close {
            return None;
        }

        // Rule 1 — lot size within bounds
        if intent.size < self.config.min_lot_size
            || intent.size > self.config.max_lot_size
        {
            let reason = RejectionReason::InvalidSize {
                requested: intent.size,
                min_size:  self.config.min_lot_size,
                max_size:  self.config.max_lot_size,
            };
            let detail = reason.to_string();
            return Some(OrderRejectedEvent {
                metadata:         EventMetadata::new(run_id, now),
                order_id:         intent.order_id,
                signal_id:        intent.signal_id,
                rejection_reason: reason,
                rejection_detail: detail,
            });
        }

        // Rule 2 — SL distance from ACTUAL fill price (not intended)
        // This is the key fix — we validate against executed_price
        // because that's where the position actually opens
        if let Some(sl) = intent.sl {
            let distance = (executed_price - sl).abs();
            if distance < self.config.min_stop_distance {
                let reason = RejectionReason::InvalidStop {
                    entry_price:  executed_price,
                    sl_price:     sl,
                    min_distance: self.config.min_stop_distance,
                };
                let detail = reason.to_string();
                return Some(OrderRejectedEvent {
                    metadata:         EventMetadata::new(run_id, now),
                    order_id:         intent.order_id,
                    signal_id:        intent.signal_id,
                    rejection_reason: reason,
                    rejection_detail: detail,
                });
            }
        }

        // Rule 3 — TP distance from ACTUAL fill price
        if let Some(tp) = intent.tp {
            let distance = (executed_price - tp).abs();
            if distance < self.config.min_stop_distance {
                let reason = RejectionReason::InvalidTakeProfit {
                    entry_price:  executed_price,
                    tp_price:     tp,
                    min_distance: self.config.min_stop_distance,
                };
                let detail = reason.to_string();
                return Some(OrderRejectedEvent {
                    metadata:         EventMetadata::new(run_id, now),
                    order_id:         intent.order_id,
                    signal_id:        intent.signal_id,
                    rejection_reason: reason,
                    rejection_detail: detail,
                });
            }
        }

        None
    }
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use observa_core::events::EventMetadata;
    use observa_core::types::Direction;
    use uuid::Uuid;

    fn test_config() -> ExecutionConfig {
        ExecutionConfig::default_eurusd()
    }

    fn test_intent (
        direction: Direction,
        size: f64,
        sl: Option<f64>,
        tp: Option<f64>,
    ) -> OrderIntentCreatedEvent {
        OrderIntentCreatedEvent{
            metadata: EventMetadata::new(
                            Uuid::new_v4(),
                            Utc::now(),
                ),
            order_id: Uuid::new_v4(),
            signal_id: Uuid::new_v4(),
            direction,
            size,
            intended_price: 1.13786,
            sl,
            tp,
            reason: "test".to_string()
        }
    }

    fn test_bar () -> Bar {
        Bar::new(
            Utc::now(),
            1.1379,
            1.13820,
            1.13667,
            1.13722,
            Some(155.54),
        )
    }

    #[test]
    fn buy_order_fills_at_ask_plus_slippage() {
        let model = ExecutionModel::new(test_config());
        let intent = test_intent(
            Direction::Buy,
            1.0,
            Some(1.1350), //29 pip stop -valid
            Some(1.1420), //41 pip stop -valid
        );
        let bar = test_bar();

        let result = model.process(&intent, &bar)
            .unwrap();

        match result {
            FillResult::Filled(fill) => {
                let expected = bar.open
                    + test_config().spread
                    + test_config().slippage;
                assert!((fill.executed_price - expected).abs() < 0.000001);
                assert_eq!(fill.direction, Direction::Buy);
                assert_eq!(fill.commission, 7.0);
            }
            FillResult::Rejected(r) => {
                panic!("Expected fill, got rejection: {}", r.rejection_detail);
            }
        }
    }

    #[test]
    fn sell_order_fills_at_bid_minus_slippage () {
        let model = ExecutionModel::new(test_config());
        let intent =test_intent(
            Direction::Sell,
            1.0,
            Some(1.1420), //stop above - valid sell
            Some(1.1350), //tp below - valid for sell
        );

        let bar = test_bar();

        let result = model.process(&intent, &bar)
            .unwrap();

        match result {
            FillResult::Filled(fill) => {
                //Sell fills at bid = open-spread-slippage
                let expected = bar.open
                    -test_config().spread
                    -test_config().slippage;
                assert!((fill.executed_price - expected).abs() < 0.000001);
                assert_eq!(fill.direction, Direction::Sell);
            }
            FillResult::Rejected(r) => {
                panic!("Exepected fill, got rejection: {}", r.rejection_detail);
            }
        }
    }

    #[test]
    fn order_rejected_when_stop_too_close() {
        let model = ExecutionModel::new(test_config());
        let intent = test_intent(
            Direction::Buy,
            1.0,
            Some(1.13785), //only 0.5 pip away - too close
            Some(1.1420)
        );

        let result = model.process(&intent, &test_bar())
            .unwrap();

        assert!(matches!(result, FillResult::Rejected(_)));
        if let FillResult::Rejected(r) = result {
            assert!(matches!(
                r.rejection_reason,
                RejectionReason::InvalidStop { .. }
            ));
        }
    }

    #[test]
    fn order_rejected_when_size_too_small() {
        let model = ExecutionModel::new(test_config());
        let intent = test_intent(
            Direction::Buy,
            0.001, //below min_lot_size of 0.01
            Some(1.1350),
            Some(1.1420),
        );

        let result = model.process(&intent, &test_bar())
            .unwrap();

        assert!(matches!(result, FillResult::Rejected(_)));
        if let FillResult::Rejected(r) = result {
            assert!(matches!(
                r.rejection_reason,
                RejectionReason::InvalidSize { .. }
            ));
        }
    }

    #[test]
    fn execution_has_no_margin_authority() {
        // Regression test for the OBS-0005 QA blocker: the execution layer
        // must NOT independently reject an order based on the obsolete
        // `price × size × 1000 × 0.01` margin formula. Margin acceptance is
        // the exclusive responsibility of the canonical portfolio model
        // (`PortfolioManager::can_open`).
        //
        // QA counter-example (equity-style instrument) that the old formula
        // wrongly rejected while the canonical model accepts:
        //   contract_size = 1, leverage = 4, balance = 20,000,
        //   quantity = 100, price = 182.50
        //   canonical margin = 100 × 1 × 182.50 / 4 = 4,562.50  → ACCEPT
        //   legacy formula    = 182.50 × 100 × 1000 × 0.01 = 182,500 → REJECT
        //
        // Execution holds no contract/leverage/balance knowledge, so a large
        // in-bounds order must simply produce a fill here; whether the account
        // can support it is decided by the portfolio.
        let model = ExecutionModel::new(test_config());
        let intent = test_intent(
            Direction::Buy,
            100.0, // at the max-lot bound; the old rule would have rejected it
            Some(1.1350),
            Some(1.1420),
        );

        let result = model.process(&intent, &test_bar()).unwrap();

        assert!(matches!(result, FillResult::Filled(_)));
        // The obsolete rejection reason must never be produced by execution.
        if let FillResult::Rejected(r) = result {
            assert!(!matches!(
                r.rejection_reason,
                RejectionReason::InsufficientCapital { .. }
            ));
            panic!("expected fill, got rejection: {}", r.rejection_detail);
        }
    }

    #[test]
    fn slippage_always_work_agnaist_trader() {
        let model = ExecutionModel::new(test_config());
        let bar = test_bar();

        //Buy - slippage pushes price higher (worse for buyer)
        let buy_intent = test_intent(
            Direction::Buy,
            1.0,
            Some(1.1350),
            Some(1.1420),
        );
        if let FillResult::Filled(fill) = model
            .process(&buy_intent, &bar).unwrap()
        {
            assert!(fill.executed_price > bar.open);
        }

        // Sell - slippage pushes price lower (worse for seller)
        let sell_intent = test_intent(
            Direction::Sell,
            1.0,
            Some(1.1420),
            Some(1.1350),
        );
        if let FillResult::Filled(fill) = model
            .process(&sell_intent, &bar).unwrap()
        {
            assert!(fill.executed_price < bar.open);
        }
    }
}