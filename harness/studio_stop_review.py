"""Browser regression for stopping stale Studio activity, without model calls.

Seeds an interrupted conversation with a real disposable subprocess and a dead
protocol reader. Exercises the production API and UI; never touches user data.
Run after building Studio: python harness/studio_stop_review.py --out /tmp/studio-stop
Requires the local Observa installation and Playwright Chromium.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright, expect

from observa.studio.app import create_app
from observa.studio.codex import Codex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--real-codex", action="store_true",
                        help="Also start and stop one real Codex turn using the configured account")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    errors, checks = [], []
    with tempfile.TemporaryDirectory(prefix="observa-stop-review-") as temp:
        root = Path(temp)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        app = create_app(root / "data", url)
        studio = app.state.studio
        studio.store.put("project", {"id": "p", "name": "Stop regression", "path": temp})
        lifecycle = app.router.lifespan_context
        loop = None
        process = None

        async def seed():
            nonlocal process
            studio.store.put("conversation", {"id": "c", "project": "p", "title": "Interrupted command",
                "status": "interrupted", "thread_id": "regression-thread", "turn_id": "stale-turn",
                "error": "Protocol reader failed"}, "p")
            studio.store.put("item", {"id": "command", "type": "commandExecution", "command": "Disposable test process",
                "status": "running", "aggregatedOutput": None}, "c")
            adapter = Codex(studio.store, "c", url)
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import time; time.sleep(120)", start_new_session=True)
            adapter.process = process
            adapter.owns_process_group = True
            adapter.reader = asyncio.create_task(asyncio.sleep(0))
            await adapter.reader
            studio.agents["c"] = adapter

        @asynccontextmanager
        async def lifespan(app):
            nonlocal loop
            async with lifecycle(app):
                loop = asyncio.get_running_loop()
                await seed()
                yield

        app.router.lifespan_context = lifespan
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=5))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.1)
            assert server.started
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get("OBSERVA_CHROMIUM"))
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url + "/#token=" + studio.token)
                page.locator(".conversation-list button").first.click()
                stop = page.get_by_role("button", name="Stop agent", exact=True)
                expect(stop).to_be_enabled()
                page.reload()
                expect(stop).to_be_enabled()
                assert process.returncode is None
                checks.append("stop remains available after refresh with interrupted conversation and live process")
                page.screenshot(path=str(args.out / "stop-before.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                page.reload()
                expect(stop).to_be_visible()
                assert page.evaluate("document.body.scrollWidth <= innerWidth")
                page.screenshot(path=str(args.out / "stop-mobile.png"))
                checks.append("stop remains visible without mobile overflow")
                page.set_viewport_size({"width": 1440, "height": 1000})
                stop.click()
                expect(stop).to_be_disabled()
                expect(stop).to_have_text("Stop agent", timeout=25000)
                expect(page.locator(".tool small", has_text="Interrupted")).to_be_visible()
                assert process.returncode is not None
                assert "c" not in studio.agents
                checks.append("browser stop terminates actual owned subprocess and settles tool activity")
                page.reload()
                expect(stop).to_be_disabled()
                expect(page.locator(".tool .spin")).to_have_count(0)
                snapshot = page.request.get(url + "/api/conversations/c").json()
                assert snapshot["conversation"]["status"] == "idle"
                assert snapshot["conversation"]["thread_id"] == "regression-thread"
                checks.append("stopped state and native thread reference survive refresh")
                page.screenshot(path=str(args.out / "stop-after.png"))

                # A browser transport failure must not be mistaken for a stop.
                asyncio.run_coroutine_threadsafe(seed(), loop).result(timeout=5)
                page.reload()
                expect(stop).to_be_enabled()
                page.wait_for_timeout(300)
                page.context.set_offline(True)
                stop.click()
                expect(page.get_by_role("alert")).to_contain_text("Stop could not be confirmed")
                expect(stop).to_be_enabled()
                assert process.returncode is None
                expect(page.get_by_role("button", name="Send message", exact=True)).to_have_count(0)
                checks.append("unreachable stop reports failure and does not claim the process stopped")
                page.context.set_offline(False)
                page.reload()
                expect(stop).to_be_enabled()
                stop.click()
                expect(stop).to_be_disabled()
                expect(stop).to_have_text("Stop agent", timeout=25000)
                assert process.returncode is not None
                checks.append("stop succeeds after reconnecting")
                if args.real_codex:
                    response = page.request.post(url + "/api/conversations", data={"project": "p"},
                                                 headers={"X-Observa-Request": "1"})
                    assert response.ok, response.text()
                    native_id = response.json()["id"]
                    page.reload()
                    page.locator(".conversation-list button", has_text="New research").click()
                    page.get_by_label("Message Codex").fill(
                        "Explain moving-average research assumptions in detail. Do not run tools, edit files, "
                        "or execute backtests. This turn will be stopped to verify Studio cancellation.")
                    page.get_by_role("button", name="Send message", exact=True).click()
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        native = page.request.get(url + "/api/conversations/" + native_id).json()
                        conv = native["conversation"]
                        if conv.get("status") == "running" and conv.get("turn_id"):
                            break
                        if conv.get("status") == "error":
                            raise AssertionError(conv.get("error"))
                        page.wait_for_timeout(100)
                    else:
                        raise AssertionError("Native Codex did not start a turn")
                    native_process = studio.agents[native_id].process
                    expect(stop).to_be_enabled()
                    stop.click()
                    expect(stop).to_be_disabled(timeout=25000)
                    expect(stop).to_have_text("Stop agent", timeout=25000)
                    native = page.request.get(url + "/api/conversations/" + native_id).json()
                    assert native_process.returncode is not None
                    assert native_id not in studio.agents
                    assert native["conversation"]["status"] == "idle"
                    assert native["conversation"]["thread_id"] == conv["thread_id"]
                    assert native["conversation"]["turn_id"] is None
                    assert not native["experiments"]
                    checks.append("browser stops real Codex turn and reaps App Server while retaining native thread")
                assert not errors, errors
                browser.close()
        finally:
            studio.shutting_down = True
            server.should_exit = True
            thread.join(timeout=15)
            sock.close()
            assert not thread.is_alive(), "Fixture server failed to shut down"
    evidence = {"checks": checks, "browser_errors": errors, "real_codex_turn_started": args.real_codex}
    (args.out / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
