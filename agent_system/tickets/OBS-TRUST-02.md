---
id: OBS-TRUST-02
title: Validate and canonicalise market data at ingestion (incl. issue #8)
size: medium
status: DONE_PENDING_OWNER_REVIEW
financial: true
release: false
owner: leadership
---

# Objective
Market data that is invalid or ambiguous is rejected at load time with the
offending row; valid data is presented to strategies in one documented,
canonical form.

# Why it matters
Failure class FC-2 of the 2026-10 trust audit (findings D01–D06). NaN/inf
prices passed validation on both input paths; the Python list/DataFrame path
skipped OHLC validation entirely (high < low, negative prices accepted);
epoch milliseconds were read as seconds (year 56971); timezone-less strings
were silently assumed UTC on one path and rejected on the other; the
strategy-facing timestamp format was undocumented and differed from the input,
so string joins silently matched nothing (issue #8).

# Scope
- `Bar::validate` rejects non-finite OHLC and non-finite volume (both paths).
- Python list/DataFrame path runs `Bar::validate`; errors carry `row` and
  the violation list (`DATA_INVALID`).
- Timestamp inputs: RFC 3339 strings with offset or `Z`; `YYYY-MM-DD HH:MM:SS+00:00`;
  timezone-aware `datetime` objects; epoch **seconds** (int/float, sub-second
  kept). Rejected with a hint: timezone-less strings or datetimes, booleans,
  numbers that are implausible as epoch seconds (> 1e11 ⇒ "looks like
  milliseconds").
- Strategy-facing bar dict: `timestamp` keeps its current canonical format
  `YYYY-MM-DDTHH:MM:SS[.f…]+00:00` (now documented and test-pinned) and gains
  `timestamp_ms` (int epoch milliseconds) for unambiguous joins.
- Docs, spec and guide state the format and recommend joining on
  `timestamp_ms` or parsed datetimes.

# Non-goals
- Extra bar fields (issue #1) — still ignored; needs the feature-store design.
- No change to fills/P&L for valid data.

# Acceptance criteria
1. `test_trust_boundary.py` FC-2 checks pass (fail on 0.1.6), including the
   property test (a bad price anywhere is rejected at its row).
2. Issue #8 reproduction: input `...Z` → `bar["timestamp"]` is the documented
   `+00:00` form, and `bar["timestamp_ms"]` matches; test pins both.
3. Canonical baseline, golden digests and all suites unchanged for valid data.

# Compatibility
Previously-accepted invalid data now fails loudly. Timezone-less timestamps on
the list path now fail (as they already did on the CSV path): append `Z` or
`+00:00`. Epoch milliseconds must be divided by 1000.

# Verification plan
Independent code review; Finance/QA confirms no economic change for valid data
(data validation affects which runs are allowed, not how they are computed).
