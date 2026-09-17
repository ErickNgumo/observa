"""observa — deterministic event-driven backtesting (Python API).

The public surface is intentionally small::

    import observa

    class MyStrategy(observa.Strategy):
        def initialize(self, params=None):
            self.n = int(params.get("n", 5)) if params else 5

        def on_bar(self, bar, portfolio, history):
            if not portfolio["has_open_position"]:
                return [{"direction": "buy", "size": 1.0}]
            return []

    result = observa.run(MyStrategy(), "EURUSD_M15.csv", config=observa.Config())
    print(result.final_equity)
    result.save("runs/test-01")

Everything is executed by the canonical Rust Engine; Python only supplies the
strategy callbacks and reads the resulting (read-only) views.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Sequence, Union

from ._observa import RunResult, run as _run
from .errors import coded, error_code
from .replay import ReplayServer

__version__ = "0.1.1"

# ────────────────────────────────────────────────
# Public enums (string constants — deterministic and strict)
# ────────────────────────────────────────────────

MARKET = "market"
LIMIT = "limit"
STOP = "stop"

BUY = "buy"
SELL = "sell"
CLOSE = "close"

BAR_CLOSE = "bar_close"
NEXT_BAR_OPEN = "next_bar_open"

PER_SIDE = "per_side"
ROUND_TRIP = "round_trip"


# ────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────


@dataclass
class Config:
    """Canonical backtest configuration (Python-facing).

    All fields have explicit, documented defaults mirroring the canonical
    Rust defaults. The Rust config validation remains authoritative: invalid
    values raise a ``ValueError`` from the binding rather than being silently
    repaired.
    """

    starting_balance: float = 10_000.0
    currency: str = "USD"
    leverage: float = 100.0

    symbol: str = "EURUSD"
    base_currency: str = "EUR"
    quote_currency: str = "USD"
    contract_size: float = 100_000.0
    min_quantity: float = 0.01
    max_quantity: float = 100.0
    quantity_step: float = 0.01
    price_decimals: int = 5

    fill_mode: str = NEXT_BAR_OPEN
    spread: float = 0.0002
    slippage: float = 0.0001
    commission: float = 0.0
    commission_mode: str = PER_SIDE
    commission_rate_per_unit: float = 0.0
    interval: str = "1d"

    strategy_name: Optional[str] = None
    params: dict = field(default_factory=dict)
    order_model: Optional[dict] = None
    strategy_source: Optional[str] = None
    dataset_source: Optional[str] = None

    def to_dict(self) -> dict:
        """Serializes to the canonical config dict consumed by the binding."""
        return {k: v for k, v in asdict(self).items() if v is not None}


# ────────────────────────────────────────────────
# Strategy base class (optional convenience)
# ────────────────────────────────────────────────


class Strategy:
    """Optional base class documenting the canonical strategy lifecycle.

    Subclasses override ``initialize``, ``on_bar`` and (optionally)
    ``teardown``. Plain classes with the same method signatures also work.
    """

    def initialize(self, params=None):
        """Called once before the first bar with the resolved params dict."""

    def on_bar(self, bar, portfolio, history):
        """Called once per closed bar; return a list of signal dicts."""
        return []

    def teardown(self):
        """Called once after the last bar."""


# ────────────────────────────────────────────────
# Data coercion helpers
# ────────────────────────────────────────────────


def _coerce_data(data: Any) -> Any:
    """Accepts a DataFrame-like object (duck-typed) by converting it to a list
    of dicts — pandas is NOT a required dependency."""
    if (
        data is not None
        and not isinstance(data, (str, list, tuple, dict))
        and hasattr(data, "to_dict")
        and hasattr(data, "columns")
    ):
        return data.to_dict("records")
    return data


# ────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────


def run(
    strategy: Any,
    data: Union[str, Sequence[Any], Any],
    config: Union[Config, dict, None] = None,
    output: Optional[str] = None,
    bars_per_year: float = 252.0,
) -> RunResult:
    """Runs a canonical backtest with ``strategy``.

    Parameters
    ----------
    strategy:
        A strategy *instance* (or class, which will be instantiated with no
        arguments).
    data:
        A CSV file path, a list of bar dicts, a list of
        ``[timestamp, open, high, low, close, volume?]`` sequences, or a
        DataFrame-like object.
    config:
        A :class:`Config` or a dict of canonical config fields.
    output:
        Optional output directory for the canonical artifacts
        (``run.json`` / ``events.jsonl`` / ``metrics.json``). Create-only.
    bars_per_year:
        Annualization factor for derived metrics only (never economics).
    """
    if inspect.isclass(strategy):
        strategy = strategy()
    data = _coerce_data(data)
    if config is None:
        cfg: dict = {}
    elif isinstance(config, Config):
        cfg = config.to_dict()
    else:
        cfg = dict(config)
    if output is not None:
        # Persistence remains create-only for the run directory itself; only
        # ensure its parent exists so a fresh user does not hit an opaque
        # filesystem error.
        import os

        parent = os.path.dirname(os.path.abspath(output))
        if parent:
            os.makedirs(parent, exist_ok=True)
    return _run(strategy, data, cfg, output, bars_per_year)


def sample_data_path() -> str:
    """Absolute path to the bundled deterministic sample dataset (CSV)."""
    return str(resources.files("observa") / "samples" / "sample_m15.csv")


def sample_strategy_path() -> str:
    """Absolute path to the bundled sample strategy module (Python)."""
    return str(resources.files("observa") / "samples" / "sample_strategy.py")


def replay(run_dir_or_result, *, port=None, block: bool = True, open_browser: bool = False):
    """Starts the local canonical replay server for a persisted run.

    Parameters
    ----------
    run_dir_or_result:
        A persisted run directory (``str``/``os.PathLike``) or a
        :class:`RunResult` whose ``artifact_dir`` exists (created with
        ``output=...`` or ``result.save(...)``).
    port:
        ``None`` (default) asks the OS for a free port. An explicit integer is
        strict: if busy, an ``OSError`` with ``code == "REPLAY_PORT_IN_USE"``
        and ``details["port"]`` is raised.
    block:
        ``True`` (default) serves until interrupted (returns ``None``) — the
        historical behavior. ``False`` returns a :class:`ReplayServer`
        immediately (notebook/agent friendly).
    open_browser:
        When ``True``, opens the replay URL in the default browser.

    Examples
    --------
    >>> server = observa.replay(result, block=False)   # doctest: +SKIP
    >>> server.url                                     # doctest: +SKIP
    'http://127.0.0.1:53421'
    >>> server.stop()                                  # doctest: +SKIP
    """
    artifact_dir = getattr(run_dir_or_result, "artifact_dir", None)
    if hasattr(run_dir_or_result, "final_balance") or hasattr(run_dir_or_result, "summary"):
        if not artifact_dir:
            raise coded(
                ValueError(
                    "this RunResult has not been persisted; pass output=... to "
                    "observa.run(...) or call result.save(dir) before replay"
                ),
                "REPLAY_RUN_NOT_PERSISTED",
            )
        run_dir = artifact_dir
    else:
        run_dir = run_dir_or_result

    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise coded(
                ValueError("port must be an integer or None, got %r" % (port,)),
                "REPLAY_PORT_INVALID",
                {"port": port},
            )
        if not (0 < port < 65536):
            raise coded(
                ValueError("port must be between 1 and 65535, got %d" % port),
                "REPLAY_PORT_INVALID",
                {"port": port},
            )

    from .replay import serve

    return serve(run_dir, port=port, block=block, open_browser=open_browser)


def run_summary(run_dir) -> dict:
    """Summarises a persisted run using only its artifacts (never re-runs).

    Reads ``run.json`` and, when present, ``metrics.json``. Returns a dict
    shaped like :meth:`RunResult.summary`, plus ``error`` for failed runs.
    ``trades`` is taken from ``metrics.json`` when available (else ``None``).
    """
    import json
    import os

    path = os.path.abspath(str(run_dir))
    run_json_path = os.path.join(path, "run.json")
    if not os.path.isdir(path) or not os.path.isfile(run_json_path):
        raise coded(
            FileNotFoundError("no persisted run found at %s (expected run.json)" % path),
            "RUN_DIR_NOT_FOUND",
            {"path": path},
        )
    try:
        with open(run_json_path, "r", encoding="utf-8") as fh:
            run = json.load(fh)
    except (OSError, ValueError) as exc:
        raise coded(
            ValueError("invalid run artifacts at %s: %s" % (run_json_path, exc)),
            "RUN_ARTIFACTS_INVALID",
            {"path": run_json_path},
        )

    metrics = None
    metrics_path = os.path.join(path, "metrics.json")
    if os.path.isfile(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as fh:
                metrics = json.load(fh)
        except (OSError, ValueError) as exc:
            raise coded(
                ValueError("invalid metrics artifacts at %s: %s" % (metrics_path, exc)),
                "RUN_ARTIFACTS_INVALID",
                {"path": metrics_path},
            )

    dataset = run.get("dataset") or {}
    status = run.get("status", "unknown")
    return {
        "status": status,
        "artifact_dir": path,
        "total_bars": dataset.get("bar_count"),
        "trades": (metrics or {}).get("total_trades"),
        "open_positions": run.get("open_positions_remaining"),
        "final_balance": run.get("final_balance"),
        "final_equity": run.get("final_equity"),
        "events": run.get("event_count"),
        "metrics": metrics,
        "dataset_source": dataset.get("source"),
        "run_schema_version": run.get("run_schema_version"),
        "error": run.get("error"),
    }


def _install_resources() -> None:
    global resources
    from importlib import resources  # noqa: F401


_install_resources()

__all__ = [
    "run",
    "replay",
    "run_summary",
    "ReplayServer",
    "error_code",
    "sample_data_path",
    "sample_strategy_path",
    "RunResult",
    "Config",
    "Strategy",
    "MARKET",
    "LIMIT",
    "STOP",
    "BUY",
    "SELL",
    "CLOSE",
    "BAR_CLOSE",
    "NEXT_BAR_OPEN",
    "PER_SIDE",
    "ROUND_TRIP",
    "__version__",
]
