use chrono::{DateTime, Utc};
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

pub struct PortfolioEvents {
    pub position_opened: Option<PositionOpenedEvent>,
    pub position_closed: Option<PositionClosedEvent>,
    pub snapshot:        PortfolioSnapshotEvent,
}

pub struct PortfolioManager {
    run_id:       Uuid,
    balance:      f64,
    positions:    Vec<Position>,
    commission:   f64,
    slippage:     f64,
    realised_pnl: f64,
    total_trades: u64,
}

impl PortfolioManager {
    pub fn new(
        run_id:          Uuid,
        initial_balance: f64,
        commission:      f64,
        slippage:        f64,
    ) -> Self {
        Self {
            run_id,
            balance: initial_balance,
            positions: Vec::new(),
            commission,
            slippage,
            realised_pnl: 0.0,
            total_trades: 0,
        }
    }

    pub fn balance(&self) -> f64 { self.balance }
    pub fn realised_pnl(&self) -> f64 { self.realised_pnl }
    pub fn total_trades(&self) -> u64 { self.total_trades }

    /// Returns all currently open positions
    pub fn open_positions(&self) -> Vec<&Position> {
        self.positions.iter().filter(|p| p.is_open()).collect()
    }

    /// Returns the first open position — kept for backward compat
    pub fn open_position(&self) -> Option<&Position> {
        self.positions.iter().find(|p| p.is_open())
    }

    /// True equity including unrealised PnL at current_price
    pub fn equity(&self, current_price: f64) -> f64 {
        let unrealised: f64 = self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.unrealised_pnl(current_price))
            .sum();
        self.balance + unrealised
    }

    /// Total unrealised PnL at current_price
    pub fn unrealised_pnl(&self, current_price: f64) -> f64 {
        self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.unrealised_pnl(current_price))
            .sum()
    }

    /// Processes an order fill.
    /// For Buy/Sell — opens a new position.
    /// For Close — closes the position matching the ticket.
    pub fn process_fill(
        &mut self,
        fill:   &OrderFilledEvent,
        ticket: Option<String>,
    ) -> Result<PortfolioEvents, PortfolioError> {
        match fill.direction {
            Direction::Buy | Direction::Sell => {
                self.open_position_from_fill(fill)
            }
            Direction::Close => {
                self.close_position_by_ticket(
                    fill,
                    ticket,
                    ExitReason::Signal,
                )
            }
        }
    }

    /// Checks all open positions for SL/TP hits on this bar.
    /// Returns events for the first hit found.
    /// SL takes priority over TP within the same position.
    pub fn check_sl_tp(
        &mut self,
        bar: &Bar,
    ) -> Vec<PortfolioEvents> {
        let mut results = Vec::new();

        // Collect indices of positions with SL/TP hit
        let hits: Vec<(usize, f64, ExitReason)> = self.positions
            .iter()
            .enumerate()
            .filter(|(_, p)| p.is_open())
            .filter_map(|(i, p)| {
                if let Some(sl_price) = p.check_sl(bar.low, bar.high) {
                    // SL hit — apply slippage (market order)
                    let exit_price = match p.direction {
                        Direction::Buy  => sl_price - self.slippage,
                        Direction::Sell => sl_price + self.slippage,
                        Direction::Close => sl_price,
                    };
                    Some((i, exit_price, ExitReason::StopLoss))
                } else if let Some(tp_price) = p.check_tp(bar.low, bar.high) {
                    // TP hit — no slippage (limit order)
                    Some((i, tp_price, ExitReason::TakeProfit))
                } else {
                    None
                }
            })
            .collect();

        // Process hits in reverse index order to avoid
        // index shifting when removing positions
        let mut indices: Vec<usize> = hits.iter().map(|(i,_,_)| *i).collect();
        indices.sort_unstable_by(|a, b| b.cmp(a));

        for (orig_idx, exit_price, reason) in hits {
            let events = self.close_position_at(
                orig_idx,
                exit_price,
                reason,
                bar.timestamp,
            );
            results.push(events);
        }

        results
    }

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
            fill.metadata.timestamp,
        );

        let equity      = self.equity(fill.executed_price);
        let pct_equity  = if equity > 0.0 {
            (fill.size / equity) * 100.0
        } else { 0.0 };
        let pct_balance = if self.balance > 0.0 {
            (fill.size / self.balance) * 100.0
        } else { 0.0 };

        let position_opened = PositionOpenedEvent {
            metadata:    EventMetadata::new(
                             self.run_id,
                             fill.metadata.timestamp,
                         ),
            position_id: position.position_id,
            order_id:    fill.order_id,
            direction:   fill.direction,
            size:        fill.size,
            entry_price: fill.executed_price,
            sl:          fill.sl,
            tp:          fill.tp,
            pnl:         0.0,
            pct_equity,
            pct_balance,
        };

        self.positions.push(position);

        let snapshot = self.snapshot(fill.executed_price, fill.metadata.timestamp);

        Ok(PortfolioEvents {
            position_opened: Some(position_opened),
            position_closed: None,
            snapshot,
        })
    }

    /// Closes a position by ticket UUID string.
    /// Falls back to closing the oldest open position
    /// if no ticket is provided (backward compatibility).
    fn close_position_by_ticket(
        &mut self,
        fill:   &OrderFilledEvent,
        ticket: Option<String>,
        reason: ExitReason,
    ) -> Result<PortfolioEvents, PortfolioError> {
        let idx = match ticket {
            Some(ref t) => {
                // Find position matching this ticket
                self.positions
                    .iter()
                    .position(|p| {
                        p.is_open() &&
                        p.position_id.to_string() == *t
                    })
                    .ok_or_else(|| PortfolioError::PositionNotFound {
                        position_id: t.clone()
                    })?
            }
            None => {
                // No ticket — close oldest open position (FIFO)
                self.positions
                    .iter()
                    .position(|p| p.is_open())
                    .ok_or(PortfolioError::NoOpenPosition)?
            }
        };

        let events = self.close_position_at(
            idx,
            fill.executed_price,
            reason,
            fill.metadata.timestamp,
        );
        Ok(events)
    }

    fn close_position_at(
        &mut self,
        idx:        usize,
        exit_price: f64,
        reason:     ExitReason,
        timestamp:  DateTime<Utc>,
    ) -> PortfolioEvents {
        let position = &mut self.positions[idx];
        let pnl = position.close(
            exit_price,
            reason,
            timestamp,
            self.commission,
        );

        self.balance      += pnl;
        self.realised_pnl += pnl;
        self.total_trades += 1;

        let position    = &self.positions[idx];
        let equity      = self.equity(exit_price);
        let pct_equity  = if equity > 0.0 {
            (position.size / equity) * 100.0
        } else { 0.0 };
        let pct_balance = if self.balance > 0.0 {
            (position.size / self.balance) * 100.0
        } else { 0.0 };

        let position_closed = PositionClosedEvent {
            metadata:    EventMetadata::new(self.run_id, timestamp),
            position_id: position.position_id,
            order_id:    position.order_id,
            direction:   position.direction,
            size:        position.size,
            entry_price: position.entry_price,
            exit_price,
            exit_reason: reason,
            pnl,
            pct_equity,
            pct_balance,
        };

        let snapshot = self.snapshot(exit_price, timestamp);

        PortfolioEvents {
            position_opened: None,
            position_closed: Some(position_closed),
            snapshot,
        }
    }

    fn snapshot(
        &self,
        current_price: f64,
        timestamp:     DateTime<Utc>,
    ) -> PortfolioSnapshotEvent {
        let unrealised_pnl: f64 = self.positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| p.unrealised_pnl(current_price))
            .sum();

        let equity      = self.balance + unrealised_pnl;
        let open_count  = self.positions
            .iter()
            .filter(|p| p.is_open())
            .count() as u32;

        PortfolioSnapshotEvent {
            metadata:        EventMetadata::new(self.run_id, timestamp),
            balance:         self.balance,
            equity,
            margin:          0.0,
            free_margin:     equity,
            unrealised_pnl,
            realised_pnl:    self.realised_pnl,
            open_positions:  open_count,
        }
    }
}
// ────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use observa_core::bar::Bar;
    use observa_core::events::{EventMetadata, OrderFilledEvent};
    use observa_core::types::Direction;
    use uuid::Uuid;

    fn test_run_id() -> Uuid {
        Uuid::new_v4()
    }

    fn test_portfolio() -> PortfolioManager {
        PortfolioManager::new(test_run_id(), 10_000.0, 7.0, 0.0001)
    }

    fn buy_fill(price: f64) -> OrderFilledEvent {
        OrderFilledEvent {
            metadata: EventMetadata::new(Uuid::new_v4(), Utc::now()),
            order_id: Uuid::new_v4(),
            signal_id: Uuid::new_v4(),
            intended_price: price,
            executed_price: price,
            slippage: 0.0,
            spread_cost: 0.0002,
            commission: 7.0,
            size: 1.0,
            direction: Direction::Buy,
            sl: Some(1.1350),
            tp: Some(1.1420),
            reason: "test".to_string(),
        }
    }

    fn close_fill(price: f64, order_id: Uuid) -> OrderFilledEvent {
        OrderFilledEvent {
            metadata: EventMetadata::new(Uuid::new_v4(), Utc::now()),
            order_id,
            signal_id: Uuid::new_v4(),
            intended_price: price,
            executed_price: price,
            slippage: 0.0,
            spread_cost: 0.0,
            commission: 7.0,
            size: 1.0,
            direction: Direction::Close,
            sl: None,
            tp: None,
            reason: "test close".to_string(),
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

    fn first_position_id(pm: &PortfolioManager) -> String {
        pm.open_position()
            .unwrap()
            .position_id
            .to_string()
    }

    #[test]
    fn opening_position_increases_open_count() {
        let mut pm = test_portfolio();

        let fill = buy_fill(1.13786);

        pm.process_fill(&fill, None).unwrap();

        assert!(pm.open_position().is_some());
    }

    #[test]
    fn closing_position_via_signal_updates_balance() {
        let mut pm = test_portfolio();

        let open = buy_fill(1.13786);

        pm.process_fill(&open, None).unwrap();

        pm.process_fill(
            &close_fill(1.14186, open.order_id),
            None,
        )
        .unwrap();

        assert!(pm.open_position().is_none());
        assert!(pm.balance() > 10_000.0);
        assert_eq!(pm.total_trades(), 1);
    }

    #[test]
    fn sl_hit_closes_position_at_loss() {
        let mut pm = test_portfolio();

        pm.process_fill(&buy_fill(1.13786), None)
            .unwrap();

        let bar = test_bar(1.1340, 1.1390);

        let events = pm.check_sl_tp(&bar);

        assert_eq!(events.len(), 1);
        assert!(pm.open_position().is_none());
        assert!(pm.balance() < 10_000.0);
    }

    #[test]
    fn tp_hit_closes_position_at_profit() {
        let mut pm = test_portfolio();

        pm.process_fill(&buy_fill(1.13786), None)
            .unwrap();

        let bar = test_bar(1.1370, 1.1430);

        let events = pm.check_sl_tp(&bar);

        assert_eq!(events.len(), 1);
        assert!(pm.open_position().is_none());
        assert!(pm.balance() > 10_000.0);
    }

    #[test]
    fn no_sl_tp_hit_returns_empty_vec() {
        let mut pm = test_portfolio();

        pm.process_fill(&buy_fill(1.13786), None)
            .unwrap();

        let bar = test_bar(1.1360, 1.1410);

        let events = pm.check_sl_tp(&bar);

        assert!(events.is_empty());
        assert!(pm.open_position().is_some());
    }

    #[test]
    fn closing_when_no_position_returns_error() {
        let mut pm = test_portfolio();

        let fill = close_fill(1.13786, Uuid::new_v4());

        let result = pm.process_fill(&fill, None);

        assert!(matches!(
            result,
            Err(PortfolioError::NoOpenPosition)
        ));
    }

    #[test]
    fn equity_reflects_unrealised_pnl() {
        let mut pm = test_portfolio();

        pm.process_fill(&buy_fill(1.13786), None)
            .unwrap();

        let equity_up = pm.equity(1.14000);
        assert!(equity_up > 10_000.0);

        let equity_down = pm.equity(1.13500);
        assert!(equity_down < 10_000.0);
    }

    #[test]
    fn closing_position_by_ticket_succeeds() {
        let mut pm = test_portfolio();

        let open = buy_fill(1.13786);

        pm.process_fill(&open, None).unwrap();

        let ticket = first_position_id(&pm);

        pm.process_fill(
            &close_fill(1.14186, open.order_id),
            Some(ticket),
        )
        .unwrap();

        assert!(pm.open_position().is_none());
        assert_eq!(pm.total_trades(), 1);
        assert!(pm.balance() > 10_000.0);
    }

    #[test]
    fn invalid_ticket_returns_position_not_found() {
        let mut pm = test_portfolio();

        let open = buy_fill(1.13786);

        pm.process_fill(&open, None).unwrap();

        let result = pm.process_fill(
            &close_fill(1.14186, open.order_id),
            Some(Uuid::new_v4().to_string()),
        );

        assert!(matches!(
            result,
            Err(PortfolioError::PositionNotFound { .. })
        ));
    }

    #[test]
    fn closing_without_ticket_uses_fifo() {
        let mut pm = test_portfolio();

        let open = buy_fill(1.13786);

        pm.process_fill(&open, None).unwrap();

        pm.process_fill(
            &close_fill(1.14186, open.order_id),
            None,
        )
        .unwrap();

        assert!(pm.open_position().is_none());
        assert_eq!(pm.total_trades(), 1);
    }

    #[test]
    fn ticket_closes_correct_position() {
        let mut pm = test_portfolio();

        let first_fill = buy_fill(1.13786);
        pm.process_fill(&first_fill, None)
            .unwrap();

        let first_ticket = first_position_id(&pm);

        let second_fill = buy_fill(1.13850);
        pm.process_fill(&second_fill, None)
            .unwrap();

        let second_ticket = pm
            .open_positions()
            .into_iter()
            .find(|p| p.position_id.to_string() != first_ticket)
            .unwrap()
            .position_id
            .to_string();

        pm.process_fill(
            &close_fill(1.14186, second_fill.order_id),
            Some(second_ticket),
        )
        .unwrap();

        let remaining = pm.open_positions();

        assert_eq!(remaining.len(), 1);
        assert_eq!(
            remaining[0].position_id.to_string(),
            first_ticket
        );
    }
}