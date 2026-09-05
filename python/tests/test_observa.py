"""Observa Python API integration tests (dependency-free; run with `python3`).

Covers the OBS-0009 acceptance surface: import/version, config, MARKET/LIMIT/
STOP, SL/TP, parameters, explicit close, multiple/hedged positions, errors,
result/events/metrics access, persistence, DataFrame-like input, and config
validation. All economics are hand-derived exact-binary fixtures.
"""

import os
import shutil
import sys
import tempfile

import observa


def bars(*rows):
    return [
        {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": None}
        for (ts, o, h, l, c) in rows
    ]


def zero_cost(**kw):
    kw.setdefault("fill_mode", "bar_close")
    kw.setdefault("spread", 0.0)
    kw.setdefault("slippage", 0.0)
    kw.setdefault("commission", 0.0)
    kw.setdefault("commission_mode", "per_side")
    return observa.Config(**kw)


def test_import_and_version():
    assert observa.__version__ == "0.1.0"
    assert callable(observa.run)
    assert observa.Config().symbol == "EURUSD"


def test_market_known_answer():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.5, 1.5, 1.5, 1.5),
    )

    class S:
        def __init__(self):
            self.bought = False
            self.closed = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.bought:
                self.bought = True
                return [{"direction": "buy", "size": 1.0, "price": bar["close"]}]
            if not self.closed and portfolio["has_open_position"]:
                self.closed = True
                p = portfolio["open_positions"][0]
                return [{"direction": "close", "size": p["size"], "ticket": p["position_id"]}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost())
    assert abs(res.final_balance - 60_000.0) < 1e-9, res.final_balance
    assert abs(res.final_equity - 60_000.0) < 1e-9
    assert res.open_positions == 0
    assert len(res.trades) == 1 and res.trades[0]["net_realized_pnl"] == 50_000.0
    assert len(res.orders) == 2 and len(res.fills) == 2
    assert len(res.events) == 15
    assert res.events[0]["type"] == "run_started"
    assert res.events[-1]["type"] == "run_completed"


def test_events_are_dense_and_ordered():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": 1.0}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost())
    seqs = [e["event_seq"] for e in res.events]
    assert seqs == list(range(len(seqs))), "event_seq must be dense 0..n"
    types = [e["type"] for e in res.events]
    assert types[0] == "run_started" and types[-1] == "run_completed"


def test_next_bar_open_fills_on_next_bar():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.25, 1.5, 1.25, 1.5),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": 1.0}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost(fill_mode="next_bar_open"))
    # Created on bar 0, filled at bar 1 open (1.25), no spread/slippage.
    assert len(res.orders) == 1
    assert res.orders[0]["created_bar"] == 0 and res.orders[0]["filled_bar"] == 1
    assert res.fills[0]["executed_price"] == 1.25
    assert res.fills[0]["bar_index"] == 1


def test_limit_order_pending_then_fill():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 0.9, 0.95),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "order_type": "limit", "price": 0.95, "size": 1.0}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost(fill_mode="next_bar_open"))
    types = [e["type"] for e in res.events]
    assert "order_pending" in types and "order_triggered" in types
    assert len(res.fills) == 1 and res.fills[0]["reason"] == "LimitEntry"
    assert res.fills[0]["executed_price"] == 0.95


def test_stop_order_triggers():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.1, 0.95, 1.1),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "order_type": "stop", "price": 1.05, "size": 1.0}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost(fill_mode="next_bar_open"))
    assert len(res.fills) == 1 and res.fills[0]["reason"] == "StopEntry"
    assert res.fills[0]["executed_price"] == 1.05


def test_protective_levels_survive_into_position():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": 1.0, "sl": 0.9, "tp": 1.1}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost())
    opened = next(e for e in res.events if e["type"] == "position_opened")
    assert opened["stop_loss"] == 0.9 and opened["take_profit"] == 1.1


def test_parameters_are_forwarded():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def __init__(self):
            self.n = None
            self.sent = False

        def initialize(self, params=None):
            self.n = int(params.get("n", 0)) if params else 0

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": float(self.n)}]
            return []

        def teardown(self):
            pass

    r2 = observa.run(S(), data, config=zero_cost(params={"n": 2}))
    r5 = observa.run(S(), data, config=zero_cost(params={"n": 5}))
    assert r2.orders[0]["quantity_lots"] == 2.0
    assert r5.orders[0]["quantity_lots"] == 5.0
    assert r2.fills[0]["quantity_lots"] == 2.0
    assert r5.fills[0]["quantity_lots"] == 5.0


def test_explicit_close_and_hedged_positions():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:43:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def __init__(self):
            self.step = 0

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            self.step += 1
            if self.step == 1:
                return [{"direction": "buy", "size": 1.0}]
            if self.step == 2:
                return [{"direction": "sell", "size": 1.0}]
            if self.step == 3:
                # Close only the long position by explicit ticket.
                for p in portfolio["open_positions"]:
                    if p["direction"] == "Buy":
                        return [{"direction": "close", "size": p["size"], "ticket": p["position_id"]}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), data, config=zero_cost())
    assert res.open_positions == 1, "one (short) position must remain"
    assert len(res.trades) == 1
    assert res.trades[0]["direction"] == "Buy", "closed the long, kept the short"


def test_strategy_exception_propagates():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            raise ValueError("boom")

        def teardown(self):
            pass

    try:
        observa.run(S(), data, config=zero_cost())
        raise AssertionError("expected an exception")
    except RuntimeError as e:
        assert "boom" in str(e) or "on_bar" in str(e), str(e)


def test_config_validation_errors():
    data = bars(("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0))

    class S:
        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            return []

        def teardown(self):
            pass

    try:
        observa.run(S(), data, config=zero_cost(fill_mode="banana"))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "fill_mode" in str(e), str(e)

    try:
        observa.run(S(), data, config=zero_cost(leverage=0.0))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "leverage" in str(e), str(e)


def test_data_not_found_error():
    class S:
        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            return []

        def teardown(self):
            pass

    try:
        observa.run(S(), "/nonexistent/definitely-missing.csv", config=zero_cost())
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass


def test_dataframe_like_input():
    class FakeDF:
        columns = ["timestamp", "open", "high", "low", "close", "volume"]

        def to_dict(self, orient):
            return [
                {"timestamp": "2023-11-14T22:13:20Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": None},
                {"timestamp": "2023-11-14T22:28:20Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": None},
            ]

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": 1.0}]
            return []

        def teardown(self):
            pass

    res = observa.run(S(), FakeDF(), config=zero_cost())
    assert res.total_bars == 2 and len(res.orders) == 1


def test_persistence_and_no_overwrite():
    data = bars(
        ("2023-11-14T22:13:20Z", 1.0, 1.0, 1.0, 1.0),
        ("2023-11-14T22:28:20Z", 1.0, 1.0, 1.0, 1.0),
    )

    class S:
        def __init__(self):
            self.sent = False

        def initialize(self, params=None):
            pass

        def on_bar(self, bar, portfolio, history):
            if not self.sent:
                self.sent = True
                return [{"direction": "buy", "size": 1.0}]
            return []

        def teardown(self):
            pass

    tmp = tempfile.mkdtemp(prefix="observa-py-")
    try:
        out = os.path.join(tmp, "run")
        res = observa.run(S(), data, config=zero_cost(), output=out)
        assert res.artifact_dir == out
        assert os.path.isfile(os.path.join(out, "run.json"))
        assert os.path.isfile(os.path.join(out, "events.jsonl"))
        assert os.path.isfile(os.path.join(out, "metrics.json"))
        with open(os.path.join(out, "events.jsonl")) as f:
            lines = f.read().splitlines()
        assert len(lines) == len(res.events)
        # Second write must refuse (no silent overwrite).
        try:
            res.save(out)
            raise AssertionError("expected FileExistsError")
        except FileExistsError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback

            print(f"FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(ALL) - failed}/{len(ALL)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
