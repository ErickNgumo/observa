"""Stable machine-readable error codes for the Observa Python API.

Exceptions keep their normal Python classes (``ValueError``,
``FileNotFoundError``, ``FileExistsError``, ``RuntimeError``, ``OSError``) so
existing ``except`` clauses keep working. Observa additionally attaches two
attributes to the raised exception instance:

``exc.code``
    A stable string code (see :data:`ERROR_CODES`).
``exc.details``
    A dict with *known* context only (never parsed out of the message text):
    e.g. ``{"path": ...}``, ``{"port": ...}``, ``{"row": ...}``,
    ``{"bar_index": ...}``.

Order rejections (invalid SL/TP, insufficient margin, invalid quantity,
invalid ticket close) are **not** exceptions: they remain canonical
``order_rejected`` events inside ``result.events``.
"""

ERROR_CODES = (
    "CONFIG_INVALID",
    "DATA_INVALID",
    "DATA_FILE_NOT_FOUND",
    "STRATEGY_ERROR",
    "ENGINE_ERROR",
    "RUN_OUTPUT_EXISTS",
    "RUN_PERSIST_FAILED",
    "RUN_DIR_NOT_FOUND",
    "RUN_ARTIFACTS_INVALID",
    "REPLAY_RUN_NOT_FOUND",
    "REPLAY_ARTIFACTS_INVALID",
    "REPLAY_PORT_IN_USE",
    "REPLAY_PORT_INVALID",
    "REPLAY_RUN_NOT_PERSISTED",
)


def error_code(exc: BaseException):
    """Returns ``exc.code`` when present, else ``None`` (compat helper)."""
    return getattr(exc, "code", None)


def coded(exc: BaseException, code: str, details=None) -> BaseException:
    """Attaches ``code``/``details`` to an exception instance and returns it."""
    exc.code = code
    exc.details = dict(details or {})
    return exc
