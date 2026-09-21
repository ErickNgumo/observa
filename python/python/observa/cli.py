"""Console entry point for the installed ``observa`` package.

Commands::

    observa replay <run-dir> [--port <port>]
    observa mcp --runs-dir <path>
    observa agent-spec [--json] [--out <file>]
    observa validate-strategy <file> [--class <name>] [--json] [--smoke]

``replay`` serves a persisted canonical run created with
``observa.run(..., output=...)``. Without ``--port`` a free port is chosen
automatically; ``--port N`` is strict (a busy port exits with a concise error
and status 2).

``mcp`` runs the read-only MCP server (run inspection + strategy-authoring
discovery) over stdio. MCP support is part of the standard Observa install, so
no extra is needed; the dependency is still imported **lazily**, so neither
``import observa`` nor the other commands initialize it. No repository, Cargo,
or Rust toolchain is needed for any command.

``agent-spec`` prints the canonical machine-readable strategy authoring contract
(OBS-AI-04) and ``validate-strategy`` validates a strategy file before it is run.

Machine-readable modes print **JSON only** on stdout; every diagnostic goes to
stderr, so an agent can pipe stdout straight into a JSON parser.

Exit codes for ``validate-strategy``: 0 valid, 1 invalid strategy, 2 usage or
setup error.
"""

from __future__ import annotations

import json
import sys

USAGE = (
    "usage: observa <command> [options]\n"
    "commands:\n"
    "  replay <run-dir> [--port <port>]   replay a persisted canonical run\n"
    "  mcp --runs-dir <path>              read-only MCP inspection server (stdio)\n"
    "  agent-spec [--json] [--out FILE]   print the strategy authoring contract\n"
    "  validate-strategy FILE [--class NAME] [--json] [--smoke]\n"
    "                                     validate a strategy before running it\n"
    "run 'observa mcp --help' for MCP options"
)

MCP_HINT = (
    "error: MCP support is included with Observa, but its dependency could not "
    "be loaded.\n"
    "hint: this installation looks incomplete. Reinstall the official Observa "
    "release —\n"
    "      one install provides replay, strategy validation and MCP support.\n"
    "      See the install instructions in README.md (official GitHub Release "
    "wheel).\n"
    "      Do not run `pip install observa`; that PyPI project is unrelated."
)

#: Backwards-compatible alias for the pre-0.1.5 name of this message.
MCP_EXTRA_HINT = MCP_HINT

#: Help for the ``replay`` subcommand (printed to stderr, like the other
#: subcommands, so stdout stays clean for machine-readable modes).
REPLAY_USAGE = (
    "usage: observa replay <run-dir> [--port <port>]\n"
    "  <run-dir>   a persisted run created with observa.run(..., output=...)\n"
    "  --port N    bind a specific port (strict: a busy port exits 2).\n"
    "              Omitted, a free port is chosen and printed."
)

#: Trust boundary for `validate-strategy`. Kept in one place so the CLI help and
#: the machine-readable contract cannot drift apart (asserted by
#: python/tests/test_agent_contract.py).
VALIDATION_SECURITY_HELP = (
    "Security: validation is NOT sandboxed. Tier B imports the strategy module\n"
    "          (top-level Python code may execute); Tier C executes on_bar()\n"
    "          through the real Observa Engine. Only validate code you trust."
)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    command = args.pop(0)
    if command == "mcp":
        return _mcp(args)
    if command == "agent-spec":
        return _agent_spec(args)
    if command == "validate-strategy":
        return _validate_strategy(args)
    if command != "replay":
        print("unknown command '%s' — %s" % (command, USAGE), file=sys.stderr)
        return 2

    if any(a in ("-h", "--help") for a in args):
        print(REPLAY_USAGE, file=sys.stderr)
        return 0

    run_dir = None
    port = None  # None => automatic free port
    i = 0
    while i < len(args):
        if args[i] in ("--dir", "-d"):
            i += 1
            if i < len(args):
                run_dir = args[i]
        elif args[i] in ("--port", "-p"):
            i += 1
            if i >= len(args):
                print("error: --port requires a value — %s" % USAGE, file=sys.stderr)
                return 2
            try:
                port = int(args[i])
            except ValueError:
                print("invalid port '%s' — %s" % (args[i], USAGE), file=sys.stderr)
                return 2
        elif run_dir is None and not args[i].startswith("-"):
            run_dir = args[i]
        else:
            print("unknown argument '%s' — %s" % (args[i], USAGE), file=sys.stderr)
            return 2
        i += 1

    if not run_dir:
        print("error: a run directory is required — %s" % USAGE, file=sys.stderr)
        return 2

    if port is not None and not (0 < port < 65536):
        print("error: port must be between 1 and 65535, got %d" % port, file=sys.stderr)
        return 2

    from .replay import serve

    try:
        serve(run_dir, port=port, block=True)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # concise, coded errors for normal CLI use
        code = getattr(exc, "code", None)
        details = getattr(exc, "details", {}) or {}
        message = str(exc)
        if code == "REPLAY_PORT_IN_USE":
            print(
                "error: %s\nhint: omit --port to choose a free port automatically, "
                "or pass a different --port." % message,
                file=sys.stderr,
            )
        elif details:
            print("error: %s [%s %s]" % (message, code, details), file=sys.stderr)
        else:
            print("error: %s" % message, file=sys.stderr)
        return 2
    return 0


def _mcp(args) -> int:
    """Runs the read-only MCP server, importing it only for this branch.

    Keeping the import here is what keeps ``import observa`` (and the other
    commands) from initializing MCP: MCP is a normal dependency of the wheel,
    but nothing about ordinary backtesting should touch it.
    """
    try:
        from .mcp_server import main as mcp_main
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "mcp":
            print(MCP_HINT, file=sys.stderr)
            return 2
        raise
    return mcp_main(args)


def _agent_spec(args) -> int:
    """Prints the canonical strategy authoring contract (JSON)."""
    from ._agent.contract import render_spec

    out_path = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--json", "-j"):
            pass  # the default output is already JSON
        elif arg == "--out":
            i += 1
            if i >= len(args):
                print("error: --out requires a path — %s" % USAGE, file=sys.stderr)
                return 2
            out_path = args[i]
        elif arg in ("-h", "--help"):
            print(
                "usage: observa agent-spec [--json] [--out FILE]\n"
                "Prints the canonical machine-readable strategy authoring contract "
                "(strategy_api_version).",
                file=sys.stderr,
            )
            return 0
        else:
            print("unknown argument '%s' — %s" % (arg, USAGE), file=sys.stderr)
            return 2
        i += 1

    from . import __version__

    text = render_spec(__version__)
    if out_path is not None:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print("error: cannot write %s: %s" % (out_path, exc), file=sys.stderr)
            return 2
        print("wrote %s" % out_path, file=sys.stderr)
        return 0
    sys.stdout.write(text)
    return 0


def _human_report(report) -> str:
    lines = []
    status = "VALID" if report["valid"] else "INVALID"
    lines.append("%s  %s%s" % (
        status,
        report.get("file") or "<class>",
        (" :: %s" % report["class"]) if report.get("class") else "",
    ))
    lines.append("tiers run: %s" % ", ".join(report.get("tiers_run") or []))
    for entry in report.get("errors", []):
        lines.append("")
        lines.append("error [%s] %s" % (entry.get("code"), entry.get("path") or ""))
        if entry.get("message"):
            lines.append("  %s" % entry["message"])
        for key in ("received", "expected", "allowed", "line"):
            if key in entry:
                lines.append("  %s: %s" % (key, json.dumps(entry[key])))
    for entry in report.get("warnings", []):
        lines.append("")
        lines.append("warning [%s] %s" % (entry.get("code"), entry.get("path") or ""))
        if entry.get("message"):
            lines.append("  %s" % entry["message"])
    smoke = report.get("smoke")
    if smoke:
        lines.append("")
        lines.append(
            "smoke: %d bar(s), %d on_bar call(s), %d signal(s) observed"
            % (smoke["bars"], smoke["on_bar_calls"], smoke["signals_observed"])
        )
        lines.append("  %s" % smoke["note"])
    return "\n".join(lines)


def _validate_strategy(args) -> int:
    from . import validate_strategy

    path = None
    class_name = None
    as_json = False
    smoke = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--class":
            i += 1
            if i >= len(args):
                print("error: --class requires a name — %s" % USAGE, file=sys.stderr)
                return 2
            class_name = args[i]
        elif arg in ("--json", "-j"):
            as_json = True
        elif arg == "--smoke":
            smoke = True
        elif arg in ("-h", "--help"):
            print(
                "usage: observa validate-strategy FILE [--class NAME] [--json] [--smoke]\n"
                "exit codes: 0 valid, 1 invalid strategy, 2 usage/setup error\n"
                + VALIDATION_SECURITY_HELP,
                file=sys.stderr,
            )
            return 0
        elif path is None and not arg.startswith("-"):
            path = arg
        else:
            print("unknown argument '%s' — %s" % (arg, USAGE), file=sys.stderr)
            return 2
        i += 1

    if not path:
        print("error: a strategy file is required — %s" % USAGE, file=sys.stderr)
        return 2

    try:
        report = validate_strategy(path, class_name=class_name, smoke=smoke)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - setup problems are exit 2
        print("error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2

    if as_json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        print(_human_report(report))
    return 0 if report["valid"] else 1
