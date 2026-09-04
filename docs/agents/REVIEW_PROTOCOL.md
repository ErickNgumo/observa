# Review Protocol

## Purpose

Define the gates used to decide whether work is safe to merge and acceptable as Observa work.

## Review sequence

```text
Developer
   ↓
Self-check
   ↓
Architecture review (when applicable)
   ↓
Finance review (when applicable)
   ↓
QA & Integration
   ↓
Leadership acceptance
```

## Developer self-check

Before requesting review, confirm:

- acceptance criteria are addressed;
- only intended files/areas changed;
- tests were added/updated;
- relevant commands were actually run;
- failures are reported;
- documentation changes are included;
- no out-of-scope cleanup was mixed in.

## Architecture acceptance levels

### LOCAL
No architectural boundary, public contract, event schema, or core invariant changes.

Architecture review may be lightweight or omitted according to routing.

### SIGNIFICANT
Cross-component behavior, public interfaces, performance-sensitive paths, or non-trivial refactors.

Architecture review is required.

### FUNDAMENTAL
Changes to:
- core event model;
- event-sourcing semantics;
- strategy contract;
- execution semantics;
- major subsystem boundaries;
- other fundamental invariants.

Architecture recommendation + Leadership approval are mandatory before implementation.

## Finance gate

Finance is mandatory whenever results can change because of:
- PnL;
- spread;
- slippage;
- commission;
- position sizing;
- exposure/risk/margin;
- SL/TP behavior;
- performance statistics;
- instrument calculations.

Finance must independently derive at least one expected result for important changes.

## QA gate

QA must verify the implementation against the ticket, not merely inspect the code.

For MVP-critical work, QA should verify the user-facing path where practical.

## Leadership acceptance

Leadership accepts significant work only after required technical gates have passed.

Leadership can return work even when QA is green if:
- the product requirement is not met;
- scope drift occurred;
- complexity is unjustified;
- documentation is incomplete;
- the result does not support Observa's core objective.

## Review outcomes

`ACCEPTED` — ready to merge/use.

`CHANGES_REQUESTED` — specific corrections required.

`BLOCKED` — decision or dependency missing.

`DEFERRED` — valid work intentionally postponed.

`REJECTED` — work should not proceed in its current form.
