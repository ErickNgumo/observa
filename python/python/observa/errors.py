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
    # OBS-AI-03 run inspection: lookup misses. Run-level artifact problems keep
    # using RUN_DIR_NOT_FOUND / RUN_ARTIFACTS_INVALID above rather than adding
    # duplicate RUN_INSPECT_* codes.
    "EVENT_NOT_FOUND",
    "BAR_NOT_FOUND",
    "POSITION_NOT_FOUND",
    "ORDER_NOT_FOUND",
    # OBS-AI-02 annotations and OBS-SCHEMA-01 reasons: these codes are attached
    # to real exceptions raised from a strategy callback/signal, so they belong
    # in the enumerable set (OBS-AI-04 completeness fix).
    "DRAWING_TYPE_INVALID",
    "DRAWING_FIELD_MISSING",
    "DRAWING_VALUE_INVALID",
    "DRAWING_ID_INVALID",
    "DRAWING_ACTION_INVALID",
    "DRAWING_REFERENCE_INVALID",
    "DRAWING_PANE_INVALID",
    "DRAWING_TIME_INVALID",
    "DRAWING_LIMIT_EXCEEDED",
    "STRATEGY_REASON_TOO_LONG",
    # OBS-AI-04 strategy authoring validation (raised only by
    # observa.validate_strategy / `observa validate-strategy`, never by
    # observa.run).
    "STRATEGY_FILE_NOT_FOUND",
    "STRATEGY_SYNTAX_ERROR",
    "STRATEGY_CLASS_NOT_FOUND",
    "STRATEGY_METHOD_MISSING",
    "STRATEGY_METHOD_SIGNATURE",
    "STRATEGY_NOT_IMPORTABLE",
    "STRATEGY_RETURN_INVALID",
    "STRATEGY_SMOKE_RUN_FAILED",
    "SIGNAL_FIELD_UNKNOWN",
    "SIGNAL_FIELD_MISSING",
    "SIGNAL_FIELD_TYPE_INVALID",
    "SIGNAL_DIRECTION_INVALID",
    "SIGNAL_ORDER_TYPE_INVALID",
    "CLOSE_TICKET_REQUIRED",
    "SIGNAL_TICKET_UNKNOWN",
    "STRATEGY_CLASS_AMBIGUOUS",
)


def error_code(exc: BaseException):
    """Returns ``exc.code`` when present, else ``None`` (compat helper)."""
    return getattr(exc, "code", None)


def coded(exc: BaseException, code: str, details=None) -> BaseException:
    """Attaches ``code``/``details`` to an exception instance and returns it."""
    exc.code = code
    exc.details = dict(details or {})
    return exc
