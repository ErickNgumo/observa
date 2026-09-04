# Agent Handoff Protocol

Agents may communicate through files, an orchestrator, or separate model sessions. The transport mechanism is implementation detail; the information in the handoff is mandatory.

## Every handoff must contain

- Task ID
- Sender
- Recipient
- Task type
- Objective
- Context
- Files/components affected
- Documentation references
- Acceptance criteria
- Work performed
- Verification performed
- Known issues
- Requested action

## Status vocabulary

PROPOSED
SPECIFIED
APPROVED
IN_PROGRESS
READY_FOR_REVIEW
CHANGES_REQUESTED
READY_FOR_QA
PASS
FAIL
ACCEPTED
DEFERRED
BLOCKED

## No implicit approval

Silence is not approval. An agent must receive an explicit ACCEPTED/APPROVED state before crossing a gated boundary.

## Proposed JSON representation

```json
{
  "task_id": "OBS-MVP-001",
  "from": "Developer",
  "to": "QA",
  "type": "Code",
  "status": "READY_FOR_QA",
  "objective": "...",
  "files_changed": [],
  "acceptance_criteria": [],
  "verification": [],
  "known_issues": [],
  "references": []
}
```

The JSON is a logical contract, not yet a requirement that all orchestration be implemented using JSON.
