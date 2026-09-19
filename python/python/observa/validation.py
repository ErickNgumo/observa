"""Three-tier strategy validation (OBS-AI-04).

Purpose: catch the mistakes an authoring agent actually makes, **before** a real
backtest, and report them as structured, repairable data.

Tiers
-----
* **A — structural (no import).** Path, readability, ``ast.parse``, class
  presence, lifecycle methods visible in the AST. Never executes user code.
* **B — imported (no engine run).** Class resolves, lifecycle callables exist,
  signatures are compatible, ``__init__`` takes no required arguments, and
  ``on_bar`` is genuinely implemented (not inherited from
  ``observa.Strategy``). Never calls ``on_bar``.
* **C — smoke (real Engine, bundled 6-bar fixture).** Runs the strategy with a
  wrapper that inspects the **raw** value returned by ``on_bar`` *before* the
  engine silently normalises or ignores it.

What this module deliberately does NOT do
-----------------------------------------
It never re-implements execution. The canonical Rust Engine still owns fills,
spread, slippage, SL/TP, margin and P&L. Tier C therefore validates **shape and
integration only**: it does not prove strategy logic, does not prove
profitability, and a strategy that emits zero signals in six bars is still
valid. Margin, SL distance, quantity ranges and ticket existence under future
states remain the Engine's business (``order_rejected`` events).

Validation is read-only and stdlib-only. It does **not** change
``observa.run`` semantics: a strategy that is invalid here still runs exactly as
it did before, because the engine keeps its historical leniency. The validator
exists so an agent does not *rely* on that leniency.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import sys

from ._agent.contract import STRATEGY_API_VERSION

# ────────────────────────────────────────────────
# Canonical expectations (kept in lock-step with CONTRACT by the drift tests)
# ────────────────────────────────────────────────

LIFECYCLE = ("initialize", "on_bar", "teardown")
SIGNAL_FIELDS = ("direction", "size", "order_type", "price", "sl", "tp", "reason", "ticket")
REQUIRED_SIGNAL_FIELDS = ("direction", "size")
DIRECTIONS = ("buy", "sell", "close")
ORDER_TYPES = ("market", "limit", "stop")
NUMERIC_SIGNAL_FIELDS = ("price", "sl", "tp")
MAX_REASON_BYTES = 1024
SMOKE_BARS = 6

# Stable key order for every error/warning entry (not-applicable fields are
# omitted, never null).
_ENTRY_KEYS = ("code", "path", "message", "received", "expected", "allowed", "line")

_MODULE_NAME = "_observa_agent_validation_target"


def _entry(code, *, path=None, message=None, received=None, expected=None,
           allowed=None, line=None) -> dict:
    raw = {
        "code": code,
        "path": path,
        "message": message,
        "received": received,
        "expected": expected,
        "allowed": allowed,
        "line": line,
    }
    return {k: raw[k] for k in _ENTRY_KEYS if raw[k] is not None}


def _dedupe(entries):
    """Dedupes by (code, path) keeping the first occurrence.

    Two tiers can report the same defect (tier A from the AST, tier B from the
    imported class). The first, most structural report wins; later entries of the
    same code at the same path are the same defect restated.
    """
    seen = set()
    out = []
    for e in entries:
        key = (e.get("code"), e.get("path"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ────────────────────────────────────────────────
# Tier A — structural, no execution
# ────────────────────────────────────────────────


def _tier_a(path: str, class_name):
    """Returns (chosen_class_name, errors, warnings). Never executes code."""
    errors, warnings = [], []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except UnicodeDecodeError as exc:
        return None, [_entry(
            "STRATEGY_SYNTAX_ERROR", path=os.path.basename(path),
            message="strategy file is not valid UTF-8: %s" % exc,
            expected="UTF-8 encoded Python source",
        )], warnings
    except OSError as exc:
        raise FileNotFoundError(
            "cannot read strategy file %s: %s" % (path, exc)
        ) from exc

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return None, [_entry(
            "STRATEGY_SYNTAX_ERROR", path=os.path.basename(path),
            message="%s" % (exc.msg or exc),
            received=type(exc).__name__, expected="valid Python syntax",
            line=exc.lineno,
        )], warnings

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if not classes:
        return None, [_entry(
            "STRATEGY_CLASS_NOT_FOUND", path=os.path.basename(path),
            message="no class is defined in this file",
            expected="a class with initialize/on_bar/teardown",
        )], warnings

    by_name = {c.name: c for c in classes}
    if class_name is not None:
        chosen = by_name.get(class_name)
        if chosen is None:
            return None, [_entry(
                "STRATEGY_CLASS_NOT_FOUND", path=os.path.basename(path),
                message="class '%s' is not defined in this file" % class_name,
                received=class_name, expected=sorted(by_name),
            )], warnings
    else:
        # Prefer a class that looks like a strategy; otherwise the first class.
        chosen = None
        for c in classes:
            names = {n.name for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if "on_bar" in names:
                chosen = c
                break
        chosen = chosen or classes[0]
        if len(classes) > 1 and chosen.name != classes[0].name:
            warnings.append(_entry(
                "STRATEGY_CLASS_AMBIGUOUS", path=os.path.basename(path),
                message="multiple classes defined; selected '%s' — pass --class to be explicit"
                        % chosen.name,
                allowed=sorted(by_name),
            ))

    declared = {
        n.name for n in chosen.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    has_bases = bool(chosen.bases)
    for method in LIFECYCLE:
        if method not in declared:
            if has_bases:
                # May be inherited — tier B decides. Not an error here.
                continue
            errors.append(_entry(
                "STRATEGY_METHOD_MISSING", path="%s.%s" % (chosen.name, method),
                message="class '%s' does not define %s()" % (chosen.name, method),
                received="missing", expected="a method named %s" % method,
            ))
    return chosen.name, errors, warnings


# ────────────────────────────────────────────────
# Tier B — import and inspect, no engine run
# ────────────────────────────────────────────────


def _import_target(path: str):
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s as a Python module" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(_MODULE_NAME, None)
    return module


def _positional_params(func):
    """Count required positional params, excluding self; None for *args."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    required = 0
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            return None
        if p.default is p.empty:
            required += 1
    return required


def _tier_b(module, class_name):
    """Returns (cls, errors, warnings). Never calls on_bar."""
    import observa

    errors, warnings = [], []
    candidates = [
        (name, obj) for name, obj in vars(module).items()
        if inspect.isclass(obj) and obj.__module__ == module.__name__
    ]
    if class_name is not None:
        cls = getattr(module, class_name, None)
        if cls is None or not inspect.isclass(cls):
            return None, [_entry(
                "STRATEGY_CLASS_NOT_FOUND", path=os.path.basename(module.__file__ or ""),
                message="class '%s' is not defined in this file" % class_name,
                received=class_name, expected=[n for n, _ in candidates],
            )], warnings
    else:
        if not candidates:
            return None, [_entry(
                "STRATEGY_CLASS_NOT_FOUND", path=os.path.basename(module.__file__ or ""),
                message="no class is defined in this file",
                expected="a class with initialize/on_bar/teardown",
            )], warnings
        cls = None
        for _name, obj in candidates:
            if hasattr(obj, "on_bar"):
                cls = obj
                break
        cls = cls or candidates[0][1]

    name = cls.__name__

    # Constructibility: no required constructor arguments.
    init = cls.__dict__.get("__init__")
    if init is not None:
        req = _positional_params(init)
        if req:
            errors.append(_entry(
                "STRATEGY_METHOD_SIGNATURE", path="%s.__init__" % name,
                message="__init__ requires %d argument(s); Observa instantiates the "
                        "strategy with no arguments" % req,
                received="%d required positional argument(s)" % req,
                expected="__init__(self, ...) with no required arguments",
            ))

    is_subclass = issubclass(cls, observa.Strategy)
    for method in LIFECYCLE:
        fn = getattr(cls, method, None)
        if not callable(fn):
            errors.append(_entry(
                "STRATEGY_METHOD_MISSING", path="%s.%s" % (name, method),
                message="class '%s' has no callable %s()" % (name, method),
                received="missing", expected="a method named %s" % method,
            ))
            continue
        if method == "on_bar" and is_subclass and "on_bar" not in cls.__dict__:
            errors.append(_entry(
                "STRATEGY_METHOD_MISSING", path="%s.on_bar" % name,
                message="class '%s' subclasses observa.Strategy but does not override "
                        "on_bar(); the base implementation returns [] and would produce "
                        "a silent zero-trade run" % name,
                received="inherited no-op", expected="an explicit on_bar override",
            ))
            continue
        expected_arity = {"initialize": (0, 1), "on_bar": (3, 3), "teardown": (0, 0)}[method]
        actual = _positional_params(fn)
        if actual is not None and not (expected_arity[0] <= actual <= expected_arity[1]):
            errors.append(_entry(
                "STRATEGY_METHOD_SIGNATURE", path="%s.%s" % (name, method),
                message="%s() takes %d positional argument(s) besides self; expected %s"
                        % (method, actual, expected_arity[0] if expected_arity[0] == expected_arity[1]
                           else "%d-%d" % expected_arity),
                received=actual, expected=list(expected_arity),
            ))
    return cls, errors, warnings


# ────────────────────────────────────────────────
# Tier C — smoke run with raw-return observation
# ────────────────────────────────────────────────


class _RawObserver:
    """Validates the raw value returned from the user's on_bar.

    The value is passed through unchanged, so the canonical Engine still behaves
    exactly as it normally would — including silently ignoring malformed shapes.
    That leniency is precisely why we inspect the raw value first.
    """

    def __init__(self, class_name):
        self.class_name = class_name
        self.errors = []
        self.warnings = []
        self.signals_observed = 0
        self.calls = 0

    # -- helpers ---------------------------------------------------------
    def _err(self, *a, **kw):
        self.errors.append(_entry(*a, **kw))

    def _warn(self, *a, **kw):
        self.warnings.append(_entry(*a, **kw))

    def _signal(self, obj, path, open_ids):
        if not isinstance(obj, dict):
            self._err(
                "STRATEGY_RETURN_INVALID", path=path,
                message="each signal must be a dict", received=type(obj).__name__,
                expected="dict",
            )
            return
        self.signals_observed += 1

        unknown = [k for k in obj if k not in SIGNAL_FIELDS]
        if unknown:
            self._err(
                "SIGNAL_FIELD_UNKNOWN", path=path,
                message="unknown signal field(s) %s — the engine silently ignores them, "
                        "so the intent is lost" % (", ".join(repr(k) for k in unknown)),
                received=unknown, allowed=sorted(SIGNAL_FIELDS),
            )
        missing = [k for k in REQUIRED_SIGNAL_FIELDS if k not in obj]
        if missing:
            self._err(
                "SIGNAL_FIELD_MISSING", path=path,
                message="signal is missing required field(s): %s" % ", ".join(missing),
                received=sorted(obj), expected=list(REQUIRED_SIGNAL_FIELDS),
            )

        direction = obj.get("direction")
        normalized = None
        if "direction" in obj:
            if not isinstance(direction, str):
                self._err(
                    "SIGNAL_FIELD_TYPE_INVALID", path=path + ".direction",
                    message="'direction' must be a string", received=type(direction).__name__,
                    expected="str",
                )
            else:
                normalized = direction.lower()
                if normalized not in DIRECTIONS:
                    self._err(
                        "SIGNAL_DIRECTION_INVALID", path=path + ".direction",
                        message="unknown direction %r" % direction,
                        received=direction, allowed=list(DIRECTIONS),
                    )

        if "size" in obj and not _is_number(obj["size"]):
            self._err(
                "SIGNAL_FIELD_TYPE_INVALID", path=path + ".size",
                message="'size' must be a number", received=type(obj["size"]).__name__,
                expected="number",
            )

        if "order_type" in obj and obj["order_type"] is not None:
            ot = obj["order_type"]
            if not isinstance(ot, str) or ot.lower() not in ORDER_TYPES:
                self._err(
                    "SIGNAL_ORDER_TYPE_INVALID", path=path + ".order_type",
                    message="unknown order_type %r" % (ot,),
                    received=ot, allowed=list(ORDER_TYPES),
                )

        for field in NUMERIC_SIGNAL_FIELDS:
            if field in obj and obj[field] is not None and not _is_number(obj[field]):
                self._err(
                    "SIGNAL_FIELD_TYPE_INVALID", path=path + "." + field,
                    message="'%s' must be a number or None" % field,
                    received=type(obj[field]).__name__, expected="number",
                )

        if "reason" in obj and obj["reason"] is not None:
            reason = obj["reason"]
            if not isinstance(reason, str):
                self._err(
                    "SIGNAL_FIELD_TYPE_INVALID", path=path + ".reason",
                    message="'reason' must be a string", received=type(reason).__name__,
                    expected="str",
                )
            else:
                n = len(reason.encode("utf-8"))
                if n > MAX_REASON_BYTES:
                    self._err(
                        "STRATEGY_REASON_TOO_LONG", path=path + ".reason",
                        message="reason is %d UTF-8 bytes; the maximum is %d"
                                % (n, MAX_REASON_BYTES),
                        received=n, expected="<= %d bytes" % MAX_REASON_BYTES,
                    )

        if normalized == "close":
            ticket = obj.get("ticket")
            if ticket is None:
                self._err(
                    "CLOSE_TICKET_REQUIRED", path=path + ".ticket",
                    message="a close signal must name the exact position ticket "
                            "(use portfolio['open_positions'][i]['position_id'])",
                    received=None, expected="position_id string",
                )
            elif not isinstance(ticket, str):
                self._err(
                    "SIGNAL_FIELD_TYPE_INVALID", path=path + ".ticket",
                    message="'ticket' must be a string", received=type(ticket).__name__,
                    expected="str",
                )
            elif ticket not in open_ids:
                # Provable only against the snapshot observed at this bar, so
                # this is reported as a warning rather than a hard failure.
                self._warn(
                    "SIGNAL_TICKET_UNKNOWN", path=path + ".ticket",
                    message="ticket %r is not among the positions open at this bar; the "
                            "engine will record an order_rejected event" % ticket,
                    received=ticket, allowed=sorted(open_ids),
                )

    # -- the observation entry point -------------------------------------
    def observe(self, raw, bar, portfolio):
        self.calls += 1
        path = "%s.on_bar" % self.class_name
        try:
            open_ids = {
                p.get("position_id")
                for p in (portfolio or {}).get("open_positions") or []
                if isinstance(p, dict)
            }
        except Exception:  # noqa: BLE001 - never let observation break the run
            open_ids = set()

        if raw is None:
            self._err(
                "STRATEGY_RETURN_INVALID", path=path,
                message="on_bar returned None; return [] for 'no action' — None is "
                        "ambiguous and is silently ignored by the engine",
                received="None", expected="list or dict",
            )
            return
        if isinstance(raw, dict):
            if "signals" not in raw:
                shape = "a bare signal dict" if "direction" in raw else "a dict without a 'signals' key"
                self._err(
                    "STRATEGY_RETURN_INVALID", path=path,
                    message="on_bar returned %s; the engine only reads the 'signals' key, "
                            "so nothing was executed. Return a list, or "
                            "{'signals': [...], 'drawings': [...]}" % shape,
                    received=sorted(raw), expected=["signals", "drawings"],
                )
            else:
                signals = raw["signals"]
                if signals is None:
                    pass
                elif not isinstance(signals, list):
                    self._err(
                        "STRATEGY_RETURN_INVALID", path=path + ".signals",
                        message="'signals' must be a list", received=type(signals).__name__,
                        expected="list",
                    )
                else:
                    for i, item in enumerate(signals):
                        self._signal(item, "%s.signals[%d]" % (path, i), open_ids)
                if "drawings" in raw and raw["drawings"] is not None \
                        and not isinstance(raw["drawings"], list):
                    self._err(
                        "DRAWING_TYPE_INVALID", path=path + ".drawings",
                        message="'drawings' must be a list",
                        received=type(raw["drawings"]).__name__, expected="list",
                    )
                extra = [k for k in raw if k not in ("signals", "drawings")]
                if extra:
                    self._warn(
                        "SIGNAL_FIELD_UNKNOWN", path=path,
                        message="unknown envelope key(s) %s are ignored"
                                % (", ".join(repr(k) for k in extra)),
                        received=extra, allowed=["signals", "drawings"],
                    )
            return
        if isinstance(raw, list):
            for i, item in enumerate(raw):
                self._signal(item, "%s[%d]" % (path, i), open_ids)
            return
        self._err(
            "STRATEGY_RETURN_INVALID", path=path,
            message="on_bar must return a list or a dict with 'signals'",
            received=type(raw).__name__, expected="list or dict",
        )


class _SmokeWrapper:
    """Delegates to the user strategy, observing every raw return value."""

    def __init__(self, target, observer):
        self._target = target
        self._observer = observer

    def initialize(self, params=None):
        fn = getattr(self._target, "initialize", None)
        if callable(fn):
            return fn(params)
        return None

    def on_bar(self, bar, portfolio, history):
        raw = self._target.on_bar(bar, portfolio, history)
        self._observer.observe(raw, bar, portfolio)
        return raw

    def teardown(self):
        fn = getattr(self._target, "teardown", None)
        if callable(fn):
            return fn()
        return None


def _smoke_config(smoke_csv):
    import observa

    return observa.Config(
        dataset_source="agent-smoke",
        fill_mode=observa.NEXT_BAR_OPEN,
        spread=0.0002,
        slippage=0.0001,
        commission=0.0,
        commission_mode=observa.ROUND_TRIP,
        interval="15m",
        params={},
        strategy_name="AgentSmoke",
    )


def _tier_c(cls, class_name):
    """Runs the real engine over the bundled 6-bar fixture.

    Returns (errors, warnings, smoke_info). Never persists anything, never
    asserts that signals were produced, and never touches execution economics.
    """
    import observa

    from ._agent import smoke_bars_path

    observer = _RawObserver(class_name)
    errors = []
    try:
        instance = cls()
    except Exception as exc:  # noqa: BLE001
        return [_entry(
            "STRATEGY_NOT_IMPORTABLE", path=class_name,
            message="could not instantiate the strategy: %s: %s" % (type(exc).__name__, exc),
            received=type(exc).__name__, expected="constructible with no arguments",
        )], [], None

    wrapper = _SmokeWrapper(instance, observer)
    engine_error = None
    try:
        observa.run(wrapper, smoke_bars_path(), config=_smoke_config(smoke_bars_path()))
    except Exception as exc:  # noqa: BLE001
        engine_error = exc

    if engine_error is not None:
        code = getattr(engine_error, "code", None)
        details = getattr(engine_error, "details", None) or {}
        observed = {e["code"] for e in observer.errors}
        generic = code in (None, "STRATEGY_ERROR", "STRATEGY_SMOKE_RUN_FAILED")
        # Prefer the specific canonical code the engine already produced
        # (STRATEGY_REASON_TOO_LONG, DRAWING_*). If the engine's failure is
        # generic, or restates something the raw observer already described more
        # precisely, keep only the observer's entry.
        if generic and observed:
            pass
        elif code is not None and code in observed:
            pass
        else:
            errors.append(_entry(
                code or "STRATEGY_SMOKE_RUN_FAILED", path="%s.on_bar" % class_name,
                message=str(engine_error).splitlines()[0][:400],
                received=details.get("drawing_id") or details.get("drawing_type"),
                expected="a valid signal/drawing",
            ))

    errors.extend(observer.errors)
    errors = _dedupe(errors)
    warnings = _dedupe(observer.warnings)

    info = {
        "ran": True,
        "bars": SMOKE_BARS,
        "on_bar_calls": observer.calls,
        "signals_observed": observer.signals_observed,
        "note": ("runtime shape and integration only — this is not a test of "
                 "strategy logic or profitability, and zero signals in six bars "
                 "is not a failure"),
    }
    return errors, warnings, info


# ────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────


def validate_strategy(path_or_class, *, class_name=None, smoke=False) -> dict:
    """Validates a strategy file (or class) across tiers A/B/C.

    Parameters
    ----------
    path_or_class:
        A path to a ``.py`` file, or a strategy class already imported.
    class_name:
        Explicit class name, when the file defines more than one candidate.
    smoke:
        Also run tier C (the real Engine over the bundled 6-bar fixture).

    Returns
    -------
    dict
        ``{valid, strategy_api_version, tiers_run, file, class, errors,
        warnings[, smoke]}``. ``errors``/``warnings`` entries carry
        ``code``/``path``/``message`` plus ``received``/``expected``/``allowed``
        where applicable; not-applicable fields are omitted.

    Raises
    ------
    FileNotFoundError
        If a path was given and cannot be read (a setup problem, not an invalid
        strategy). Carries ``.code == "STRATEGY_FILE_NOT_FOUND"``.
    """
    errors, warnings, tiers = [], [], []
    file_repr = None
    resolved_name = class_name

    target_cls = None
    if inspect.isclass(path_or_class):
        target_cls = path_or_class
        resolved_name = class_name or path_or_class.__name__
        try:
            file_repr = os.path.basename(inspect.getfile(path_or_class))
        except (TypeError, OSError):
            file_repr = None
        module = sys.modules.get(path_or_class.__module__)
        if module is not None:
            tiers.append("B")
            cls, errs, warns = _tier_b(module, resolved_name)
            errors.extend(errs)
            warnings.extend(warns)
            target_cls = cls or target_cls
    else:
        path = os.fspath(path_or_class)
        if not os.path.isfile(path):
            exc = FileNotFoundError("no such strategy file: %s" % path)
            exc.code = "STRATEGY_FILE_NOT_FOUND"
            exc.details = {"path": os.path.basename(path)}
            raise exc
        file_repr = os.path.basename(path)
        tiers.append("A")
        name_a, errs_a, warns_a = _tier_a(path, class_name)
        errors.extend(errs_a)
        warnings.extend(warns_a)
        resolved_name = resolved_name or name_a

        if name_a is None and errs_a:
            # Structural failure: importing would only produce noise.
            return _report(False, tiers, file_repr, resolved_name, errors, warnings, None)

        tiers.append("B")
        try:
            module = _import_target(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(_entry(
                "STRATEGY_NOT_IMPORTABLE", path=file_repr,
                message="importing the strategy file raised %s: %s"
                        % (type(exc).__name__, exc),
                received=type(exc).__name__, expected="an importable module",
            ))
            return _report(False, tiers, file_repr, resolved_name, errors, warnings, None)
        cls, errs_b, warns_b = _tier_b(module, class_name)
        errors.extend(errs_b)
        warnings.extend(warns_b)
        target_cls = cls
        resolved_name = (cls.__name__ if cls is not None else resolved_name)

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)

    smoke_info = None
    if smoke and target_cls is not None and not errors:
        tiers.append("C")
        errs_c, warns_c, smoke_info = _tier_c(target_cls, resolved_name)
        errors = _dedupe(errors + errs_c)
        warnings = _dedupe(warnings + warns_c)

    valid = not errors
    return _report(valid, tiers, file_repr, resolved_name, errors, warnings, smoke_info)


def _report(valid, tiers, file_repr, class_repr, errors, warnings, smoke_info):
    report = {
        "valid": bool(valid),
        "strategy_api_version": STRATEGY_API_VERSION,
        "tiers_run": list(tiers),
        "file": file_repr,
        "class": class_repr,
        "errors": errors,
        "warnings": warnings,
    }
    if smoke_info is not None:
        report["smoke"] = smoke_info
    return report


def report_to_json(report: dict) -> str:
    """Deterministic JSON rendering used by the CLI's ``--json`` mode."""
    return json.dumps(report, indent=2, sort_keys=True)
