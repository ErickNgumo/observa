#!/usr/bin/env python
"""Execution/accounting invariance check for the metrics-schema-2 change.

Runs the metrics golden scenarios (those valid on both builds: no
bars_per_year argument) with whichever interpreter executes it, then compares
two output trees.

    <rel-0.1.6-python> metrics_cross_wheel.py run OUT_REL
    <fixed-python>     metrics_cross_wheel.py run OUT_FIX
    python             metrics_cross_wheel.py compare OUT_REL OUT_FIX

Compared per scenario:
  * events.jsonl must be byte-identical (canonical history = execution/accounting)
  * run.json: every key present in the 0.1.6 run.json must be equal in the
    fixed one; keys added/removed are listed (additive provenance is reported,
    not failed)
  * metrics.json: reported as changed (expected: schema 1 -> schema 2)
Exit 1 on any events.jsonl difference or changed pre-existing run.json value.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def run_all(out):
    import observa
    import metrics_golden as g
    os.makedirs(out)
    cases = [(n, g.Scripted(sc["script"]), sc["bars"], g.cfg(**sc["config"]))
             for n, sc in g.HAND.items()]
    cases += [(n, g.bh_strategy(), b, c) for n, b, c, kw, _ in g.ratio_scenarios() if not kw]
    for name, strat, bars, config in cases:
        try:
            observa.run(strat, bars, config=config, output=os.path.join(out, name))
        except Exception as exc:  # noqa: BLE001
            Path(out, name + ".error").write_text(f"{type(exc).__name__}: {exc}")
    print(f"wrote {len(cases)} cases to {out}")


def flat(d, p=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flat(v, f"{p}.{k}" if p else k))
    else:
        out[p] = d
    return out


def compare(a, b):
    fails = 0
    names = sorted({p.name for p in Path(a).iterdir()} | {p.name for p in Path(b).iterdir()})
    for n in names:
        pa, pb = Path(a, n), Path(b, n)
        if n.endswith(".error") or not (pa.is_dir() and pb.is_dir()):
            print(f"FAIL {n}: present/errored on only one side or errored "
                  f"({pa.exists()}, {pb.exists()})")
            fails += 1
            continue
        ea, eb = (pa / "events.jsonl").read_bytes(), (pb / "events.jsonl").read_bytes()
        same = ea == eb
        fails += not same
        print(f"{'PASS' if same else 'FAIL'} {n}: events.jsonl identical "
              f"({len(ea.splitlines())} events, sha256 {hashlib.sha256(ea).hexdigest()[:12]})")
        ra = flat(json.loads((pa / "run.json").read_text()))
        rb = flat(json.loads((pb / "run.json").read_text()))
        changed = [k for k in ra if k in rb and ra[k] != rb[k]]
        removed = [k for k in ra if k not in rb]
        added = [k for k in rb if k not in ra]
        bad = changed + removed
        fails += bool(bad)
        print(f"{'PASS' if not bad else 'FAIL'} {n}: run.json pre-existing keys equal; "
              f"changed={[(k, ra[k], rb[k]) for k in changed]} removed={removed} added={added}")
        ma, mb = (pa / "metrics.json").read_bytes(), (pb / "metrics.json").read_bytes()
        print(f"INFO {n}: metrics.json {'identical' if ma == mb else 'differs (expected: schema change)'}")
    print(f"\ncompare failures: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run_all(sys.argv[2])
    else:
        sys.exit(compare(sys.argv[2], sys.argv[3]))
