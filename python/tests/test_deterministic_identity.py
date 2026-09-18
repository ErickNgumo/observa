"""OBS-DET-01 — deterministic economic object identity (installed wheel).

Run against an installed Observa wheel:

    python python/tests/test_deterministic_identity.py

Covers the deterministic position-identity contract end-to-end:

* identical inputs produce byte-identical ``events.jsonl`` / ``run.json`` /
  ``metrics.json`` — with no position-id normalization;
* position ids are UUIDv5 values derived from the run-local position ordinal,
  identical across runs, and unique within a run;
* explicit ticket closes still resolve the exact position through the id;
* historical UUIDv4 runs still load (and the loader is genuinely strict).

See ``docs/ARCHITECTURE.md`` and ``llms-full.txt`` for the documented contract.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid

import observa
from observa import _observa
from observa.samples.sample_strategy import SampleEma

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_canonical_baseline as tb  # noqa: E402

# Frozen namespace: must match OBSERVA_POSITION_NAMESPACE in
# crates/observa-portfolio/src/portfolio.rs.
NS = uuid.UUID("8983c16f-8d9d-5d2f-87f2-3f02294b00e9")

PASSED, FAILED = [], []


def check(label, ok, detail=""):
    (PASSED if ok else FAILED).append(label)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def events_of(run_dir):
    with open(os.path.join(run_dir, "events.jsonl")) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def position_ids(events):
    return [e["position_id"] for e in events if "position_id" in e]


def cfg():
    return observa.Config(dataset_source=tb.FIXTURE, **tb.CANONICAL)


class HedgeAndCloseExact:
    """bar0 buy A, bar1 sell B (hedge), then close A by its exact ticket."""

    def __init__(self):
        self.n = 0
        self.done = False

    def initialize(self, params=None):
        pass

    def on_bar(self, bar, portfolio, history):
        i = self.n
        self.n += 1
        if i == 0:
            return {"signals": [{"direction": "buy", "size": 1.0, "reason": "A"}]}
        if i == 1:
            return {"signals": [{"direction": "sell", "size": 1.0, "reason": "B"}]}
        if not self.done and portfolio["open_positions"]:
            # Exact-ticket close of the FIRST position (A), never FIFO-guessed.
            ticket = portfolio["open_positions"][0]["position_id"]
            self.done = True
            return {"signals": [{"direction": "close", "size": 1.0,
                                 "ticket": ticket, "reason": "close A"}]}
        return {"signals": []}

    def teardown(self):
        pass


def main():
    tmp = tempfile.mkdtemp(prefix="qa-det-")
    try:
        # ── 1-3. byte-identical artifacts across identical runs ─────────────
        a = os.path.join(tmp, "run_a")
        b = os.path.join(tmp, "run_b")
        observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=a)
        observa.run(SampleEma(), tb.FIXTURE, config=cfg(), output=b)

        for name in ("events.jsonl", "run.json", "metrics.json"):
            same = sha(os.path.join(a, name)) == sha(os.path.join(b, name))
            check("%s is byte-identical across identical runs" % name, same,
                  {"a": sha(os.path.join(a, name))[:16], "b": sha(os.path.join(b, name))[:16]})

        ea, eb = events_of(a), events_of(b)
        check("event count is unchanged", len(ea) == len(eb) == 4862, len(ea))
        check("canonical history is identical in full (no field stripped)",
              ea == eb)

        # ── 4-5. ids identical across runs, UUIDv5, ordinal-derived ─────────
        ida, idb = position_ids(ea), position_ids(eb)
        check("position ids are identical across runs", ida == idb and len(ida) == 95, len(ida))
        check("every new position id is UUIDv5",
              all(uuid.UUID(i).version == 5 for i in ida),
              sorted({uuid.UUID(i).version for i in ida}))
        opened = [e["position_id"] for e in ea if e["type"] == "position_opened"]
        check("first opened position is ordinal 1 (UUIDv5(NS, 1))",
              opened[0] == str(uuid.uuid5(NS, "1")), opened[:1])
        check("ids follow UUIDv5(namespace, ordinal) in open order",
              all(pid == str(uuid.uuid5(NS, str(i + 1))) for i, pid in enumerate(opened)),
              opened[:3])
        check("ids are unique within a run", len(set(opened)) == len(opened), len(opened))
        check("a closed position reuses the id it was opened with",
              all(e["position_id"] in opened for e in ea if e["type"] == "position_closed"))

        # ── 12. persisted replay parity ─────────────────────────────────────
        pa = _observa.replay_payload(a)
        pb = _observa.replay_payload(b)
        check("replay payload is identical across runs", pa == pb)
        check("replay payload carries the deterministic ids",
              position_ids(pa["events"]) == ida)

        # ── 14. no economics change ─────────────────────────────────────────
        res = observa.run(SampleEma(), tb.FIXTURE, config=cfg())
        check("canonical economics unchanged (trades/fills/open)",
              (len(res.trades), len(res.orders), len(res.fills), res.open_positions)
              == (tb.EXPECTED["trades"], tb.EXPECTED["orders"], tb.EXPECTED["fills"],
                  tb.EXPECTED["open_positions"]),
              (len(res.trades), len(res.orders), len(res.fills), res.open_positions))
        check("final balance/equity unchanged",
              tb._close(tb.EXPECTED["final_balance"], res.final_balance)
              and tb._close(tb.EXPECTED["final_equity"], res.final_equity),
              (res.final_balance, res.final_equity))
        check("metrics digest unchanged", tb._digest(res.metrics) == tb.EXPECTED_METRICS_DIGEST,
              tb._digest(res.metrics))

        # ── 6-8. hedging + exact ticket close, deterministic ────────────────
        h1 = os.path.join(tmp, "hedge1")
        h2 = os.path.join(tmp, "hedge2")
        r1 = observa.run(HedgeAndCloseExact(), tb.FIXTURE, config=cfg(), output=h1)
        r2 = observa.run(HedgeAndCloseExact(), tb.FIXTURE, config=cfg(), output=h2)
        check("exact-ticket close closed exactly one trade", len(r1.trades) == 1, len(r1.trades))
        check("one hedged position remains open", r1.open_positions == 1, r1.open_positions)
        closed_id = r1.trades[0]["position_id"]
        check("the closed trade carries the deterministic ordinal-1 id",
              closed_id == str(uuid.uuid5(NS, "1")), closed_id)
        check("hedged run is repeatable", (len(r2.trades), r2.open_positions)
              == (len(r1.trades), r1.open_positions))
        check("hedged run artifacts are byte-identical",
              sha(os.path.join(h1, "events.jsonl")) == sha(os.path.join(h2, "events.jsonl")))
        check("no close order was rejected (the ticket parsed as a UUID)",
              not [e for e in events_of(h1) if e["type"] == "order_rejected"],
              [e for e in events_of(h1) if e["type"] == "order_rejected"][:1])

        # ── 6b. OBS-SCHEMA-02: the hedge close links its exact order ────────
        hedge_run = observa.inspect_run(h1)
        lifecycle = hedge_run.position(closed_id)
        closer = lifecycle["closing_order"]
        check("the hedged close records its canonical closing order",
              closer is not None and isinstance(closer["order_seq"], int),
              closer and closer.get("order_seq"))
        check("the closing order is distinct from the opening order",
              closer["order_seq"] != lifecycle["opening_order"]["order_seq"],
              (closer["order_seq"], lifecycle["opening_order"]["order_seq"]))
        check("the closing order resolves back to the closed position",
              hedge_run.order(closer["order_seq"])["position_id"] == closed_id)
        check("the still-open hedge leg has no closing order",
              all(p["closing_order_seq"] is None
                  for p in hedge_run.positions(open=True)))
        check("the positional close event carries the linkage",
              lifecycle["closed"]["order_seq"] == closer["order_seq"])
        check("closing-order linkage is identical across repeated hedged runs",
              observa.inspect_run(h2).position(closed_id)["closing_order"]
              == closer)

        # ── 13. historical UUIDv4 runs still load ───────────────────────────
        legacy = os.path.join(tmp, "legacy")
        shutil.copytree(a, legacy)
        mapping = {}
        for pid in set(position_ids(ea)):
            mapping[pid] = str(uuid.uuid4())  # a genuine old-style v4 id
        lines = []
        with open(os.path.join(a, "events.jsonl")) as fh:
            for line in fh:
                e = json.loads(line)
                if isinstance(e, dict) and e.get("position_id") in mapping:
                    e["position_id"] = mapping[e["position_id"]]
                    line = json.dumps(e) + "\n"
                lines.append(line)
        with open(os.path.join(legacy, "events.jsonl"), "w") as fh:
            fh.writelines(lines)
        lp = _observa.replay_payload(legacy)
        check("a historical UUIDv4 run still loads", lp is not None and len(lp["events"]) > 0)
        check("historical v4 ids survive loading unchanged",
              set(position_ids(lp["events"])) == set(mapping.values()),
              sorted(set(position_ids(lp["events"])))[:2])
        check("historical ids keep UUID version 4",
              all(uuid.UUID(i).version == 4 for i in position_ids(lp["events"])))

        # negative control: the loader really does validate the id shape, so the
        # positive result above is meaningful rather than vacuous.
        broken = os.path.join(tmp, "broken")
        shutil.copytree(a, broken)
        with open(os.path.join(broken, "events.jsonl")) as fh:
            raw = fh.read()
        raw = raw.replace(opened[0], "not-a-uuid", 1)
        with open(os.path.join(broken, "events.jsonl"), "w") as fh:
            fh.write(raw)
        try:
            _observa.replay_payload(broken)
            rejected = False
        except Exception:  # noqa: BLE001 - QA probe
            rejected = True
        check("a malformed position id is rejected (loader is strict)", rejected)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print("  -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
