"""OBS-AI-04 — agent strategy authoring contract tests.

Run against the **installed wheel**:

    python python/tests/test_agent_contract.py

Everything that must ship is reached through ``observa.agent_*_path()`` so the
suite works from an installed wheel with no repository assumptions. The few
repo-relative checks at the end are *drift* checks that compare the bundled
assets against their repository mirrors — they are skipped cleanly when the
repository is not present (e.g. running the wheel in a bare environment).

No third-party dependency is required or imported.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap

import observa

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: %s" % (detail,)))


def _has_repo() -> bool:
    return os.path.isfile(os.path.join(REPO, "llms-full.txt"))


def _cli(args, cwd=None):
    """Runs the console script belonging to *this* interpreter.

    Deliberately not ``shutil.which`` — a stale ``observa`` from an unrelated
    virtualenv earlier on PATH must never be what we test.
    """
    script = os.path.join(os.path.dirname(sys.executable), "observa")
    if os.path.isfile(script):
        cmd = [script] + list(args)
    else:
        cmd = [sys.executable, "-c",
               "import sys; from observa.cli import main; sys.exit(main(sys.argv[1:]))"] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


@contextlib.contextmanager
def strategy_file(name, body):
    tmp = tempfile.mkdtemp(prefix="ai04-test-")
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body))
    try:
        yield path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


VALID = """
    import observa

    class Valid(observa.Strategy):
        def initialize(self, params=None):
            self.period = 2

        def on_bar(self, bar, portfolio, history):
            if len(history) < self.period:
                return []
            return [{"direction": "buy", "size": 1.0, "sl": 1.0, "reason": "entry"}]

        def teardown(self):
            pass
"""


# ── 1. spec / contract ───────────────────────────────────────────────────


def test_spec_is_json_and_versioned():
    spec = observa.agent_spec()
    check("agent_spec() returns a dict", isinstance(spec, dict))
    try:
        dumped = json.dumps(spec, sort_keys=True)
        check("agent_spec() is JSON-serialisable", True)
    except (TypeError, ValueError) as exc:  # pragma: no cover
        dumped = ""
        check("agent_spec() is JSON-serialisable", False, exc)

    check("strategy_api_version is present", "strategy_api_version" in spec)
    check("strategy_api_version == '1'", spec.get("strategy_api_version") == "1",
          spec.get("strategy_api_version"))
    check("observa.STRATEGY_API_VERSION matches the spec",
          observa.STRATEGY_API_VERSION == spec.get("strategy_api_version"))
    check("observa_version is recorded", spec.get("observa_version") == observa.__version__,
          spec.get("observa_version"))

    required = ["strategy_api_version", "observa_version", "installation", "lifecycle",
                "on_bar", "bar", "portfolio", "position", "history", "signals",
                "orders", "closing", "drawings", "reason", "execution_rules",
                "error_codes", "forbidden_patterns", "examples"]
    missing = [k for k in required if k not in spec]
    check("spec contains every required top-level key", not missing, missing)

    check("spec serialises under 12 KB", len(dumped) <= 12 * 1024, len(dumped))

    # deep copy: callers must not be able to mutate global state
    first = observa.agent_spec()
    first["strategy_api_version"] = "MUTATED"
    first["lifecycle"]["required"].append("mutated")
    second = observa.agent_spec()
    check("agent_spec() returns a deep copy (no global mutation)",
          second["strategy_api_version"] == "1"
          and "mutated" not in second["lifecycle"]["required"])


def test_contract_matches_implementation():
    spec = observa.agent_spec()

    # lifecycle
    check("lifecycle lists initialize/on_bar/teardown",
          spec["lifecycle"]["required"] == ["initialize", "on_bar", "teardown"],
          spec["lifecycle"]["required"])
    check("observa.Strategy exposes the three lifecycle methods",
          all(hasattr(observa.Strategy, m) for m in ("initialize", "on_bar", "teardown")))

    # signal fields
    fields = set(spec["signals"]["fields"])
    expected = {"direction", "size", "order_type", "price", "sl", "tp", "reason", "ticket"}
    check("spec signal fields == the eight the binding reads", fields == expected,
          sorted(fields ^ expected))
    check("spec signal required == ['direction', 'size']",
          spec["signals"]["required"] == ["direction", "size"])

    # enums match the public constants
    check("spec directions are lowercase buy/sell/close",
          "buy" in spec["signals"]["fields"]["direction"]
          and "sell" in spec["signals"]["fields"]["direction"]
          and "close" in spec["signals"]["fields"]["direction"])
    check("public constants match the documented literals",
          (observa.BUY, observa.SELL, observa.CLOSE) == ("buy", "sell", "close")
          and (observa.MARKET, observa.LIMIT, observa.STOP) == ("market", "limit", "stop"))
    check("spec order types == market/limit/stop",
          spec["orders"]["order_types"] == ["market", "limit", "stop"],
          spec["orders"]["order_types"])

    # reason
    check("spec reason max_bytes == 1024", spec["reason"]["max_bytes"] == 1024)
    check("spec reason code == STRATEGY_REASON_TOO_LONG",
          spec["reason"]["code"] == "STRATEGY_REASON_TOO_LONG")

    # drawings
    check("spec lists the eight drawing types",
          sorted(spec["drawings"]["types"]) == sorted(
              ["series", "hline", "line", "rectangle", "region", "marker", "label", "bar_color"]),
          spec["drawings"]["types"])
    check("spec drawings max_per_bar == 256", spec["drawings"]["max_per_bar"] == 256)
    check("spec drawing codes are the canonical DRAWING_* set",
          all(c.startswith("DRAWING_") for c in spec["drawings"]["errors"])
          and len(spec["drawings"]["errors"]) == 9)

    # history / position / portfolio traps
    check("spec says history excludes the current bar",
          spec["history"]["current_bar_included"] is False)
    check("spec says history is unbounded", spec["history"]["unbounded"] is True)
    check("spec documents the position input/output alias traps",
          "position_id" in spec["position"]["keys"]
          and "stop_loss" in spec["position"]["keys"]
          and "quantity" in spec["position"]["keys"])
    check("spec portfolio includes the margins",
          {"used_margin", "free_margin"} <= set(spec["portfolio"]["keys"]))

    # execution authority
    check("spec states the Engine owns economics",
          any("Engine" in spec["execution_rules"]["owner"] for _ in [0]))
    check("spec forbids a custom backtest loop",
          any("backtest loop" in p for p in spec["forbidden_patterns"]))


def test_bundled_assets_present():
    for label, fn, name in (
        ("spec.json", observa.agent_spec_path, "spec.json"),
        ("guide", observa.agent_guide_path, "strategy-authoring.md"),
        ("gold example", observa.agent_example_path, "example_strategy.py"),
    ):
        path = fn()
        ok = os.path.isfile(path)
        check("bundled %s exists" % label, ok, path)
        if ok:
            check("bundled %s is named %s" % (label, name), os.path.basename(path) == name)
    check("bundled guide is non-trivial",
          os.path.getsize(observa.agent_guide_path()) > 2000)
    check("bundled example imports observa",
          "import observa" in open(observa.agent_example_path(), encoding="utf-8").read())


def test_spec_json_matches_contract():
    from observa._agent._render import SPEC_REGENERATE_HINT
    from observa._agent.contract import render_spec

    bundled = open(observa.agent_spec_path(), encoding="utf-8").read()
    rendered = render_spec(observa.__version__)
    check("bundled spec.json == render(CONTRACT) (no second authority)",
          bundled == rendered,
          "regenerate with `%s`" % SPEC_REGENERATE_HINT)

    # OBS-AI-04 QA finding L1: the hint must target the REPOSITORY source file,
    # not the copy inside the installed package.
    check("spec regeneration hint is a repo-targeting command",
          "--out" in SPEC_REGENERATE_HINT
          and "python/python/observa/_agent/spec.json" in SPEC_REGENERATE_HINT,
          SPEC_REGENERATE_HINT)
    check("spec regeneration hint is runnable from the repository root",
          SPEC_REGENERATE_HINT.startswith("python -m observa._agent._render"),
          SPEC_REGENERATE_HINT)


def test_validation_trust_boundary_is_documented():
    """OBS-AI-04 QA finding M1: validation is not a sandbox and must say so."""
    import observa.cli as cli

    # A. machine-readable contract
    sec = observa.agent_spec()["validation"]["security"]
    check("contract exposes validation.security", isinstance(sec, dict), type(sec).__name__)
    check("contract says validation is NOT sandboxed", sec.get("sandboxed") is False,
          sec.get("sandboxed"))
    check("contract says trusted code only", sec.get("trusted_code_only") is True,
          sec.get("trusted_code_only"))
    check("contract tier A does not import or execute",
          "not import" in sec.get("tier_a", "") and "does not import or execute" in sec.get("tier_a", ""),
          sec.get("tier_a"))
    check("contract tier B says it IMPORTS the module and runs top-level code",
          "IMPORTS" in sec.get("tier_b", "") and "top-level" in sec.get("tier_b", ""),
          sec.get("tier_b"))
    check("contract tier C says it EXECUTES on_bar",
          "EXECUTES" in sec.get("tier_c", "") and "on_bar" in sec.get("tier_c", ""),
          sec.get("tier_c"))
    check("contract carries the canonical warning text",
          "not a sandbox" in sec.get("warning", "")
          and "Tier B imports" in sec.get("warning", "")
          and "Tier C" in sec.get("warning", "")
          and "you trust" in sec.get("warning", ""),
          sec.get("warning"))

    # B. bundled authoring guide (the copy inside the wheel)
    guide = open(observa.agent_guide_path(), encoding="utf-8").read()
    check("bundled guide warns that validation is not a sandbox",
          "not a sandbox" in guide, "")
    check("bundled guide says tier B imports the strategy module",
          "imports the strategy module" in guide)
    check("bundled guide says tier C executes on_bar",
          "executes" in guide and "on_bar" in guide)
    check("bundled guide says tier A does not import or execute",
          "does **not** import" in guide or "does not import" in guide)
    check("bundled guide tells the reader to only validate trusted code",
          "code you trust" in guide)

    # C. docs/STRATEGY_API.md (generated block + prose)
    if _has_repo():
        sa = open(os.path.join(REPO, "docs", "STRATEGY_API.md"), encoding="utf-8").read()
        check("STRATEGY_API.md warns that validation is not a sandbox",
              "not a sandbox" in sa)
        check("STRATEGY_API.md states the tier B/C trust boundary",
              "IMPORTS the strategy module" in sa and "EXECUTES on_bar()" in sa)
    else:
        check("repository present for STRATEGY_API check (skipped: not a checkout)", True)

    # D. CLI help
    rc, out, err = _cli(["validate-strategy", "--help"])
    check("`validate-strategy --help` exits 0", rc == 0, rc)
    helptext = out + err
    check("CLI help states validation is not sandboxed",
          "not sandboxed" in helptext or "NOT sandboxed" in helptext, helptext[:200])
    check("CLI help says tier B imports / tier C executes",
          "imports the strategy module" in helptext and "executes on_bar()" in helptext,
          helptext[:200])
    check("CLI help says only validate code you trust", "code you trust" in helptext)
    check("CLI help keeps the usage line and exit codes",
          "usage: observa validate-strategy FILE" in helptext
          and "0 valid, 1 invalid strategy, 2 usage/setup error" in helptext)
    check("the CLI trust constant is the one the help prints",
          cli.VALIDATION_SECURITY_HELP in helptext)

    # No surface may claim the whole validator is non-executing or safe on
    # untrusted input.
    for name, text in (("bundled guide", guide), ("CLI help", helptext)):
        lowered = text.lower()
        check("no 'safe for untrusted code' claim in the %s" % name,
              "safe for untrusted" not in lowered and "safe to run untrusted" not in lowered)
        check("no blanket 'never executes' claim in the %s" % name,
              "never executes code" not in lowered and "never executes your code" not in lowered)


def test_error_codes_complete():
    from observa.errors import ERROR_CODES

    spec = observa.agent_spec()
    authoring = set(spec["error_codes"]["authoring"])
    drawing = set(spec["drawings"]["errors"])
    missing_authoring = sorted(authoring - set(ERROR_CODES))
    missing_drawing = sorted(drawing - set(ERROR_CODES))
    check("every authoring code is in ERROR_CODES", not missing_authoring, missing_authoring)
    check("every drawing code is in ERROR_CODES", not missing_drawing, missing_drawing)
    check("STRATEGY_REASON_TOO_LONG is in ERROR_CODES",
          "STRATEGY_REASON_TOO_LONG" in ERROR_CODES)
    base = ["CONFIG_INVALID", "DATA_INVALID", "STRATEGY_ERROR", "ENGINE_ERROR",
            "RUN_OUTPUT_EXISTS", "RUN_DIR_NOT_FOUND", "RUN_ARTIFACTS_INVALID"]
    check("pre-existing runtime codes were not removed",
          all(c in ERROR_CODES for c in base),
          [c for c in base if c not in ERROR_CODES])


# ── 2. validator ─────────────────────────────────────────────────────────


def test_validation_gold_and_valid():
    report = observa.validate_strategy(observa.agent_example_path(), smoke=True)
    check("gold example validates cleanly (A/B/C)",
          report["valid"] is True and report["tiers_run"] == ["A", "B", "C"],
          report.get("errors"))
    check("gold example report carries the strategy api version",
          report["strategy_api_version"] == "1")

    with strategy_file("valid.py", VALID) as path:
        rep = observa.validate_strategy(path)
        check("a well-formed strategy validates (A/B only)",
              rep["valid"] is True and rep["tiers_run"] == ["A", "B"], rep.get("errors"))
        rep_smoke = observa.validate_strategy(path, smoke=True)
        check("the same strategy validates with smoke (A/B/C)",
              rep_smoke["valid"] is True and rep_smoke["tiers_run"] == ["A", "B", "C"],
              rep_smoke.get("errors"))


def test_validation_reports_errors_only():
    def codes(report):
        return [e["code"] for e in report["errors"]]

    # F6 — inherited empty on_bar is a tier B failure
    with strategy_file("inherit.py", """
        import observa
        class Inherited(observa.Strategy):
            def initialize(self, params=None): pass
            def teardown(self): pass
    """) as path:
        rep = observa.validate_strategy(path)
        check("F6 missing on_bar override is detected (tier B)",
              "STRATEGY_METHOD_MISSING" in codes(rep) and rep["valid"] is False, codes(rep))
        check("missing on_bar is a tier B (not smoke) finding", rep["tiers_run"] == ["A", "B"])

    # syntax error
    with strategy_file("bad.py", "class X:\n    def on_bar(self\n") as path:
        rep = observa.validate_strategy(path)
        check("syntax error -> STRATEGY_SYNTAX_ERROR",
              "STRATEGY_SYNTAX_ERROR" in codes(rep), codes(rep))

    # no class
    with strategy_file("nocls.py", "x = 1\n") as path:
        rep = observa.validate_strategy(path)
        check("no class -> STRATEGY_CLASS_NOT_FOUND",
              "STRATEGY_CLASS_NOT_FOUND" in codes(rep), codes(rep))

    # missing file is a setup error
    try:
        observa.validate_strategy(os.path.join(tempfile.gettempdir(), "definitely-absent-ai04.py"))
        check("missing file raises FileNotFoundError", False, "no raise")
    except FileNotFoundError as exc:
        check("missing file raises FileNotFoundError with STRATEGY_FILE_NOT_FOUND",
              getattr(exc, "code", None) == "STRATEGY_FILE_NOT_FOUND",
              getattr(exc, "code", None))

    # F1 bare dict, F2 None, F4 misspelled envelope, unsupported type
    cases = {
        "F1_bare_dict": 'return {"direction": "buy", "size": 1.0}',
        "F2_none": "return None",
        "F4_misspelled": 'return {"signal": [{"direction": "buy", "size": 1.0}]}',
        "unsupported_str": 'return "buy"',
        "unsupported_tuple": 'return ({"direction": "buy", "size": 1.0},)',
    }
    for name, body in cases.items():
        with strategy_file(name + ".py", """
            class C:
                def initialize(self, params=None): pass
                def teardown(self): pass
                def on_bar(self, bar, portfolio, history):
                    %s
        """ % body) as path:
            rep = observa.validate_strategy(path, smoke=True)
            check("%s -> STRATEGY_RETURN_INVALID" % name,
                  "STRATEGY_RETURN_INVALID" in codes(rep) and rep["valid"] is False, codes(rep))

    # F3 unknown signal key (tier C, runtime-return validation)
    with strategy_file("f3.py", """
        class F3:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "buy", "size": 1.0, "stop_loss": 1.0}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        unknown = [e for e in rep["errors"] if e["code"] == "SIGNAL_FIELD_UNKNOWN"]
        check("F3 unknown signal key -> SIGNAL_FIELD_UNKNOWN (tier C)",
              bool(unknown) and "C" in rep["tiers_run"], codes(rep))
        if unknown:
            check("F3 error names the offending field",
                  "stop_loss" in str(unknown[0].get("received")), unknown[0])
            check("F3 error lists the allowed fields",
                  "sl" in (unknown[0].get("allowed") or []), unknown[0].get("allowed"))

    # bad direction
    with strategy_file("dir.py", """
        class D:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "long", "size": 1.0}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        entry = next((e for e in rep["errors"] if e["code"] == "SIGNAL_DIRECTION_INVALID"), None)
        check("bad direction -> SIGNAL_DIRECTION_INVALID", entry is not None, codes(rep))
        if entry:
            check("bad direction error carries received + allowed",
                  entry.get("received") == "long"
                  and entry.get("allowed") == ["buy", "sell", "close"], entry)

    # close without ticket
    with strategy_file("ticket.py", """
        class T:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "close", "size": 1.0}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        check("close without ticket -> CLOSE_TICKET_REQUIRED",
              "CLOSE_TICKET_REQUIRED" in codes(rep), codes(rep))

    # bad drawing -> canonical DRAWING_* code
    with strategy_file("draw.py", """
        class Dr:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return {"signals": [], "drawings": [{"id": "a", "type": "nope"}]}
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        check("bad drawing -> a canonical DRAWING_* code",
              any(c.startswith("DRAWING_") for c in codes(rep)) and rep["valid"] is False,
              codes(rep))

    # reason too long -> reuse the engine's canonical code
    with strategy_file("reason.py", """
        class R:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "buy", "size": 1.0, "reason": "x" * 1025}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        entry = next((e for e in rep["errors"] if e["code"] == "STRATEGY_REASON_TOO_LONG"), None)
        check("reason > 1024 bytes -> STRATEGY_REASON_TOO_LONG", entry is not None, codes(rep))
        check("reason error reports the actual byte count",
              entry is not None and entry.get("received") == 1025, entry)

    # a 1024-byte reason is fine
    with strategy_file("reason_ok.py", """
        class ROk:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "buy", "size": 1.0, "reason": "x" * 1024}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        check("reason of exactly 1024 bytes is valid", rep["valid"] is True, rep.get("errors"))

    # zero signals in six bars is VALID
    with strategy_file("zero.py", """
        class Zero:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return []
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        check("zero signals during smoke is NOT a failure",
              rep["valid"] is True and rep.get("smoke", {}).get("signals_observed") == 0,
              rep.get("errors"))

    # a 20-bar strategy cannot signal in 6 bars and must still be valid
    with strategy_file("slow.py", """
        class Slow:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                if len(history) < 20:
                    return []
                return [{"direction": "buy", "size": 1.0}]
    """) as path:
        rep = observa.validate_strategy(path, smoke=True)
        check("a 20-bar warm-up strategy is valid even with no signals",
              rep["valid"] is True, rep.get("errors"))


def test_tiers_are_honest():
    """Tier A/B must never execute user code; tier C must be deterministic."""
    sentinel = os.path.join(tempfile.mkdtemp(prefix="ai04-sentinel-"), "EXECUTED")
    with strategy_file("sentinel.py", """
        class Sentinel:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                open(%r, "w").write("executed")
                return []
    """ % sentinel) as path:
        rep = observa.validate_strategy(path)
        check("tier A/B do not execute on_bar (no sentinel)",
              not os.path.exists(sentinel), "sentinel was created")
        check("tier A/B report tiers ['A', 'B']", rep["tiers_run"] == ["A", "B"],
              rep["tiers_run"])

    with strategy_file("det.py", """
        class Det:
            def initialize(self, params=None): pass
            def teardown(self): pass
            def on_bar(self, bar, portfolio, history):
                return [{"direction": "buy", "size": 1.0}]
    """) as path:
        one = observa.validate_strategy(path, smoke=True)
        two = observa.validate_strategy(path, smoke=True)
        check("smoke validation is deterministic",
              json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True))
        check("smoke report contains no absolute temp paths",
              "/tmp/" not in json.dumps(one) and tempfile.gettempdir() not in json.dumps(one),
              json.dumps(one)[:200])
        check("smoke report uses a basename for file", one["file"] == "det.py", one["file"])

    # no class + no smoke still reports A only, without importing
    with strategy_file("broken.py", "this is not python\n") as path:
        rep = observa.validate_strategy(path)
        check("a non-parsing file reports tier A only", rep["tiers_run"] == ["A"], rep["tiers_run"])


# ── 3. CLI ───────────────────────────────────────────────────────────────


def test_cli_agent_spec_and_validate():
    rc, out, err = _cli(["agent-spec", "--json"])
    check("`observa agent-spec --json` exits 0", rc == 0, err[:200])
    try:
        parsed = json.loads(out)
        check("`observa agent-spec --json` stdout is JSON only", True)
        check("`observa agent-spec --json` returns the contract",
              parsed.get("strategy_api_version") == "1")
    except ValueError as exc:
        check("`observa agent-spec --json` stdout is JSON only", False, "%s :: %s" % (exc, out[:120]))

    rc, out, err = _cli(["agent-spec"])
    check("`observa agent-spec` exits 0", rc == 0, err[:200])
    check("`observa agent-spec` prints JSON by default", out.lstrip().startswith("{"))

    rc, out, err = _cli(["agent-spec", "--out", os.path.join(tempfile.mkdtemp(), "s.json")])
    check("`observa agent-spec --out` exits 0", rc == 0, err[:200])

    # validate-strategy: valid
    with strategy_file("clivalid.py", VALID) as path:
        rc, out, err = _cli(["validate-strategy", path, "--json"])
        check("`validate-strategy --json` exits 0 for a valid strategy", rc == 0, err[:200])
        try:
            rep = json.loads(out)
            check("`validate-strategy --json` stdout is JSON only", True)
            check("`validate-strategy --json` reports valid", rep.get("valid") is True)
        except ValueError as exc:
            check("`validate-strategy --json` stdout is JSON only", False, str(exc))

        rc, out, err = _cli(["validate-strategy", path])
        check("`validate-strategy` human mode exits 0", rc == 0, err[:200])
        check("`validate-strategy` human mode mentions VALID", "VALID" in out, out[:80])

    # validate-strategy: invalid -> exit 1
    with strategy_file("clibad.py", """
        class Bad:
            def initialize(self, params=None): pass
            def teardown(self): pass
    """) as path:
        rc, out, err = _cli(["validate-strategy", path, "--json"])
        check("`validate-strategy` exits 1 for an invalid strategy", rc == 1, rc)
        rep = json.loads(out)
        check("invalid CLI report carries errors", bool(rep["errors"]))

    # validate-strategy: missing file -> exit 2
    rc, out, err = _cli(["validate-strategy", "/nonexistent/ai04.py"])
    check("`validate-strategy` exits 2 for a missing file", rc == 2, rc)
    check("missing-file diagnostics go to stderr", "error" in err.lower(), err[:120])

    # smoke through the CLI
    with strategy_file("clismoke.py", VALID) as path:
        rc, out, err = _cli(["validate-strategy", path, "--smoke", "--json"])
        check("`validate-strategy --smoke --json` exits 0", rc == 0, err[:200])
        rep = json.loads(out)
        check("CLI smoke report includes the smoke block", "smoke" in rep, sorted(rep))


def test_mcp_missing_extra_hint_is_safe():
    """The released hint must never *recommend* the bare PyPI name."""
    import observa.cli as cli
    import observa.mcp_server as mcp_server

    hint = cli.MCP_EXTRA_HINT
    check("CLI hint never instructs a bare extra install",
          'install the optional dependency with: pip install "observa[mcp]"' not in hint)
    check("CLI hint warns against bare installs",
          "Do not run" in hint and "unrelated" in hint)
    check("CLI hint shows the local wheel form", "whl[mcp]" in hint)

    src = open(mcp_server.__file__, encoding="utf-8").read()
    check("mcp_server.py no longer instructs the bare extra install",
          'install the optional dependency with: pip install "observa[mcp]"' not in src)
    check("mcp_server.py hint warns against bare installs",
          "unrelated" in src and "Do not run" in src)


def test_cli_unknown_command_still_fails():
    rc, out, err = _cli(["nonsense-command"])
    check("unknown CLI command exits 2", rc == 2, rc)
    rc, out, err = _cli(["agent-spec", "--bogus"])
    check("unknown agent-spec flag exits 2", rc == 2, rc)
    rc, out, err = _cli(["validate-strategy"])
    check("validate-strategy without a file exits 2", rc == 2, rc)


# ── 4. isolation / offline ───────────────────────────────────────────────


def test_no_network_and_no_heavy_deps():
    before = set(sys.modules)
    spec = observa.agent_spec()
    check("agent_spec() works", isinstance(spec, dict))

    # discovery must not require a socket
    real_create = socket.create_connection
    real_getaddr = socket.getaddrinfo

    def _boom(*a, **kw):
        raise AssertionError("network access attempted during discovery/validation")

    socket.create_connection = _boom
    socket.getaddrinfo = _boom
    try:
        observa.agent_spec()
        observa.agent_spec_path()
        observa.agent_guide_path()
        observa.agent_example_path()
        report = observa.validate_strategy(observa.agent_example_path(), smoke=True)
        check("discovery + smoke validation need no network",
              report["valid"] is True, report.get("errors"))
    finally:
        socket.create_connection = real_create
        socket.getaddrinfo = real_getaddr

    for mod in ("mcp", "pandas", "requests", "jsonschema"):
        check("importing observa/authoring does not pull in %s" % mod,
              mod not in sys.modules, mod)


def test_offline_from_foreign_cwd():
    """A zero-repo, isolated interpreter must be able to do all of it."""
    code = textwrap.dedent("""
        import json, os, tempfile
        import observa

        spec = observa.agent_spec()
        assert spec["strategy_api_version"] == "1", spec["strategy_api_version"]
        for p in (observa.agent_spec_path(), observa.agent_guide_path(),
                  observa.agent_example_path()):
            assert os.path.isfile(p), p

        # gold example runs and persists
        import importlib.util
        spec_file = importlib.util.spec_from_file_location("gold", observa.agent_example_path())
        mod = importlib.util.module_from_spec(spec_file)
        spec_file.loader.exec_module(mod)
        out = os.path.join(tempfile.mkdtemp(), "run")
        cfg = observa.Config(dataset_source=observa.sample_data_path(),
                             fill_mode=observa.NEXT_BAR_OPEN, interval="15m",
                             params={"period": 3}, strategy_name="Gold",
                             commission=0.0, spread=0.0002, slippage=0.0001)
        result = observa.run(mod.AgentExample(), observa.sample_data_path(),
                             config=cfg, output=out)
        summary = result.summary()
        assert summary["status"] == "completed", summary
        assert all(os.path.isfile(os.path.join(out, n))
                   for n in ("run.json", "events.jsonl", "metrics.json")), os.listdir(out)

        report = observa.validate_strategy(observa.agent_example_path(), smoke=True)
        assert report["valid"] is True, report["errors"]
        print(json.dumps({"ok": True, "trades": summary["trades"]}))
    """)
    tmp = tempfile.mkdtemp(prefix="ai04-offline-")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp, env=env,
                          capture_output=True, text=True)
    ok = proc.returncode == 0 and '"ok": true' in proc.stdout
    check("offline, isolated interpreter discovers + runs + validates (no repo, no network)",
          ok, (proc.stdout[-300:] + proc.stderr[-500:]))


# ── 5. repository drift / mirrors ────────────────────────────────────────


def test_generated_docs_are_current():
    if not _has_repo():
        check("repository present for drift checks (skipped: not a checkout)", True)
        return
    from observa._agent import _generate

    docs = {
        "llms-full.txt": os.path.join(REPO, "llms-full.txt"),
        "docs/STRATEGY_API.md": os.path.join(REPO, "docs", "STRATEGY_API.md"),
    }
    for label, path in docs.items():
        text = open(path, encoding="utf-8").read()
        for name in _generate.BLOCK_NAMES:
            try:
                current = _generate.find_block(text, name)
            except KeyError as exc:
                check("%s has the %s sentinel block" % (label, name), False, exc)
                continue
            check("%s generated block '%s' is current" % (label, name),
                  current == _generate.render_block(name, observa.__version__),
                  "regenerate with `python -m observa._agent._render --doc %s`" % label)


def test_repo_mirrors_match_bundled_assets():
    if not _has_repo():
        check("repository present for mirror checks (skipped: not a checkout)", True)
        return
    pairs = [
        (observa.agent_guide_path(), os.path.join(REPO, "docs", "agent", "strategy-authoring.md")),
        (observa.agent_example_path(), os.path.join(REPO, "examples", "agent_example.py")),
        (observa.agent_agents_template_path(),
         os.path.join(REPO, "examples", "ai_starter", "AGENTS.md")),
    ]
    for bundled, mirror in pairs:
        if not os.path.isfile(mirror):
            check("mirror exists: %s" % os.path.relpath(mirror, REPO), False, mirror)
            continue
        check("mirror is byte-identical: %s" % os.path.relpath(mirror, REPO),
              open(bundled, encoding="utf-8").read() == open(mirror, encoding="utf-8").read())

    # root AGENTS.md embeds the same template between sentinels
    root = os.path.join(REPO, "AGENTS.md")
    begin = "<!-- BEGIN GENERATED: agent-strategy-authoring -->"
    end = "<!-- END GENERATED: agent-strategy-authoring -->"
    text = open(root, encoding="utf-8").read()
    ok = begin in text and end in text
    check("root AGENTS.md carries the strategy-authoring sentinel block", ok)
    if ok:
        block = text.split(begin, 1)[1].split(end, 1)[0]
        if block.startswith("\n"):
            block = block[1:]
        check("root AGENTS.md block == bundled AGENTS template",
              block == open(observa.agent_agents_template_path(), encoding="utf-8").read())


def test_llms_router_routes_correctly():
    if not _has_repo():
        check("repository present for llms.txt checks (skipped: not a checkout)", True)
        return
    text = open(os.path.join(REPO, "llms.txt"), encoding="utf-8").read()
    lines = text.splitlines()
    check("llms.txt is a compact router (<= 60 lines)", len(lines) <= 60, len(lines))
    for token in ("agent_spec", "agent_guide_path", "agent_example_path",
                  "validate-strategy", "llms-full.txt", "execution-model.md"):
        check("llms.txt routes to %s" % token, token in text)
    check("llms.txt warns against the bare PyPI install",
          "pip install observa" in text and "unrelated" in text)
    check("llms.txt shows the [mcp] form on a wheel reference",
          "whl[mcp]" in text)


def test_starter_is_functional():
    if not _has_repo():
        check("repository present for starter checks (skipped: not a checkout)", True)
        return
    starter_dir = os.path.join(REPO, "examples", "ai_starter")
    strategy_py = os.path.join(starter_dir, "strategy.py")
    check("starter strategy.py exists", os.path.isfile(strategy_py))
    if not os.path.isfile(strategy_py):
        return
    report = observa.validate_strategy(strategy_py, smoke=True)
    check("starter strategy.py validates cleanly", report["valid"] is True, report.get("errors"))
    check("starter no longer ships an unused data/ directory",
          not os.path.isdir(os.path.join(starter_dir, "data")))
    for name in ("AGENTS.md", "strategy.py", "run.py", "README.md"):
        check("starter contains %s" % name, os.path.isfile(os.path.join(starter_dir, name)))
    agents = open(os.path.join(starter_dir, "AGENTS.md"), encoding="utf-8").read()
    check("starter AGENTS.md warns against the bare PyPI install",
          "pip install observa" in agents and "unrelated" in agents)

    # run.py must actually work, from a copy so the repo is not polluted
    work = tempfile.mkdtemp(prefix="ai04-starter-")
    shutil.copytree(starter_dir, os.path.join(work, "starter"))
    proc = subprocess.run([sys.executable, "run.py"], cwd=os.path.join(work, "starter"),
                          capture_output=True, text=True)
    ok = proc.returncode == 0 and "final_equity" in proc.stdout
    check("starter run.py executes and persists a run", ok,
          (proc.stdout[-200:] + proc.stderr[-400:]))
    check("starter run.py wrote canonical artifacts",
          os.path.isdir(os.path.join(work, "starter", "runs"))
          and any("run.json" in files for _d, _s, files in os.walk(os.path.join(work, "starter", "runs"))),
          "no run.json found")
    shutil.rmtree(work, ignore_errors=True)


def test_gold_example_is_the_authoring_reference():
    report = observa.validate_strategy(observa.agent_example_path())
    check("gold example is structurally valid without smoke", report["valid"] is True,
          report.get("errors"))
    src = open(observa.agent_example_path(), encoding="utf-8").read()
    for token in ("def initialize", "def on_bar", "def teardown", "history",
                  '"signals"', '"drawings"', "position_id", '"sl"', '"reason"',
                  "observa.Config", "observa.run", "output="):
        check("gold example demonstrates %s" % token, token in src)
    check("gold example is small (<= 120 lines)", len(src.splitlines()) <= 120,
          len(src.splitlines()))


def test_legacy_bridge_divergence_is_explicit():
    """`crates/observa-python` is legacy/dev-only and its dicts diverge.

    OBS-AI-04 kept that bridge in place but made the divergence *explicit*: if
    its shape changes, this fails and forces a deliberate decision instead of a
    silent drift from the shipped contract.
    """
    if not _has_repo():
        check("repository present for legacy-bridge check (skipped: not a checkout)", True)
        return
    legacy = os.path.join(REPO, "crates", "observa-python", "src", "portfolio.rs")
    check("legacy bridge source is present", os.path.isfile(legacy))
    if not os.path.isfile(legacy):
        return
    import re

    src = open(legacy, encoding="utf-8").read()
    legacy_keys = set(re.findall(r'set_item\(\s*"([a-z_]+)"', src))

    spec = observa.agent_spec()
    canonical = set(spec["portfolio"]["keys"]) | set(spec["position"]["keys"])

    # Recorded 2026-09 (OBS-AI-04). Changing either set is a deliberate decision.
    expected_missing = {"used_margin", "free_margin", "position_id", "symbol",
                        "quantity", "unrealized_pnl", "stop_loss", "take_profit"}
    expected_extra = {"sl", "tp"}

    missing = canonical - legacy_keys
    extra = legacy_keys - canonical
    check("legacy bridge still lacks exactly the recorded canonical keys",
          missing == expected_missing, sorted(missing))
    check("legacy bridge still has exactly the recorded legacy-only keys",
          extra == expected_extra, sorted(extra))
    check("legacy bridge README documents the status",
          os.path.isfile(os.path.join(REPO, "crates", "observa-python", "README.md")))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback

            check("%s raised" % fn.__name__, False, "%s: %s" % (type(exc).__name__, exc))
            traceback.print_exc()
    total = len(PASSED) + len(FAILED)
    print()
    print("%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
