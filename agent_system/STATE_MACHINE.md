# Ticket State Machine

```text
PROPOSED
   │
   ├── small ───────────────────────────────┐
   │                                        ▼
   └── medium/large → SPECIFIED → APPROVED
                                      │
                                      ▼
                                 IN_PROGRESS
                                      │
                                      ▼
                              READY_FOR_REVIEW
                               │            │
                         changes needed    pass
                               │            ▼
                               └────── CHANGES_REQUESTED
                                            │
                                            ▼
                                     READY_FOR_QA
                                       │        │
                                      fail     pass
                                       │        ▼
                                       │     ACCEPTED
                                       ▼
                                   CHANGES_REQUESTED
```

`BLOCKED` may be entered whenever required information, environment access, or an unresolved leadership decision prevents progress.

`DEFERRED` is a leadership decision and is never assigned by an implementation agent merely because a task is difficult.
