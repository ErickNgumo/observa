"""Console entry point for the installed ``observa`` package.

Primary command::

    observa replay <run-dir> [--port <port>]

replays a persisted canonical run created with ``observa.run(..., output=...)``.
No repository, Cargo, or Rust toolchain is required.
"""

from __future__ import annotations

import sys


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help", "help"):
        print("usage: observa replay <run-dir> [--port <port>]")
        return 0

    command = args.pop(0)
    if command != "replay":
        print("unknown command '%s' — usage: observa replay <run-dir> [--port <port>]" % command)
        return 2

    run_dir = None
    port = 7878
    i = 0
    while i < len(args):
        if args[i] in ("--dir", "-d"):
            i += 1
            if i < len(args):
                run_dir = args[i]
        elif args[i] in ("--port", "-p"):
            i += 1
            if i < len(args):
                try:
                    port = int(args[i])
                except ValueError:
                    print("invalid port '%s'" % args[i])
                    return 2
        elif run_dir is None and not args[i].startswith("-"):
            run_dir = args[i]
        else:
            print("unknown argument '%s'" % args[i])
            return 2
        i += 1

    if not run_dir:
        print("error: a run directory is required — usage: observa replay <run-dir> [--port <port>]")
        return 2

    import importlib

    replay_module = importlib.import_module("observa.replay")
    replay_module.serve(run_dir, port)
    return 0
