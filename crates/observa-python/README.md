# observa-python — LEGACY / DEV-ONLY Python bridge

> **This crate is NOT the strategy contract of the released Python wheel.**

## Status

`crates/observa-python` is a **legacy/dev-only** PyO3 bridge. It is a workspace
member (so `cargo test --workspace` exercises it) and it is used by exactly one
consumer: the Rust `observa-cli` binary, via `observa run --strategy <file.py>`.

It is **not** part of the released product:

* the released wheel is built by the separate maturin project at `python/`
  (`python/Cargo.toml`, module `observa._observa`), which does **not** depend on
  this crate;
* the Rust `observa-cli` binary is not uploaded to the GitHub Release assets;
* the installed `observa` console script has no `run` subcommand.

## Why it matters

Its dict shapes **diverge** from the shipped binding. Portfolio and position
dicts built by `crates/observa-python/src/portfolio.rs` are smaller than those
built by `python/src/lib.rs::portfolio_to_py_dict`:

| | legacy (this crate) | shipped wheel |
| --- | --- | --- |
| portfolio | `balance`, `equity`, `has_open_position`, `unrealised_pnl`, `open_positions` | + `used_margin`, `free_margin` |
| position | `ticket`, `direction`, `size`, `entry_price`, `unrealised_pnl`, `sl`, `tp` | + `position_id`, `symbol`, `quantity`, `unrealized_pnl`, `stop_loss`, `take_profit` |

A strategy written against the shipped contract (`pos["position_id"]`) raises
`KeyError` under this bridge, and one written against this bridge silently
loses the canonical aliases under the wheel. That is exactly the ambiguity
OBS-AI-04 removed from the documentation.

## Policy (OBS-AI-04)

* **The released wheel contract is the single public authority**
  (`python/src/lib.rs`, surfaced at runtime by `observa.agent_spec()`).
* This crate is **not** redesigned, not ported onto the execution path, and not
  deleted in OBS-AI-04. A later ticket may reconcile or remove it.
* Divergence is now **explicit and guarded**: the key-set difference above is
  recorded as a constant, and `python/tests/test_agent_contract.py`
  (`test_legacy_bridge_divergence_is_explicit`) fails if this crate's dict shape
  changes, forcing a deliberate decision rather than a silent drift.
