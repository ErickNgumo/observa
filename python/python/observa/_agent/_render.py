"""Regenerates the bundled ``spec.json`` from the canonical contract.

Maintainer/CI helper — never run at import time::

    python -m observa._agent._render            # write spec.json
    python -m observa._agent._render --check    # exit 1 if it is stale

``CONTRACT`` is the only authority. ``spec.json`` is a rendered artefact; if the
two disagree, the contract is right and the JSON is stale.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .contract import render_spec

#: Command that regenerates the REPOSITORY source spec, runnable from the
#: repository root. Without ``--out`` the renderer would overwrite the copy
#: inside the installed package and leave the repository source stale (OBS-AI-04
#: QA finding L1). Asserted by python/tests/test_agent_contract.py.
SPEC_REGENERATE_HINT = (
    "python -m observa._agent._render "
    "--out python/python/observa/_agent/spec.json"
)


def _version() -> str:
    from .. import __version__

    return __version__


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    doc = None
    for flag in ("--doc", "--llms-full"):  # --llms-full kept as an alias
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print("%s requires a path" % flag, file=sys.stderr)
                return 2
            doc = Path(args[i + 1])
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out requires a path", file=sys.stderr)
            return 2
        out = Path(args[i + 1])

    version = _version()

    if doc is not None:
        from . import _generate

        if check:
            text = doc.read_text(encoding="utf-8")
            stale = [
                name for name in _generate.BLOCK_NAMES
                if _generate.find_block(text, name)
                != _generate.render_block(name, version)
            ]
            if stale:
                print(
                    "stale generated block(s) in %s: %s — regenerate with "
                    "`python -m observa._agent._render --llms-full %s`"
                    % (doc, ", ".join(stale), doc),
                    file=sys.stderr,
                )
                return 1
            print("generated blocks are up to date", file=sys.stderr)
            return 0
        text = doc.read_text(encoding="utf-8")
        doc.write_text(_generate.splice(text, version), encoding="utf-8")
        print("spliced generated blocks into %s" % doc, file=sys.stderr)
        return 0

    target = out if out is not None else (Path(__file__).resolve().parent / "spec.json")
    rendered = render_spec(version)
    if check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != rendered:
            print(
                "spec.json is stale: regenerate the repository source file from the "
                "repository root with\n"
                "  %s\n"
                "(without --out the renderer would overwrite the copy inside the "
                "installed package, leaving the source stale)" % SPEC_REGENERATE_HINT,
                file=sys.stderr,
            )
            return 1
        print("spec.json is up to date", file=sys.stderr)
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    print("wrote %s" % target, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
