# Task Routing

## Small task

Examples: local bug fix, error-message improvement, documentation correction, isolated test.

```text
Leadership → Developer → QA → Leadership
```

Architecture is consulted only when the change affects an architectural boundary.

## Medium task

Examples: isolated feature, cross-module bug fix, non-breaking subsystem change with known design.

```text
Leadership → Architecture → Developer → QA → Leadership
```

Finance is inserted when financial behavior is affected.

## Large / new capability

Examples: public API changes, new event types, new execution semantics, new packaging architecture, major subsystem redesign.

```text
Leadership
  ↓
Research (when uncertainty/evidence is needed)
  ↓
Architecture
  ↓
Leadership approval
  ↓
Developer
  ↓
Finance / QA & Integration
  ↓
Architecture review
  ↓
Leadership acceptance
  ↓
Release (when applicable)
```

## Escalation triggers

Any agent must escalate rather than improvise when:

- scope must change;
- a fundamental invariant is challenged;
- requirements are contradictory;
- a public contract must change unexpectedly;
- financial correctness is uncertain;
- tests cannot establish correctness;
- documentation and code disagree about intended behavior.
