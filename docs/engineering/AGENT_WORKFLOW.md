# Observa Agent Operating Protocol

Version: 1.0
Status: Proposed
Owner: Engineering Leadership

## 1. Purpose

This document defines how work moves through the Observa agent team from idea to accepted change.
It is the operating protocol for agent-assisted development. Product and technical truth live in the project documentation; this document defines how agents use that truth to execute work.

## 2. Authority

Agents are specialists, not autonomous product owners.

Engineering Leadership (Erick + senior engineering review) owns:
- product direction;
- MVP scope and priorities;
- fundamental architectural decisions;
- resolution of agent disagreements;
- final acceptance of significant work.

Agents may challenge decisions with evidence, but they must escalate rather than silently override them.

Authority for project truth follows `docs/README.md`.

## 3. Core operating loop

Every meaningful task follows this loop:

```text
REQUEST
  ↓
TRIAGE
  ↓
SPECIFY (if needed)
  ↓
APPROVE
  ↓
IMPLEMENT
  ↓
VERIFY
  ↓
REVIEW
  ↓
ACCEPT / CHANGES / DEFER
  ↓
DOCUMENT
```

No agent may skip a required gate merely because the implementation appears obvious.

## 4. Before an agent starts

The agent must:

1. Read the task ticket.
2. Identify the task size and routing path.
3. Read only the relevant project documents, starting with `README.md` and then the documents named by the ticket.
4. Inspect the current source implementation before proposing edits.
5. Check `CURRENT_STATE.md` for known partial implementations and issues.
6. Identify conflicts between requirements, documentation, and code.

The agent must not assume that a historical decision in `DECISIONS.md` is still active without checking its status.

## 5. Task lifecycle

### PROPOSED

A task exists as an idea or observed problem. No implementation begins.

Required:
- objective;
- reason it matters;
- initial scope;
- owner/next agent.

### SPECIFIED

Requirements and acceptance criteria are sufficiently precise for implementation.

Required for medium/large work:
- problem;
- scope;
- non-goals;
- expected behavior;
- affected components;
- acceptance criteria;
- test/verification strategy;
- relevant documentation.

### APPROVED

Leadership has approved the scope/design to proceed.

For architectural or significant work, Architecture must also approve the technical design before implementation.

### IN_PROGRESS

Developer or another assigned specialist is actively working.

The agent may refine implementation details within the approved scope, but cannot expand requirements unilaterally.

### READY_FOR_REVIEW

Implementation is complete enough for technical review.

Required:
- files changed;
- implementation summary;
- tests run;
- test results;
- known issues;
- documentation changes;
- deviations from the approved design.

### CHANGES_REQUESTED

Reviewer found issues. The task returns to the responsible agent with explicit required changes.

### READY_FOR_QA

Architecture/code review has found the implementation technically acceptable enough for verification.

### PASS

QA and any required Finance verification have passed.

### ACCEPTED

Leadership accepts the completed work.

### DEFERRED

Work is intentionally moved out of the current priority/scope.

### BLOCKED

Progress cannot continue without an external decision, missing information, dependency, or environment capability.

## 6. Task routing

### Small

Examples:
- isolated bug fix;
- error-message correction;
- documentation update;
- isolated test improvement.

```text
Leadership → Developer → QA → Leadership
```

Architecture is consulted if an architectural boundary is affected.
Finance is inserted if financial behavior is affected.

### Medium

Examples:
- subsystem feature;
- cross-module bug fix;
- API-preserving refactor;
- non-trivial UI behavior.

```text
Leadership → Architecture → Developer → QA → Leadership
```

Add Finance for financial/quantitative behavior.

### Large / fundamental

Examples:
- new public API;
- event model changes;
- execution semantics changes;
- new subsystem;
- packaging architecture;
- fundamental refactor.

```text
Leadership
  ↓
Research (when uncertainty exists)
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

## 7. Document selection protocol

Agents should not ingest the entire project documentation by default.

### Every agent reads
- `docs/README.md`
- the task ticket
- `docs/CURRENT_STATE.md`

### Then select by task

Product/scope → `docs/PROJECT.md`, `docs/MVP.md`

Architecture → `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`

Strategy/API → `docs/STRATEGY_API.md`, `docs/DOMAIN_MODEL.md`

Execution → `docs/domain/EXECUTION.md`, `docs/domain/PORTFOLIO.md`

Metrics → `docs/domain/METRICS.md`

Data → `docs/domain/DATA.md`

Visualization → `docs/domain/VISUALIZATION.md`

Testing → `docs/engineering/TESTING.md`

Packaging → `docs/engineering/PACKAGING.md`

Development conventions → `docs/engineering/DEVELOPMENT.md`

Historical reasoning → `docs/DECISIONS.md`

Agents only read additional documents when the task requires them.

## 8. Source inspection protocol

Before editing, the responsible agent must identify:

- current implementation location;
- relevant interfaces/contracts;
- dependent code;
- existing tests;
- existing documentation;
- known related bugs or limitations.

For financial behavior, Finance must independently derive expected outputs instead of merely checking whether Developer tests pass.

For architecture-sensitive work, Architecture must inspect the dependency and event flow before approval.

## 9. Implementation protocol

Developer should:

1. Restate the acceptance criteria internally.
2. Make the smallest coherent change that satisfies them.
3. Preserve existing invariants.
4. Add or update tests in the same change.
5. Avoid opportunistic refactors outside the task.
6. Run relevant formatters, linters, builds, and tests.
7. Report failures honestly.

A green build does not override a failed requirement.

## 10. Verification protocol

Verification must match risk.

### Minimum
- targeted unit tests;
- regression tests for bug fixes.

### Medium/high risk
- integration tests;
- known-answer tests where numerical correctness matters;
- event-sequence verification where traceability matters.

### MVP/user-facing
- end-to-end workflow verification.

The verifier must report what was actually executed, not what was assumed to work.

## 11. Review protocol

Architecture review asks:

- Is the implementation consistent with approved architecture?
- Are boundaries preserved?
- Is event traceability preserved?
- Is behavior deterministic?
- Is future data still structurally inaccessible?
- Is the solution unnecessarily complex?
- Are contracts explicit?

Finance review asks when applicable:

- Are formulas correct?
- Do units and currencies make sense?
- Are execution assumptions correct?
- Does the implementation match independently derived expected outputs?

QA asks:

- Does the requirement work?
- What failure modes were exercised?
- Does the regression suite catch the original bug?
- Does the end-to-end flow work where required?

## 12. Handoff protocol

Every handoff uses `docs/agents/HANDOFF_PROTOCOL.md`.

A handoff must identify:
- task ID;
- sender and recipient;
- current status;
- objective;
- scope;
- files changed;
- relevant references;
- verification performed;
- known issues;
- exact requested next action.

Silence is never approval.

## 13. Escalation rules

Stop and escalate when:

- the approved scope appears wrong;
- a requirement conflicts with another requirement;
- source behavior contradicts intended behavior;
- a public contract must change unexpectedly;
- a core invariant must be changed;
- financial correctness is uncertain;
- a test cannot establish correctness;
- an agent lacks required information or tooling;
- a change would require an unapproved dependency or platform assumption.

The agent should present:
1. what was discovered;
2. why it matters;
3. options;
4. recommendation;
5. decision needed.

## 14. Documentation synchronization

Documentation changes are part of the change when behavior, contracts, architecture, scope, or current state changes.

At minimum:

- API change → update the API document;
- architecture change → update `ARCHITECTURE.md` and `DECISIONS.md`;
- MVP scope change → update `MVP.md` and decision record;
- implementation status change → update `CURRENT_STATE.md`;
- test-process change → update `engineering/TESTING.md`;
- packaging change → update `engineering/PACKAGING.md`.

## 15. Definition of Done

A task is complete only when the applicable conditions in `docs/agents/DEFINITION_OF_DONE.md` are satisfied.

## 16. No false completion

Agents must never claim:
- a feature is implemented when only a design exists;
- a test passed when it was not run;
- packaging works without a clean-environment install test when that is a release requirement;
- financial correctness based solely on matching the same implementation's expected value;
- documentation is current without checking the relevant source contract.

When uncertain, report uncertainty explicitly.
