"""Deterministic markdown generation from the canonical contract (OBS-AI-04).

Contract-heavy documentation is **generated** from ``CONTRACT`` between sentinel
markers, so it cannot drift from the machine-readable spec. Narrative sections
(execution model, MCP, examples, agent rules) stay hand-authored.

    python -m observa._agent._render --llms-full <path>          # splice
    python -m observa._agent._render --llms-full <path> --check  # drift check
"""

from __future__ import annotations

from .contract import build_spec

BEGIN = "<!-- BEGIN GENERATED: %s -->"
END = "<!-- END GENERATED: %s -->"

#: Generated regions, in document order.
BLOCK_NAMES = ("strategy-contract",)


def _table(rows, headers=("Key", "Meaning")):
    out = ["| %s | %s |" % headers, "| --- | --- |"]
    for key, meaning in rows:
        out.append("| `%s` | %s |" % (key, meaning))
    return "\n".join(out)


def _bullets(items):
    return "\n".join("* %s" % i for i in items)


def render_strategy_contract(version: str) -> str:
    spec = build_spec(version)
    lc = spec["lifecycle"]
    ob = spec["on_bar"]
    sig = spec["signals"]
    pos = spec["position"]
    hist = spec["history"]
    dr = spec["drawings"]
    reason = spec["reason"]
    orders = spec["orders"]
    closing = spec["closing"]

    parts = []
    parts.append("**strategy_api_version `%s`** (observa %s). This block is generated "
                 "from `observa.agent_spec()`; edit the contract, not this text."
                 % (spec["strategy_api_version"], spec["observa_version"]))
    parts.append("")
    parts.append("A strategy is a plain Python class (subclassing `observa.Strategy` is optional):")
    parts.append("")
    parts.append("```python")
    parts.append("class MyStrategy:")
    for method in lc["required"]:
        parts.append("    def %s: ..." % lc["signatures"][method])
    parts.append("```")
    parts.append("")
    parts.append("Lifecycle order: " + "; ".join(lc["call_order"]) + ".")
    parts.append("")
    parts.append(_bullets(lc["notes"]))
    parts.append("")
    parts.append("`on_bar` must return:")
    parts.append("")
    parts.append(_bullets("`%s`" % r for r in ob["accepted_returns"]))
    parts.append("")
    parts.append("Never return:")
    parts.append("")
    parts.append(_bullets(ob["invalid_returns"]))
    parts.append("")
    parts.append("### Fields (exact)")
    parts.append("")
    parts.append("`bar` — " + spec["bar"]["type"] + ":")
    parts.append("")
    parts.append(_table(sorted(spec["bar"]["keys"].items())))
    parts.append("")
    parts.append(spec["bar"]["note"])
    parts.append("")
    parts.append("`portfolio` — " + spec["portfolio"]["type"] + ":")
    parts.append("")
    parts.append(_table(sorted(spec["portfolio"]["keys"].items())))
    parts.append("")
    parts.append("each `position` — " + pos["type"] + ":")
    parts.append("")
    parts.append(_table(sorted(pos["keys"].items())))
    parts.append("")
    parts.append(pos["note"])
    parts.append("")
    parts.append("`history` — %s. %s" % (hist["contains"], hist["note"]))
    parts.append("")
    parts.append("### Signal fields")
    parts.append("")
    parts.append("Required: " + ", ".join("`%s`" % r for r in sig["required"]) + ".")
    parts.append("")
    parts.append(_table(sorted(sig["fields"].items())))
    parts.append("")
    parts.append(sig["unknown_fields"])
    parts.append("")
    parts.append("Order types: %s (default `%s`); limit/stop trigger price goes in "
                 "`%s`." % (", ".join("`%s`" % o for o in orders["order_types"]),
                            orders["default"], orders["trigger_price_field"]))
    parts.append("")
    parts.append(orders["note"])
    parts.append("")
    parts.append("Closing: `%s` — requires a ticket: %s; FIFO: %s. %s"
                 % (closing["rule"], closing["requires_ticket"], closing["fifo"],
                    closing["note"]))
    parts.append("")
    parts.append("`reason`: max %d %s bytes, code `%s`, persisted: %s. %s"
                 % (reason["max_bytes"], reason["encoding"], reason["code"],
                    reason["persisted"], reason["note"]))
    parts.append("")
    parts.append("### Annotations (drawings)")
    parts.append("")
    parts.append("Types: " + ", ".join("`%s`" % t for t in dr["types"])
                 + ". Maximum **%d per bar**. `id`: %s. `time`: %s."
                 % (dr["max_per_bar"], dr["id_rule"], dr["time_rule"]))
    parts.append("")
    parts.append(dr["note"])
    parts.append("")
    parts.append("### Execution authority")
    parts.append("")
    parts.append("The Engine owns:")
    parts.append("")
    parts.append(_bullets("`%s`" % x for x in spec["execution_rules"]["engine_owns"]))
    parts.append("")
    parts.append("The strategy owns: "
                 + ", ".join(spec["execution_rules"]["strategy_owns"]) + ".")
    return "\n".join(parts).rstrip() + "\n"


_RENDERERS = {
    "strategy-contract": render_strategy_contract,
}


def render_block(name: str, version: str) -> str:
    """Renders one sentinel region (without the sentinel lines)."""
    try:
        renderer = _RENDERERS[name]
    except KeyError:
        raise KeyError("unknown generated block %r (known: %s)"
                       % (name, ", ".join(BLOCK_NAMES))) from None
    return renderer(version)


def render_all(version: str) -> dict:
    return {name: render_block(name, version) for name in BLOCK_NAMES}


def splice(text: str, version: str, names=None) -> str:
    """Replaces the content of each sentinel region in ``text``."""
    for name in (names or BLOCK_NAMES):
        begin, end = BEGIN % name, END % name
        if begin not in text or end not in text:
            raise KeyError("missing sentinel pair for %r" % name)
        head, rest = text.split(begin, 1)
        _body, tail = rest.split(end, 1)
        text = head + begin + "\n" + render_block(name, version) + end + tail
    return text


def find_block(text: str, name: str) -> str:
    """Extracts the current content of a sentinel region."""
    begin, end = BEGIN % name, END % name
    if begin not in text or end not in text:
        raise KeyError("missing sentinel pair for %r" % name)
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return body[1:] if body.startswith("\n") else body
