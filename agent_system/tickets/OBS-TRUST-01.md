---
id: OBS-TRUST-01
title: Reject silently-dropped strategy and config intent at the Python boundary
size: medium
status: DONE_PENDING_OWNER_REVIEW
financial: false
release: false
owner: leadership
---

# Objective
Make every way a strategy or config can lose intent at the Python→Engine
boundary fail loudly, with a stable machine-readable code and a fix hint.

# Why it matters
Failure class FC-1 of the 2026-10 trust audit (`docs/audit/2026-10-trust-audit.md`,
findings S01–S05, C01, C02). A signal written with `stop_loss` instead of `sl`
opened a position **without a stop** and the run completed normally. A bare
signal dict, a forgotten `return` (`None`) or a misspelled envelope key
produced a "successful" zero-trade run. A typo in a config dict (`spred`)
silently applied the default cost model. The project documented these as
"traps" instead of removing them.

# Scope
- Signal dicts: any key outside the eight canonical keys fails the run with
  `SIGNAL_FIELD_UNKNOWN` (details: `field`, `suggestion`, `allowed`,
  `bar_index`, `signal_index`).
- `on_bar` return: `None`, a bare signal dict, a dict with keys other than
  `signals`/`drawings`, `signals` that is not a list, and any non-list/dict
  value fail with `STRATEGY_RETURN_INVALID` (details: `bar_index`, `received`).
- Config dicts: unknown top-level and `order_model` keys fail with
  `CONFIG_INVALID` (details: `field`, `suggestion`, `allowed`).
- `observa.Config` gains `tick_size` and `pip_size` (issue #5).
- (Considered and reverted after Finance/QA review F4: recording
  `strategy_name` as the run's strategy name changes the strategy identity
  hash `params_sha256`. Deferred to a run-schema change.)
- Validator, `agent_spec()`, guides, AGENTS template and llms-full.txt updated
  to say these are errors (no longer "traps").

# Non-goals
- No change to execution, fills, P&L or event schema.
- No new signal fields.

# Acceptance criteria
1. `python/tests/test_trust_boundary.py` FC-1 checks pass (they fail on 0.1.6).
2. Property test: any non-canonical signal key fails loudly; canonical keys never do.
3. All existing Python suites and Rust tests still pass; canonical baseline unchanged.
4. Docs/spec/template consistent; template mirrored, not edited in three places.

# Compatibility
Strategies that relied on the lenient behaviour now fail at the first offending
bar with an explicit code and hint. Migration: rename the key (`stop_loss`→`sl`,
`take_profit`→`tp`, `quantity`/`qty`→`size`), return `[]` for no action, and
wrap bare signals in a list.

# Verification plan
- Implementation: coding agent. Independent code review: separate review agent.
- No economic change is intended; the canonical baseline and golden digests
  must be byte-identical (Finance/QA confirms no economic change).

# Agent reports
_See `docs/audit/2026-10-trust-audit.md` §7._
