"""Canonical agent-facing strategy authoring contract (OBS-AI-04).

This module is the **single source of truth** for the strategy authoring
contract. ``spec.json``, the bundled guide, the generated blocks in
``llms-full.txt`` and the validator's expectations are all derived from, or
checked against, ``CONTRACT`` here.

Authority for the contract's *content* is the shipped wheel binding
(``python/src/lib.rs``, module ``observa._observa``), never prose. If this
contract and the binding disagree, the binding wins and this file is wrong.

Design rules
------------
* Plain Python data only: no Rust type names, no serde attributes, no internal
  enum dumps.
* JSON-serialisable, deterministic, compact (target <= 6 KB serialised).
* Describes the **Python-facing** authoring surface only.

``STRATEGY_API_VERSION`` versions the authoring surface. It is deliberately
independent of the package version and of ``RUN_SCHEMA_VERSION`` /
``METRICS_SCHEMA_VERSION`` / ``EVENT_SCHEMA_VERSION``, which version persisted
artefacts instead.

Bump rules
----------
* Breaking (``"1"`` -> ``"2"``): removing or renaming a read signal key or
  lifecycle method; changing an accepted enum literal; changing a key a
  strategy reads from ``bar``/``portfolio``/``position``; making an optional
  field required; tightening the reason or drawing limits; changing direction
  casing.
* Additive (``"1"`` -> ``"1.1"``): a new optional signal key; a new drawing
  type; a new documented constant. Strategies written against ``"1"`` keep
  working.
* No bump: clarifications, examples, message wording, new ``details`` keys
  inside an existing error code.
"""

from __future__ import annotations

import copy
import json

STRATEGY_API_VERSION = "1"

# ────────────────────────────────────────────────
# Installation (centralised: never hard-code a version elsewhere)
# ────────────────────────────────────────────────

REPOSITORY = "ErickNgumo/observa"
RELEASE_TAG_TEMPLATE = "observa-{version}-private-mvp"
WHEEL_FILENAME_TEMPLATE = "observa-{version}-cp310-abi3-manylinux_2_34_x86_64.whl"
WHEEL_URL_TEMPLATE = (
    "https://github.com/ErickNgumo/observa/releases/download/"
    + RELEASE_TAG_TEMPLATE
    + "/"
    + WHEEL_FILENAME_TEMPLATE
)

FORBIDDEN_INSTALLS = [
    "pip install observa",
    'pip install "observa[mcp]"',
]


def wheel_filename(version: str) -> str:
    return WHEEL_FILENAME_TEMPLATE.format(version=version)


def wheel_url(version: str) -> str:
    return WHEEL_URL_TEMPLATE.format(version=version)


def release_tag(version: str) -> str:
    return RELEASE_TAG_TEMPLATE.format(version=version)


def installation(version: str) -> dict:
    """Builds the installation block for ``version`` (centralised generation).

    Commands reference ``<wheel_url>`` / ``<wheel_filename>`` from the same
    block rather than repeating the (long) URL five times.
    """
    return {
        "distribution": "github_release_wheel",
        "repository": REPOSITORY,
        "release_tag": release_tag(version),
        "wheel_filename": wheel_filename(version),
        "wheel_url": wheel_url(version),
        "base": 'python -m pip install "<wheel_url>"',
        "mcp_extra": 'python -m pip install "<wheel_url>[mcp]"',
        "local_wheel": 'python -m pip install "./<wheel_filename>"',
        "local_wheel_mcp": 'python -m pip install "./<wheel_filename>[mcp]"',
        "forbidden": list(FORBIDDEN_INSTALLS),
        "forbidden_reason": "The PyPI distribution named 'observa' is unrelated.",
        "verified_platforms": ["linux-x86_64 (glibc>=2.34)", "CPython>=3.10 (abi3)"],
        "unsupported": ["Windows", "macOS", "Google Colab"],
    }


# ────────────────────────────────────────────────
# The contract
# ────────────────────────────────────────────────

CONTRACT: dict = {
    "strategy_api_version": STRATEGY_API_VERSION,
    "lifecycle": {
        "required": ["initialize", "on_bar", "teardown"],
        "signatures": {
            "initialize": "initialize(self, params=None)",
            "on_bar": "on_bar(self, bar, portfolio, history)",
            "teardown": "teardown(self)",
        },
        "call_order": [
            "initialize(params) once before the first bar",
            "on_bar(bar, portfolio, history) once per closed bar",
            "teardown() once after the last bar",
        ],
        "base_class": "observa.Strategy",
        "base_class_optional": True,
        "notes": [
            "A plain class with the three methods works; subclassing is optional.",
            "TRAP: if you subclass observa.Strategy you must still override on_bar "
            "- the base class returns [] and a missing override silently produces a "
            "zero-trade run.",
            "initialize receives the resolved params dict ({} when none are set).",
            "Raising from any callback fails the run (code STRATEGY_ERROR).",
        ],
    },
    "on_bar": {
        "accepted_returns": [
            "[]  # no action",
            "[{...signal...}, ...]",
            "{'signals': [...], 'drawings': [...]}",
        ],
        "invalid_returns": [
            "TRAP: a bare signal dict {'direction': 'buy', 'size': 1.0} - the engine "
            "reads only the 'signals' key, so it is ignored. Wrap it in a list.",
            "TRAP: None - return [] for 'no action'; None is ambiguous.",
            "{'signal': [...]} - misspelled envelope key.",
            "str, tuple, number - anything not a list or dict.",
        ],
        "rule": "Always return a list, or a dict containing a 'signals' list.",
    },
    "bar": {
        "type": "dict (read-only)",
        "keys": {
            "timestamp": "str, RFC 3339",
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "float or None",
        },
        "note": "No bar_index and no symbol. Use bar['close'], not bar.close.",
    },
    "portfolio": {
        "type": "dict (read-only)",
        "keys": {
            "balance": "float, realised cash",
            "equity": "float, balance + unrealised P&L",
            "used_margin": "float",
            "free_margin": "float",
            "has_open_position": "bool",
            "unrealised_pnl": "float",
            "open_positions": "list of position dicts",
        },
    },
    "position": {
        "type": "dict (read-only), from portfolio['open_positions'][i]",
        "keys": {
            "position_id": "str, the exact ticket to close with",
            "ticket": "str, alias of position_id",
            "symbol": "str",
            "direction": "'Buy' or 'Sell' - OUTPUT is capitalised",
            "quantity": "float, alias of size",
            "size": "float, lots",
            "entry_price": "float",
            "unrealized_pnl": "float, alias of unrealised_pnl",
            "unrealised_pnl": "float",
            "stop_loss": "float or None - OUTPUT name",
            "take_profit": "float or None - OUTPUT name",
        },
        "note": "TRAP: signal INPUT uses lowercase 'buy' and keys size/sl/tp; position "
                "OUTPUT uses 'Buy' and stop_loss/take_profit. quantity is an output "
                "alias only - the input key is size.",
    },
    "history": {
        "type": "list of bar dicts",
        "contains": "strictly PRIOR bars only",
        "current_bar_included": False,
        "unbounded": True,
        "empty_at_first_bar": True,
        "note": "No lookahead is possible. Guard warm-up yourself: "
                "if len(history) < period: return []. It is all prior bars, not a "
                "fixed window, so slice history[-period:].",
    },
    "signals": {
        "type": "list of dicts returned from on_bar",
        "required": ["direction", "size"],
        "fields": {
            "direction": "'buy' | 'sell' | 'close' (lowercase, case-insensitive on input)",
            "size": "float, lots (INPUT quantity field - not 'quantity')",
            "order_type": "'market' (default) | 'limit' | 'stop'",
            "price": "float; limit/stop trigger price",
            "sl": "float, protective stop loss (entries)",
            "tp": "float, protective take profit (entries)",
            "reason": "str, persisted, max 1024 UTF-8 bytes",
            "ticket": "str, REQUIRED for close - use position['position_id']",
        },
        "unknown_fields": "TRAP: only those eight keys are read. Any other key "
                          "(stop_loss, take_profit, quantity, qty, sl_price) is "
                          "silently ignored, so a typo silently drops your stop loss. "
                          "validate-strategy reports SIGNAL_FIELD_UNKNOWN.",
    },
    "orders": {
        "order_types": ["market", "limit", "stop"],
        "default": "market",
        "trigger_price_field": "price",
        "note": "Rejections (bad size, bad SL/TP distance, insufficient margin) are "
                "canonical order_rejected EVENTS, not Python exceptions.",
    },
    "closing": {
        "requires_ticket": True,
        "fifo": False,
        "rule": "{'direction': 'close', 'size': pos['size'], 'ticket': pos['position_id']}",
        "note": "No FIFO, no 'close oldest', no implicit close. A close without a "
                "valid ticket is rejected as an event, not raised.",
    },
    "drawings": {
        "type": "optional list under the 'drawings' key of the on_bar dict return",
        "types": ["series", "hline", "line", "rectangle", "region", "marker",
                  "label", "bar_color"],
        "max_per_bar": 256,
        "id_rule": "1-64 chars from [A-Za-z0-9_.:-]",
        "time_rule": "any 'time' must be an already-seen bar timestamp (no future bars)",
        "errors": ["DRAWING_TYPE_INVALID", "DRAWING_FIELD_MISSING",
                   "DRAWING_VALUE_INVALID", "DRAWING_ID_INVALID",
                   "DRAWING_ACTION_INVALID", "DRAWING_REFERENCE_INVALID",
                   "DRAWING_PANE_INVALID", "DRAWING_TIME_INVALID",
                   "DRAWING_LIMIT_EXCEEDED"],
        "note": "Descriptive only - never affects orders, fills, P&L or chronology. "
                "Malformed drawings fail the run.",
    },
    "reason": {
        "max_bytes": 1024,
        "encoding": "UTF-8",
        "code": "STRATEGY_REASON_TOO_LONG",
        "persisted": True,
        "note": "Recorded on the canonical strategy_decision event; visible in replay "
                "and via inspect_run/MCP. Over-long reasons fail the whole run.",
    },
    "execution_rules": {
        "owner": "the canonical Rust Engine",
        "engine_owns": ["order creation, scheduling and triggering",
                        "fill timing and price (fill_mode)",
                        "spread and slippage",
                        "SL/TP evaluation and outcome",
                        "commission and margin",
                        "position identity and lifecycle",
                        "balance, equity, drawdown and all metrics"],
        "strategy_owns": ["intent only: direction, size, protective levels, reason"],
    },
    "error_codes": {
        "authoring": ["STRATEGY_CLASS_NOT_FOUND", "STRATEGY_METHOD_MISSING",
                      "STRATEGY_METHOD_SIGNATURE", "STRATEGY_RETURN_INVALID",
                      "SIGNAL_FIELD_UNKNOWN", "SIGNAL_FIELD_MISSING",
                      "SIGNAL_DIRECTION_INVALID", "SIGNAL_ORDER_TYPE_INVALID",
                      "SIGNAL_FIELD_TYPE_INVALID", "CLOSE_TICKET_REQUIRED",
                      "SIGNAL_TICKET_UNKNOWN", "STRATEGY_REASON_TOO_LONG",
                      "STRATEGY_SYNTAX_ERROR", "STRATEGY_NOT_IMPORTABLE",
                      "STRATEGY_SMOKE_RUN_FAILED"],
        "setup": ["STRATEGY_FILE_NOT_FOUND"],
        "warning_only": ["STRATEGY_CLASS_AMBIGUOUS", "SIGNAL_TICKET_UNKNOWN",
                         "SIGNAL_FIELD_UNKNOWN"],
        "drawing": "see drawings.errors",
        "runtime": "engine/config/data/run codes are raised by observa.run itself; "
                   "read them from exc.code (see docs/STRATEGY_API.md)",
    },
    "forbidden_patterns": [
        "Your own fill model, matching engine or backtest loop.",
        "Applying spread, slippage or commission yourself.",
        "Computing balance, equity, P&L, drawdown or any metric yourself.",
        "Recreating order execution, queueing or SL/TP evaluation.",
        "Reading future bars or indexing beyond the current bar.",
        "Assuming FIFO or 'close the oldest'.",
        "Returning a bare signal dict or None from on_bar.",
        "Using quantity/stop_loss/take_profit as SIGNAL input keys.",
        "Running 'pip install observa' or 'pip install \"observa[mcp]\"'.",
    ],
    "validation": {
        "cli": "observa validate-strategy FILE [--class NAME] [--json] [--smoke]",
        "python": "observa.validate_strategy(path_or_class, class_name=None, smoke=False)",
        "exit_codes": {"0": "valid", "1": "invalid strategy", "2": "usage/setup error"},
        "tiers": {
            "A": "structural: parses, lifecycle methods visible in the AST; never executes user code",
            "B": "imported: class resolves, signatures compatible, on_bar genuinely overridden; never calls on_bar",
            "C": "smoke: real Engine over 6 bundled bars, validating the RAW on_bar return; shape/integration only",
        },
        # TRUST BOUNDARY (additive metadata; not a strategy-API change).
        # Validation is NOT a sandbox: tiers B and C run the author's code.
        "security": {
            "sandboxed": False,
            "trusted_code_only": True,
            "tier_a": "parses source only; does not import or execute the strategy",
            "tier_b": "IMPORTS the strategy module - top-level Python code may execute",
            "tier_c": "EXECUTES on_bar() through the real Observa Engine",
            "warning": "validate-strategy is not a sandbox. Tier B imports the strategy "
                       "module, which may execute top-level Python code. Tier C "
                       "additionally executes the strategy's on_bar() through the real "
                       "Observa Engine. Only validate strategy code you trust.",
        },
        "does_not_prove": [
            "strategy logic or profitability",
            "margin, SL/TP distance, or quantity validity (engine order_rejected events)",
            "that any signal will ever be produced - zero signals in six bars is valid",
        ],
    },
    "examples": {
        "gold": "example_strategy.py (bundled beside this contract)",
        "guide": "strategy-authoring.md (bundled beside this contract)",
        "note": "Imitate the gold example: entry with sl and reason, exact-ticket "
                "close, one annotation, output= persistence.",
    },
}


def build_spec(observa_version: str) -> dict:
    """Returns a fresh, JSON-serialisable spec dict for ``observa_version``.

    A deep copy is returned every time, so callers can never mutate module
    state. The returned mapping is deterministic: rendering it with
    ``json.dumps(spec, indent=2, sort_keys=True)`` reproduces the bundled
    ``spec.json`` byte for byte.
    """
    spec = copy.deepcopy(CONTRACT)
    spec["observa_version"] = observa_version
    spec["installation"] = installation(observa_version)
    return spec


def render_spec(observa_version: str) -> str:
    """Deterministic text rendering of the spec (the only supported renderer)."""
    return json.dumps(build_spec(observa_version), indent=2, sort_keys=True) + "\n"
