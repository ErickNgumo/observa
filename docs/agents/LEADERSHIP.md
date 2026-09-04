# Engineering Leadership

## Role

Engineering Leadership is the product and technical decision layer above the agents.

Leadership is currently Erick + senior engineering review with ChatGPT acting as the senior engineering counterpart in the development process.

## Responsibilities

- Define and lock MVP scope.
- Prioritize backlog and create/approve engineering tickets.
- Approve fundamental architecture changes.
- Decide when an old architectural decision should be replaced.
- Resolve disagreements between agents.
- Review significant implementation results.
- Decide whether work is accepted, returned, deferred, or rejected.

## Leadership does not delegate

The following decisions must not be made unilaterally by implementation agents:

- Adding or removing MVP capabilities.
- Changing the north-star product concept.
- Replacing event sourcing or another fundamental architecture invariant.
- Changing the strategy contract in a breaking way without review.
- Changing financial/execution semantics without appropriate Finance and Architecture review.
- Adding a major external dependency or platform requirement.

## Decision rule

Agents may recommend. Leadership decides.

## Review questions

For significant work, Leadership asks:

1. Does this solve a real MVP/product problem?
2. Is the proposed complexity justified?
3. Does it preserve Observa's trust/observability goal?
4. Does it introduce new assumptions or hidden technical debt?
5. Can the behavior be tested deterministically?
6. Does the implementation remain consistent with the documentation hierarchy?
