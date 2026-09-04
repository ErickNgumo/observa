# Observa Architectural Decisions

This document separates **historical decisions** from **current invariants**. Historical decisions explain why the project reached its present shape; they are not all permanently immutable.

## ADR-001 — Event sourcing

**Decision:** Use immutable events as the source of truth and primary communication mechanism.

**Reason:** Observability, replayability, auditability, and debugging are central to the product.

**Alternatives:** Direct method calls between components.

**Status:** Core architectural invariant; do not change casually.

## ADR-002 — Rust engine

**Decision:** Core engine in Rust.

**Reason:** Determinism, memory safety, performance, and explicit ownership.

**Tradeoff:** Rust/Python FFI complexity and packaging complexity.

**Status:** Approved; no current proposal to replace it.

## ADR-003 — Python strategies

**Decision:** Trader-written strategies remain Python classes.

**Reason:** Accessibility for algorithmic traders and alignment with ecosystem practice.

**Status:** Approved for current direction; WASM is a future possibility, not a current replacement.

## ADR-004 — CLI as initial interface

**Historical decision:** CLI was chosen because it was faster to build and avoided early packaging complexity.

**Current review:** The historical reason no longer automatically defines product distribution. Engineering leadership now proposes pip installation as an MVP requirement.

**Status:** CLI remains part of MVP; packaging decision is being revised.

## ADR-005 — Ticket-based closing

**Decision:** Positions can be targeted by ticket UUID.

**Reason:** Supports multiple simultaneous positions and partial/selective exits.

**Status:** Approved for current MVP.

## ADR-006 — Validate SL/TP after fill calculation

**Decision:** Validate stop/target distance from actual executed fill price.

**Reason:** Slippage changes actual entry price.

**Status:** Financial execution invariant.

## ADR-007 — SL slippage / TP no slippage

**Decision:** Apply slippage to SL exits but not TP exits.

**Reason:** SL is treated as market execution; TP as limit execution.

**Status:** Current execution rule.

## ADR-008 — Mark-to-market equity every bar

**Decision:** Emit portfolio snapshots on every bar.

**Reason:** Equity returns must use equally spaced observations; trade-close-only sampling caused distorted Sharpe calculations.

**Status:** Current metrics architecture invariant.

## ADR-009 — Sharpe sample variance and compound risk-free conversion

**Decision:** Historical implementation changed to sample variance and compound conversion.

**Reason:** Improve statistical formulation.

**Status:** Current implementation according to source KB, but small-sample behavior remains an open research problem.

## ADR-010 — InstrumentSpec

**Decision:** Convert quantity to monetary exposure through a dedicated instrument specification rather than dividing lots by money.

**Reason:** Unit correctness across position sizing and exposure calculations.

**Status:** Approved; implementation is incomplete according to the source KB.

## ADR-011 — Lightweight Charts v5

**Decision:** Use TradingView Lightweight Charts v5 for browser visualization.

**Reason:** Better candlestick capabilities than the rejected desktop/UI alternatives.

**Status:** Current frontend dependency; pin version and account for API changes.

## ADR-012 — No backward compatibility for hypothetical users in MVP

**Decision:** With zero users, correctness and clean APIs take priority over preserving obsolete fields.

**Status:** Current development philosophy.

## ADR-013 — Event chain orchestration is synchronous

**Historical issue:** A pure subscriber model caused a circular dependency where the portfolio manager did not receive fills.

**Resolution:** Execution is coordinated through a synchronous processing pipeline within the runner while still emitting events for observability.

**Lesson:** Event sourcing does not require every command processing step to be an asynchronous subscriber.
