"""Bundled agent-authoring assets (OBS-AI-04).

Everything here ships **inside the wheel**, so an agent working in a fresh
environment with no repository checkout and no network can still discover the
strategy contract, read a short guide, copy a gold example and validate its own
strategy.

Public surface (re-exported from :mod:`observa`)::

    observa.agent_spec()          -> dict    (deep copy, JSON-serialisable)
    observa.agent_spec_path()     -> str
    observa.agent_guide_path()    -> str
    observa.agent_example_path()  -> str
    observa.STRATEGY_API_VERSION  -> "1"

All access goes through :mod:`importlib.resources`, so it works for zipped and
ordinary installs alike. Nothing here imports a third-party dependency.
"""

from __future__ import annotations

from importlib import resources

from .contract import (  # noqa: F401  (re-exported for internal use)
    CONTRACT,
    FORBIDDEN_INSTALLS,
    REPOSITORY,
    STRATEGY_API_VERSION,
    build_spec,
    installation,
    release_tag,
    render_spec,
    wheel_filename,
    wheel_url,
)

_PACKAGE = "observa._agent"

GUIDE_FILENAME = "strategy-authoring.md"
EXAMPLE_FILENAME = "example_strategy.py"
SPEC_FILENAME = "spec.json"
SMOKE_BARS_FILENAME = "smoke_bars.csv"
AGENTS_TEMPLATE_FILENAME = "AGENTS.template.md"


def _asset(name: str) -> str:
    return str(resources.files(_PACKAGE) / name)


def _current_version() -> str:
    # Imported lazily: observa/__init__ imports this package, so a module-level
    # import would be circular. By call time the parent package is fully loaded.
    from .. import __version__

    return __version__


def agent_spec() -> dict:
    """The canonical machine-readable strategy contract.

    Returns a **fresh deep copy** every call, so callers cannot mutate the
    global contract. The result is deterministic and JSON-serialisable; see
    :func:`observa._agent.contract.render_spec`.
    """
    return build_spec(_current_version())


def agent_spec_path() -> str:
    """Absolute path to the bundled ``spec.json`` (the rendered contract)."""
    return _asset(SPEC_FILENAME)


def agent_guide_path() -> str:
    """Absolute path to the bundled short authoring guide."""
    return _asset(GUIDE_FILENAME)


def agent_example_path() -> str:
    """Absolute path to the bundled gold authoring example."""
    return _asset(EXAMPLE_FILENAME)


def agent_agents_template_path() -> str:
    """Absolute path to the bundled vendor-neutral ``AGENTS.md`` template."""
    return _asset(AGENTS_TEMPLATE_FILENAME)


def smoke_bars_path() -> str:
    """Absolute path to the bundled deterministic smoke fixture (6 bars)."""
    return _asset(SMOKE_BARS_FILENAME)


__all__ = [
    "CONTRACT",
    "STRATEGY_API_VERSION",
    "GUIDE_FILENAME",
    "EXAMPLE_FILENAME",
    "SPEC_FILENAME",
    "SMOKE_BARS_FILENAME",
    "AGENTS_TEMPLATE_FILENAME",
    "agent_spec",
    "agent_spec_path",
    "agent_guide_path",
    "agent_example_path",
    "agent_agents_template_path",
    "smoke_bars_path",
    "build_spec",
    "render_spec",
    "installation",
    "wheel_url",
    "wheel_filename",
    "release_tag",
    "FORBIDDEN_INSTALLS",
    "REPOSITORY",
]
