# Migration Review Notes

This file records the distinctions made while reorganizing the original knowledge base.

## Preserved as current/core

- Event sourcing as the product architecture.
- Rust engine + Python strategies.
- Observability as the central value proposition.
- Determinism.
- No-future-data access through controlled history.
- Realistic execution assumptions.
- Event-derived visualization and metrics.

## Preserved as known current issues

- InstrumentSpec wiring incomplete.
- Deprecated exposure fields remain.
- Sharpe small-sample concern.
- Python on_fill not wired.
- Indicator registration not implemented.
- Visualization polish gaps.
- History-growth scalability issue.
- Large event-log/browser payload scalability issue.
- Documentation drift risk.

## Moved to historical context

- Detailed timeline of previous development phases.
- Individual bug stories.
- Rejected alternatives and why they were rejected.
- Business/marketing discussion.
- Competitive analysis.

These should not be included wholesale in every agent's context.

## Deliberately marked as proposals/open decisions

- Pip packaging as an MVP requirement.
- Exact release platform support matrix.
- Final Sharpe small-sample policy.
- Exact treatment of data gaps.
- Config version migration strategy.
- Future history-window strategy.
- Whether and when WASM should matter.

## Source fact vs approval

The original KB says pip packaging was v1.0. The current engineering direction is to consider it MVP because end-user friction is itself a product problem. This reorganization records that as a proposed change rather than rewriting history.
