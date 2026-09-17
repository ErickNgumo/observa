"""OBS-AI-01 agent/notebook interface tests.

Run with the installed wheel (the tests spawn real replay servers on
127.0.0.1 and use only stdlib):

    python python/tests/test_ai_interface.py

Covers: free-port selection, concurrent servers, port collisions, server
lifecycle, result overload, structured summaries, persisted run summaries,
machine-readable error codes, rejection events (not exceptions), CLI
behavior, and notebook-style non-blocking usage. No economic behavior is
asserted beyond canonical equality with existing getters/artifacts.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import observa
from observa.samples.sample_strategy import SampleEma

PASSED = []
FAILED = []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print("PASS " + label)
    else:
        FAILED.append(label)
        print("FAIL " + label + (": " + str(detail) if detail else ""))


def _config(**overrides):
    values = dict(
        fill_mode=observa.BAR_CLOSE,
        spread=0.0002,
        slippage=0.0001,
        commission=0.0,
        dataset_source=observa.sample_data_path(),
    )
    values.update(overrides)
    return observa.Config(**values)


def _make_run(tmp, name="run"):
    run_dir = os.path.join(tmp, name)
    result = observa.run(SampleEma(), observa.sample_data_path(), config=_config(),
                         output=run_dir)
    return result, run_dir


def _get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, json.loads(response.read())


def _get_status(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status


def _expect_code(fn, code):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - test helper
        return getattr(exc, "code", None), exc
    return None, None


# ── A/B/C/D: replay server behavior ─────────────


def test_free_port_replay_payload():
    tmp = tempfile.mkdtemp(prefix="ai01-a-")
    try:
        result, run_dir = _make_run(tmp)
        server = observa.replay(result, block=False)
        check("A: non-blocking replay returns a handle", server is not None)
        check("A: server exposes url/port/run_dir", bool(server.url) and server.port > 0)
        check("A: url uses 127.0.0.1", server.url.startswith("http://127.0.0.1:"))
        check("A: is_running true", server.is_running is True)
        check("A: GET / == 200", _get_status(server.url + "/") == 200)
        status, payload = _get_json(server.url + "/api/replay")
        check("A: GET /api/replay == 200", status == 200)
        check("A: candles present", len(payload["bars"]) > 0, len(payload["bars"]))
        check("A: events present", len(payload["events"]) > 0, len(payload["events"]))
        check("A: status completed", payload["run"]["status"] == "completed")
        server.stop()
        check("A: is_running false after stop", server.is_running is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_two_servers_distinct_ports():
    tmp = tempfile.mkdtemp(prefix="ai01-b-")
    try:
        _, run_dir = _make_run(tmp)
        first = observa.replay(run_dir, block=False)
        second = observa.replay(run_dir, block=False)
        check("B: distinct automatic ports", first.port != second.port,
              "%s vs %s" % (first.port, second.port))
        check("B: both reachable",
              _get_status(first.url + "/") == 200 and _get_status(second.url + "/") == 200)
        first.stop()
        second.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_port_collision_is_coded():
    tmp = tempfile.mkdtemp(prefix="ai01-c-")
    listening = socket.socket()
    try:
        _, run_dir = _make_run(tmp)
        listening.bind(("127.0.0.1", 0))
        listening.listen(1)
        busy_port = listening.getsockname()[1]
        code, exc = _expect_code(lambda: observa.replay(run_dir, port=busy_port), "REPLAY_PORT_IN_USE")
        check("C: explicit busy port raises REPLAY_PORT_IN_USE", code == "REPLAY_PORT_IN_USE", code)
        check("C: exception class is OSError", isinstance(exc, OSError), type(exc).__name__)
        check("C: details carries the port",
              getattr(exc, "details", {}).get("port") == busy_port, getattr(exc, "details", None))
        check("C: message recommends port=None", "port=None" in str(exc), str(exc))
    finally:
        listening.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_lifecycle_and_reuse():
    tmp = tempfile.mkdtemp(prefix="ai01-d-")
    try:
        _, run_dir = _make_run(tmp)
        with observa.replay(run_dir, block=False) as server:
            check("D: context manager returns running server", server.is_running)
            port = server.port
        check("D: context exit stops server", server.is_running is False)
        server.stop()  # second stop must be a no-op
        check("D: double stop is safe", server.is_running is False)
        rebound = observa.replay(run_dir, port=port, block=False)
        check("D: strict port becomes reusable after stop", rebound.port == port)
        rebound.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_result_overload_and_unpersisted():
    tmp = tempfile.mkdtemp(prefix="ai01-e-")
    try:
        result, _ = _make_run(tmp)
        server = observa.replay(result, block=False)
        check("E: persisted RunResult accepted", server.is_running)
        server.stop()

        unpersisted = observa.run(SampleEma(), observa.sample_data_path(), config=_config())
        code, exc = _expect_code(lambda: observa.replay(unpersisted, block=False),
                                 "REPLAY_RUN_NOT_PERSISTED")
        check("E: unpersisted result -> REPLAY_RUN_NOT_PERSISTED",
              code == "REPLAY_RUN_NOT_PERSISTED", code)
        check("E: message mentions output=/save", "output=" in str(exc) and "save" in str(exc), str(exc))

        code2, _ = _expect_code(
            lambda: observa.replay(os.path.join(tmp, "does-not-exist"), block=False),
            "REPLAY_RUN_NOT_FOUND")
        check("E: missing run dir -> REPLAY_RUN_NOT_FOUND", code2 == "REPLAY_RUN_NOT_FOUND", code2)

        incomplete = os.path.join(tmp, "incomplete")
        os.makedirs(incomplete)
        with open(os.path.join(incomplete, "run.json"), "w") as fh:
            fh.write("{}")
        code3, _ = _expect_code(lambda: observa.replay(incomplete, block=False),
                                "REPLAY_ARTIFACTS_INVALID")
        check("E: missing events.jsonl -> REPLAY_ARTIFACTS_INVALID",
              code3 == "REPLAY_ARTIFACTS_INVALID", code3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── F/G/H/I: summaries, codes, rejections ───────


def test_result_summary():
    tmp = tempfile.mkdtemp(prefix="ai01-f-")
    try:
        result, run_dir = _make_run(tmp)
        summary = result.summary()
        expected = {
            "status", "artifact_dir", "total_bars", "trades", "open_positions",
            "final_balance", "final_equity", "events", "metrics",
            "dataset_source", "run_schema_version",
        }
        check("F: exact summary keys", set(summary) == expected, sorted(summary))
        check("F: status completed", summary["status"] == "completed")
        check("F: artifact_dir matches", summary["artifact_dir"] == run_dir)
        check("F: trades matches getter", summary["trades"] == len(result.trades))
        check("F: events matches getter", summary["events"] == len(result.events))
        check("F: balances match getters",
              summary["final_balance"] == result.final_balance
              and summary["final_equity"] == result.final_equity)
        check("F: open_positions matches getter",
              summary["open_positions"] == result.open_positions)
        check("F: metrics match getter", summary["metrics"] == result.metrics)
        check("F: no full arrays duplicated",
              "orders" not in summary and "fills" not in summary and "trades_list" not in summary)
        # metrics caching must not change values across calls
        check("F: metrics stable across calls", result.metrics == result.metrics == summary["metrics"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_summary_completed_failed_missing_malformed():
    tmp = tempfile.mkdtemp(prefix="ai01-g-")
    try:
        result, run_dir = _make_run(tmp)
        info = observa.run_summary(run_dir)
        check("G: completed status", info["status"] == "completed")
        check("G: total_bars from run.json", info["total_bars"] == 200, info["total_bars"])
        check("G: trades from metrics.json", info["trades"] == len(result.trades), info["trades"])
        check("G: events from run.json", info["events"] == len(result.events))
        check("G: balance/equity persisted",
              info["final_balance"] == result.final_balance
              and info["final_equity"] == result.final_equity)
        check("G: metrics included", isinstance(info["metrics"], dict))
        check("G: dataset_source included", info["dataset_source"] == observa.sample_data_path())

        class Boom:
            def initialize(self, params=None):
                pass

            def on_bar(self, bar, portfolio, history):
                raise RuntimeError("scripted failure")

            def teardown(self):
                pass

        failed_dir = os.path.join(tmp, "failed")
        code, _ = _expect_code(
            lambda: observa.run(Boom(), observa.sample_data_path(), config=_config(),
                                output=failed_dir),
            "STRATEGY_ERROR")
        check("G: failed run raised STRATEGY_ERROR", code == "STRATEGY_ERROR", code)
        failed = observa.run_summary(failed_dir)
        check("G: failed summary status failed", failed["status"] == "failed", failed["status"])
        check("G: failed error exposed", bool(failed["error"]), failed.get("error"))
        check("G: failed metrics absent", failed["metrics"] is None)
        check("G: failed trades None", failed["trades"] is None)

        code_missing, _ = _expect_code(
            lambda: observa.run_summary(os.path.join(tmp, "nope")), "RUN_DIR_NOT_FOUND")
        check("G: missing dir -> RUN_DIR_NOT_FOUND", code_missing == "RUN_DIR_NOT_FOUND", code_missing)

        bad = os.path.join(tmp, "bad")
        os.makedirs(bad)
        with open(os.path.join(bad, "run.json"), "w") as fh:
            fh.write("{not json")
        code_bad, _ = _expect_code(lambda: observa.run_summary(bad), "RUN_ARTIFACTS_INVALID")
        check("G: malformed run.json -> RUN_ARTIFACTS_INVALID",
              code_bad == "RUN_ARTIFACTS_INVALID", code_bad)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_error_codes():
    tmp = tempfile.mkdtemp(prefix="ai01-h-")
    try:
        result, run_dir = _make_run(tmp)
        code, exc = _expect_code(
            lambda: observa.run(SampleEma(), "/definitely/missing.csv", config=_config()),
            "DATA_FILE_NOT_FOUND")
        check("H: missing data -> DATA_FILE_NOT_FOUND", code == "DATA_FILE_NOT_FOUND", code)
        check("H: missing data class FileNotFoundError", isinstance(exc, FileNotFoundError))
        check("H: missing data details path", exc.details.get("path") == "/definitely/missing.csv")

        code2, _ = _expect_code(
            lambda: observa.run(SampleEma(), observa.sample_data_path(),
                                config=observa.Config(fill_mode="banana")),
            "CONFIG_INVALID")
        check("H: invalid config -> CONFIG_INVALID", code2 == "CONFIG_INVALID", code2)

        code3, exc3 = _expect_code(
            lambda: observa.run(SampleEma(), observa.sample_data_path(),
                                config=_config(), output=run_dir),
            "RUN_OUTPUT_EXISTS")
        check("H: existing output -> RUN_OUTPUT_EXISTS", code3 == "RUN_OUTPUT_EXISTS", code3)
        check("H: existing output class FileExistsError", isinstance(exc3, FileExistsError))
        check("H: existing output details path", exc3.details.get("path") == run_dir)

        class Boom:
            def initialize(self, params=None):
                pass

            def on_bar(self, bar, portfolio, history):
                raise ValueError("kaboom")

            def teardown(self):
                pass

        code4, exc4 = _expect_code(
            lambda: observa.run(Boom(), observa.sample_data_path(), config=_config()),
            "STRATEGY_ERROR")
        check("H: strategy exception -> STRATEGY_ERROR", code4 == "STRATEGY_ERROR", code4)
        check("H: strategy details message/bar_index",
              "kaboom" in exc4.details.get("message", "")
              and exc4.details.get("bar_index") == 0, exc4.details)

        code5, _ = _expect_code(lambda: observa.replay(run_dir, port=70000), "REPLAY_PORT_INVALID")
        check("H: invalid port -> REPLAY_PORT_INVALID", code5 == "REPLAY_PORT_INVALID", code5)
        check("H: error_code() helper", observa.error_code(exc4) == "STRATEGY_ERROR")
        check("H: error_code() on plain exception is None",
              observa.error_code(ValueError("x")) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rejections_are_events_not_exceptions():
    tmp = tempfile.mkdtemp(prefix="ai01-i-")
    try:
        run_dir = os.path.join(tmp, "run")
        # size 1000 lots exceeds the instrument max (100) -> canonical rejection
        class Oversize:
            def __init__(self):
                self.sent = False

            def initialize(self, params=None):
                pass

            def on_bar(self, bar, portfolio, history):
                if not self.sent:
                    self.sent = True
                    return [{"direction": "buy", "size": 1000.0}]
                return []

            def teardown(self):
                pass

        result = observa.run(Oversize(), observa.sample_data_path(), config=_config(),
                             output=run_dir)
        rejected = [e for e in result.events if e.get("type") == "order_rejected"]
        check("I: oversize order produced order_rejected event", len(rejected) == 1, len(rejected))
        check("I: rejection has canonical category/reason",
              rejected and rejected[0].get("category") == "execution_domain"
              and bool(rejected[0].get("reason")), rejected[:1])
        check("I: no exception was raised", True)
        check("I: no fills occurred", len(result.fills) == 0, len(result.fills))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── J: CLI compatibility ────────────────────────


def _cli_path():
    candidate = os.path.join(os.path.dirname(sys.executable), "observa")
    return candidate if os.path.exists(candidate) else None


def test_cli_auto_and_busy_port():
    cli = _cli_path()
    if not cli:
        check("J: CLI available in this environment", False, "observa console script not found")
        return
    tmp = tempfile.mkdtemp(prefix="ai01-j-")
    try:
        _, run_dir = _make_run(tmp)
        proc = subprocess.Popen([cli, "replay", run_dir], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        url = None
        deadline = time.time() + 15
        try:
            while time.time() < deadline:
                line = proc.stdout.readline()
                if "http://127.0.0.1:" in line:
                    url = line.strip().split("http://")[1].split(" ")[0]
                    url = "http://" + url
                    break
                if proc.poll() is not None and not line:
                    break
            check("J: CLI default binds an automatic port and prints URL", bool(url), url)
            if url:
                check("J: CLI auto-port serves /api/replay", _get_status(url + "/api/replay") == 200)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        holding = socket.socket()
        holding.bind(("127.0.0.1", 0))
        holding.listen(1)
        busy_port = holding.getsockname()[1]
        try:
            done = subprocess.run([cli, "replay", run_dir, "--port", str(busy_port)],
                                  capture_output=True, text=True, timeout=30)
            check("J: busy explicit port exits non-zero", done.returncode != 0, done.returncode)
            check("J: busy explicit port message mentions in use",
                  "in use" in (done.stderr + done.stdout).lower(), done.stderr[:200])
            check("J: no traceback for busy port", "Traceback" not in done.stderr, done.stderr[:200])
            check("J: busy port suggests omitting --port",
                  "--port" in (done.stderr + done.stdout), done.stderr[:200])
        finally:
            holding.close()

        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        free_port = free.getsockname()[1]
        free.close()
        proc2 = subprocess.Popen([cli, "replay", run_dir, "--port", str(free_port)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            served = False
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    if _get_status("http://127.0.0.1:%d/" % free_port) == 200:
                        served = True
                        break
                except Exception:
                    time.sleep(0.2)
            check("J: explicit free port works", served)
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc2.kill()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── K: notebook-style lifecycle ─────────────────


def test_notebook_style_non_blocking():
    tmp = tempfile.mkdtemp(prefix="ai01-k-")
    try:
        result, _ = _make_run(tmp)
        started = time.time()
        replay = observa.replay(result, block=False)
        elapsed = time.time() - started
        check("K: replay() returns immediately", elapsed < 2.0, "%.3fs" % elapsed)
        summary = result.summary()
        check("K: notebook can continue working after replay start", summary["status"] == "completed")
        check("K: replay url available", _get_status(replay.url + "/") == 200)
        replay.stop()
        check("K: replay.stop() cleans up", replay.is_running is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [
        test_free_port_replay_payload,
        test_two_servers_distinct_ports,
        test_port_collision_is_coded,
        test_lifecycle_and_reuse,
        test_result_overload_and_unpersisted,
        test_result_summary,
        test_run_summary_completed_failed_missing_malformed,
        test_error_codes,
        test_rejections_are_events_not_exceptions,
        test_cli_auto_and_busy_port,
        test_notebook_style_non_blocking,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - keep other tests running
            import traceback

            FAILED.append(test.__name__)
            print("FAIL %s (unexpected): %s" % (test.__name__, exc))
            traceback.print_exc()
    print("\n%d checks passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
