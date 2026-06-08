use chrono::DateTime;
use chrono::Utc;
use uuid::Uuid;

use observa_core::bar::Bar;
use observa_core::events::{
    EventMetadata, OrderFilledEvent,
    PortfolioSnapshotEvent, PositionClosedEvent,
    PositionOpenedEvent,
};
use observa_core::types::{Direction, ExitReason};

use crate::error::PortfolioError;
use crate::position::Position;

// ────────────────────────────────────────────────
// PortfolioManager
// ────────────────────────────────────────────────

/// Tracks the complete financial state of a run.
///
/// Responsibilities:
/// - Open positions on entry fills
/// - Check SL/TP on every bar
/// - Close positions on exit fills or SL/TP hits
/// - Track capital, equity, and realised PnL
/// - Emit position and portfolio events
pub struct PortfolioManager {
    /// Unique run ID - stamped on every event
    run_id: Uuid,

    /// Starting and current balance
    balance: f64,

    /// All positions - open and closed
    positions: Vec<Position>,

    /// Commission per trade
    commission: f64,

    /// Total realised PnL this run
    realised_pnl: f64,

    /// Total trade completed
    total_trades: u64,
}

/// Events produced by the portfolio manager
/// after processing a fill or checking a bar.
#[derive(Debug)]
pub struct PortfolioEvents {
    pub position_opened: Option<PositionOpenedEvent>,
    pub position_closed: Option<PositionClosedEvent>,
    pub snapshot: PortfolioSnapshotEvent,
}

impl PortfolioManager {
    /// Creates a new portfolio manager
    pub fn new(
        run_id: Uuid,
        initial_balance: f64,
        commission: f64,
    ) -> Self {
        Self {
            run_id,
            balance: initial_balance,
            positions: Vec::new(),
            commission,
            realised_pnl: 0.0,
            total_trades: 0
        }
    }

    /// Returns current balance
    pub fn balance(&self) -> f64 {
        self.balance
    }

    /// Returns realised PnL
    pub fn realised_pnl(&self) -> f64 {
        self.realised_pnl
    }

    /// Returns the currently open positions if any
    pub fn total_trades(&self) -> u64 {
        self.total_trades
    }

    /// Returns the current open position if any
    pub fn open_position(&self) -> Option<&Position> {
        self.positions.iter().find(|p | p.is_open())
    }
    
    /// Calculates current equity
    /// (balance + unrealised PnL on open positions)
    pub fn equity(&self, current_price: f64) -> f64 {
        let unrealised: f64 = self.positions
            .iter()
            .filter(|p | p.is_open())
            .map(|p | p.unrealised_pnl(current_price))
            .sum();
        self.balance + unrealised
    }
    

    /// Proocess an order fill.
    /// 
    /// if direction is Buy or Sell -opens a position
    /// if direction is Close - closes the position
    pub fn process_fill(
        &mut self,
        fill: &OrderFilledEvent,        
    ) -> Result<PortfolioEvents, PortfolioError> {
        match fill.direction {
            Direction::Buy | Direction::Sell => {
                self.open_position_from_fill(fill)
            }
            Direction::Close => {
                self.close_position_from_fill(
                    fill,
                    ExitReason::Signal
                )
            }
        }
    }

    /// Checks all open positions agnaist a new bar
    /// Closes any position whose SL or TP was hit
    /// SL takes priority if both are hit in same bar
    pub fn check_sl_tp(
        &mut self,
        bar: &Bar,
    ) -> Option<PortfolioEvents> {
        // Find index of open positions with SL/TP hit
        let hit = self.positions
            .iter()
            .enumerate()
            .find(|(_, p)| p.is_open())
            .and_then(|(i,p)| {
                // SL takes priority over TP
                if let Some(sl_price) = p.check_sl(
                    bar.low, bar.high
                ) {
                    Some((i, sl_price, ExitReason::StopLoss))
                } else if let Some(tp_price) = p.check_tp(bar.low, bar.high) {
                    Some((i, tp_price, ExitReason::TakeProfit))
                } else {
                    None
                }
            });
        
        if let Some((idx, exit_price, reason)) = hit {
            let events = self.close_position_at(
                idx,
                exit_price,
                reason,
                bar.timestamp,
            );
            Some(events)
        } else {
            None
        }
    }


    /// Opens a new position from an entry fill
    fn open_position_from_fill(
        &mut self,
        fill: &OrderFilledEvent,        
    ) -> Result<PortfolioEvents, PortfolioError> {
        let position = Position::new(
            Uuid::new_v4(),
            fill.order_id,
            fill.direction,
            fill.size,
            fill.executed_price,
            fill.sl,
            fill.tp,
            fill.metadata.timestamp
        );

        let equity = self.equity(fill.executed_price);
        let pct_equity = if equity > 0.0 {
            (fill.size/equity) * 100.0
        } else {
            0.0
        };

        let pct_balance = if self.balance > 0.0 {
            (fill.size / self.balance) * 100.0
        } else {
            0.0
        };

        let position_opened = PositionOpenedEvent {
            metadata: EventMetadata::new(
                self.run_id,
                fill.metadata.timestamp,
            ),
            position_id: position.position_id,
            order_id: fill.order_id,
            direction: fill.direction,
            size: fill.size,
            entry_price: fill.executed_price,
            sl: fill.sl,
            tp: fill.tp,
            pnl: 0.0,
            pct_equity,
            pct_balance,
        };

        self.positions.push(position);

        let snapshot = self.snapshot(fill.executed_price);

        Ok(PortfolioEvents {
            position_opened: Some(position_opened),
            position_closed: None,
            snapshot,
        })
    }

    /// Closed the open position from a strategy signal
    fn close_position_from_fill(
        &mut self,
        fill: &OrderFilledEvent,
        reason: ExitReason,
    ) -> Result<PortfolioEvents, PortfolioError> {
        let idx = self.positions
            .iter()
            .position(|p | p.is_open())
            .ok_or(PortfolioError::NoOpenPosition)?;

        let events = self.close_position_at(
            idx,
            fill.executed_price,
            reason,
            fill.metadata.timestamp
        );
        Ok(events)
    }

    /// Closes position at a given index
    fn close_position_at(
        &mut self,
        idx: usize,
        exit_price: f64,
        reason: ExitReason,
        timestamp: DateTime<Utc>,
    ) -> PortfolioEvents {
        let position = &mut self.positions[idx];
        let pnl = position.close(
            exit_price,
            reason,
            timestamp,
            self.commission
        );

        self.balance += pnl;
        self.realised_pnl += pnl;
        self.total_trades += 1;

        let position = &self.positions[idx];
        let equity = self.equity(exit_price);
        let pct_equity = if equity > 0.0 {
            (position.size/ equity) *100.0
        } else {
            0.0
        };
        let pct_balance = if self.balance > 0.0 {
            (position.size/ self.balance) * 100.0
        } else {
            0.0
        };

        let position_closed = PositionClosedEvent {
            metadata: EventMetadata::new(self.run_id, timestamp),
            position_id: position.position_id,
            order_id: position.order_id,
            direction: position.direction,
            size: position.size,
            entry_price: position.entry_price,
            exit_price,
            exit_reason: reason,
            pnl,
            pct_equity,
            pct_balance,
        };

        let snapshot = self.snapshot(exit_price);

        PortfolioEvents {
            position_opened: None,
            position_closed: Some(position_closed),
            snapshot,
        }
    }

    /// Builds a portfolio snapshot at the current price
    fn snapshot(&self, current_price: f64) -> PortfolioSnapshotEvent {
        let unrealised_pnl: f64 = self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.unrealised_pnl(current_price))
            .sum();

        let equity = self.balance + unrealised_pnl;
        let margin = 0.0; //simplified for MVP
        let free_margin = equity - margin;
        let open_count = self.positions
            .iter()
            .filter(|p| p.is_open())
            .count() as u32;

        PortfolioSnapshotEvent {
            metadata: EventMetadata::new(
                self.run_id,
                Utc::now(),
                ),
            balance: self.balance,
            equity,
            margin,
            free_margin,
            unrealised_pnl,
            realised_pnl: self.realised_pnl,
            open_positions: open_count,
        }
    }
}

// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};
    use observa_core::events::EventMetadata;
    use observa_core::types::Direction;
    use uuid::Uuid;

    fn test_run_id() -> Uuid { Uuid::new_v4() }

    fn test_portfolio() -> PortfolioManager {
        PortfolioManager::new(test_run_id(), 10_000.0, 7.0)
    }

    fn buy_fill(price: f64) -> OrderFilledEvent {
        OrderFilledEvent {
            metadata:        EventMetadata::new(
                                 Uuid::new_v4(),
                                 Utc::now(),
                             ),
            order_id:        Uuid::new_v4(),
            signal_id:       Uuid::new_v4(),
            intended_price:  price,
            executed_price:  price,
            slippage:        0.0,
            spread_cost:     0.0002,
            commission:      7.0,
            size:            1.0,
            direction:       Direction::Buy,
            sl:             Some(1.1350),  
            tp:             Some(1.1420),
            reason:          "test".to_string(),
        }
    }

    fn close_fill(price: f64) -> OrderFilledEvent {
        OrderFilledEvent {
            metadata:        EventMetadata::new(
                                 Uuid::new_v4(),
                                 Utc::now(),
                             ),
            order_id:        Uuid::new_v4(),
            signal_id:       Uuid::new_v4(),
            intended_price:  price,
            executed_price:  price,
            slippage:        0.0,
            spread_cost:     0.0,
            commission:      7.0,
            size:            1.0,
            direction:       Direction::Close,
            sl:              None,  
            tp:              None,
            reason:          "test close".to_string(),
        }
    }

    fn test_bar(low: f64, high: f64) -> Bar {
        Bar::new(
            Utc::now(),
            1.1376,
            high,
            low,
            1.1376,
            None,
        )
    }

    #[test]
    fn opening_position_increases_open_count() {
        let mut pm = test_portfolio();
        let fill = buy_fill(1.13786);

        pm.process_fill(
            &fill,
        ).unwrap();

        assert!(pm.open_position().is_some());
    }

    #[test]
    fn closing_position_via_signal_updates_balance() {
        let mut pm = test_portfolio();

        // Open at 1.13786
        pm.process_fill(
            &buy_fill(1.13786)
        ).unwrap();

        // Close at 1.14186 — 40 pip profit
        pm.process_fill(
            &close_fill(1.14186)
        ).unwrap();

        assert!(pm.open_position().is_none());
        assert!(pm.balance() > 10_000.0);
        assert_eq!(pm.total_trades(), 1);
    }

    #[test]
    fn sl_hit_closes_position_at_loss() {
        let mut pm = test_portfolio();

        // Open long at 1.13786, SL at 1.1350
        pm.process_fill(
            &buy_fill(1.13786)
        ).unwrap();

        // Bar low goes below SL
        let bar = test_bar(1.1340, 1.1390);
        let events = pm.check_sl_tp(&bar);

        assert!(events.is_some());
        assert!(pm.open_position().is_none());
        assert!(pm.balance() < 10_000.0); // took a loss
    }

    #[test]
    fn tp_hit_closes_position_at_profit() {
        let mut pm = test_portfolio();

        // Open long at 1.13786, TP at 1.1420
        pm.process_fill(
            &buy_fill(1.13786)
        ).unwrap();

        // Bar high reaches TP
        let bar = test_bar(1.1370, 1.1430);
        let events = pm.check_sl_tp(&bar);

        assert!(events.is_some());
        assert!(pm.open_position().is_none());
        assert!(pm.balance() > 10_000.0); // made profit
    }

    #[test]
    fn no_sl_tp_hit_returns_none() {
        let mut pm = test_portfolio();

        pm.process_fill(
            &buy_fill(1.13786)
        ).unwrap();

        // Bar stays within SL/TP range
        let bar = test_bar(1.1360, 1.1410);
        let events = pm.check_sl_tp(&bar);

        assert!(events.is_none());
        assert!(pm.open_position().is_some()); // still open
    }

    #[test]
    fn closing_when_no_position_returns_error() {
        let mut pm = test_portfolio();
        let fill = close_fill(1.13786);

        let result = pm.process_fill(&fill);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            PortfolioError::NoOpenPosition
        ));
    }

    #[test]
    fn equity_reflects_unrealised_pnl() {
        let mut pm = test_portfolio();

        pm.process_fill(
            &buy_fill(1.13786)
        ).unwrap();

        // Price moved up — equity should be higher
        let equity_up = pm.equity(1.14000);
        assert!(equity_up > 10_000.0);

        // Price moved down — equity should be lower
        let equity_down = pm.equity(1.13500);
        assert!(equity_down < 10_000.0);
    }
}
