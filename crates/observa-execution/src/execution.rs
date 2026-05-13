//! Execution model — applies spread, slippage, commission.
use chrono::Utc;
use uuid::Uuid;


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
    pub fn process (
        &self,
        intent: &OrderIntentCreatedEvent,
        fill_bar: &Bar,
        account_balance: f64,
    ) -> Result<FillResult, ExecutionError> {
        //step 1 - validate the order
        if let Some(rejection) = self.validate(
            intent,
            fill_bar,
            account_balance,
        ) {
            return Ok(FillResult::Rejected(rejection));
        }

        //Step 2 - calculate fill price
        let base_price = match intent.direction {
            // Buying - fill at ask (base +spread)
            Direction::Buy => fill_bar.open + self.config.spread,

            //Selling - fill at bid (base - spread)
            Direction::Sell => fill_bar.open - self.config.spread,
        };

        //Step 3 - apply slippage
        let slippage = match intent.direction {
            // Slippage always works against the trader
            Direction::Buy  =>  self.config.slippage,
            Direction::Sell => -self.config.slippage,
        };

        let executed_price = base_price + slippage;

        //Step 4 - build the fill event
        let fill = OrderFilledEvent {
            metadata: EventMetadata::new(
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
        };
        
        Ok(FillResult::Filled(fill))
        
    }

    /// Validates an order intent.
    /// Returns Some(rejection) if invalid, None if valid.
    fn validate(
        &self,
        intent: &OrderIntentCreatedEvent,
        fill_bar: &Bar,
        account_balance: f64,
    ) -> Option<OrderRejectedEvent> {
        let run_id = intent.metadata.run_id;
        let now = Utc::now();

        // Rule 1 — lot size must be within bounds
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
                metadata: EventMetadata::new(run_id, now),
                order_id: intent.order_id,
                signal_id: intent.signal_id,
                rejection_reason: reason,
                rejection_detail: detail,
            });
        }

        // Rule 2 — stop loss must be far enough away
        if let Some(sl) = intent.sl {
            let distance = (fill_bar.open - sl).abs();
            if distance < self.config.min_stop_distance {
                let reason = RejectionReason::InvalidStop {
                    entry_price:  fill_bar.open,
                    sl_price:     sl,
                    min_distance: self.config.min_stop_distance,
                };
                let detail = reason.to_string();
                return Some(OrderRejectedEvent {
                    metadata: EventMetadata::new(run_id, now),
                    order_id: intent.order_id,
                    signal_id: intent.signal_id,
                    rejection_reason: reason,
                    rejection_detail: detail,
                });
            }
        }

        // Rule 3 — take profit must be far enough away
        if let Some(tp) = intent.tp {
            let distance = (fill_bar.open - tp).abs();
            if distance < self.config.min_stop_distance {
                let reason = RejectionReason::InvalidTakeProfit {
                    entry_price:  fill_bar.open,
                    tp_price:     tp,
                    min_distance: self.config.min_stop_distance,
                };
                let detail = reason.to_string();
                return Some(OrderRejectedEvent {
                    metadata: EventMetadata::new(run_id, now),
                    order_id: intent.order_id,
                    signal_id: intent.signal_id,
                    rejection_reason: reason,
                    rejection_detail: detail,
                });
            }
        }

        // Rule 4 — sufficient capital
        let required_margin = fill_bar.open
            * intent.size
            * 1000.0  // contract size placeholder
            * 0.01;   // 1% margin requirement

        if required_margin > account_balance {
            let reason = RejectionReason::InsufficientCapital {
                required:  required_margin,
                available: account_balance,
            };
            let detail = reason.to_string();
            return Some(OrderRejectedEvent {
                metadata: EventMetadata::new(run_id, now),
                order_id: intent.order_id,
                signal_id: intent.signal_id,
                rejection_reason: reason,
                rejection_detail: detail,
            });
        }

        None // all rules passed
    }
}
