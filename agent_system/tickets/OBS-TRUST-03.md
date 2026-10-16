---
id: OBS-TRUST-03
title: O(1) per-bar strategy history (issue #6)
size: medium
status: DONE_PENDING_OWNER_REVIEW
financial: false
release: false
owner: leadership
---

# Objective
Per-bar overhead independent of how many bars came before, without changing
what strategies observe or any canonical output.

# Why it matters
Failure class FC-3 (finding P01, issue #6). The adapter rebuilt a fresh list
of fresh dicts for every prior bar on every bar: 1k bars 1.9 s, 8k bars 71.8 s
(released wheel), ~3 h extrapolated for 100k one-minute bars. Intraday
research was impractical.

# Scope
- `history` becomes a read-only, list-like view (`observa._observa.History`)
  over the strictly prior bars: `len`, int/negative indexing, slicing (returns
  a `list`), iteration, `reversed`, `in`, `index`, `count`, `==`/`+` with
  lists; registered as `collections.abc.Sequence`.
- Each access materialises a fresh dict (mutations never leak across bars).
- A view retained from bar *t* keeps length *t* forever (no future leakage).
- Mutators (`append`, item assignment, …) are not available.
- Docs/spec: history is a read-only sequence; `list(history)` gives a list.

# Non-goals
- No history window option (unnecessary once O(1)).

# Acceptance criteria
1. `python/tests/test_history_contract.py` passes: semantics, causality,
   isolation, golden digest identical to 0.1.6, 40k/10k runtime ratio < 7.
2. Issue #6 reproduction scales linearly; 100k-bar run completes in minutes.
3. All suites pass; canonical baseline unchanged.

# Compatibility
`isinstance(history, list)` becomes False; `history.append(...)` etc. raise
`AttributeError` (previously the mutation was silently discarded next bar).
Use `list(history)` for a mutable copy.

# Verification plan
Independent code review; benchmarks recorded in the audit; Finance/QA confirms
byte-identical economics on the golden scenario.
