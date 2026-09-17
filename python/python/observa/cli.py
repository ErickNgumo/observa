"""Console entry point for the installed ``observa`` package.

Primary command::

    observa replay <run-dir> [--port <port>]

Replays a persisted canonical run created with ``observa.run(..., output=...)``.
Without ``--port`` a free port is chosen automatically; ``--port N`` is strict
(a busy port exits with a concise error and status 2). No repository, Cargo,
or Rust toolchain is required.
"""

from __future__ import annotations

import sys

USAGE = "usage: observa replay <run-dir> [--port <port>]"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    command = args.pop(0)
    if command != "replay":
        print("unknown command '%s' — %s" % (command, USAGE), file=sys.stderr)
        return 2

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
