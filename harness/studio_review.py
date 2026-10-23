"""Opt-in, real Codex + browser Studio acceptance test (no agent mocks).

python harness/studio_review.py --real-codex --out /tmp/observa-studio-review

Requires built Studio assets, the installed local Observa package, Playwright
Chromium, bubblewrap and an authenticated Codex CLI. Uses the configured Codex
account. Approves only this test's strategy.py edits and scoped Studio tools;
unexpected shell/permission requests fail the test. Saves screenshots and evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-codex", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review-existing", action="store_true",
                        help="Review a completed run already in --out, then verify real thread resume")
    args = parser.parse_args()
    if not args.real_codex:
        parser.error("Pass --real-codex to authorize real model calls and the controlled test approvals.")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.chmod(0o700)
    project = out / "project"
    project.mkdir(exist_ok=True)
    checks, errors = [], []
    process = None
    log_handle = None

    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
        print("PASS", label, flush=True)

    def start():
        nonlocal process, log_handle
        log_handle = (out / "server.log").open("w")
        process = subprocess.Popen([
            sys.executable, "-c", "from observa.cli import main; raise SystemExit(main())",
            "studio", "--no-browser", "--data-dir", str(out / "data"),
        ], stdout=log_handle, stderr=subprocess.STDOUT)
        for _ in range(100):
            content = (out / "server.log").read_text()
            match = re.search(r"Open: (http://127\.0\.0\.1:\d+/\#token=\S+)", content)
            if match:
                return match.group(1)
            if process.poll() is not None:
                raise RuntimeError(content)
            time.sleep(.1)
        raise RuntimeError("Studio did not start.")

    def stop():
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if log_handle:
            log_handle.close()

    try:
        launch = start()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("OBSERVA_CHROMIUM"))
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def enter(url):
                for _ in range(30):
                    try:
                        page.goto(url)
                        page.get_by_label("Message Codex").wait_for()
                        return
                    except Exception:
                        time.sleep(.2)
                raise RuntimeError("Studio frontend did not become ready.")

            enter(launch)
            page.screenshot(path=str(out / "01-welcome.png"))
            if not args.review_existing:
                page.get_by_role("button", name="Create your first project").click()
                page.get_by_label("Project name", exact=True).fill("Studio acceptance research")
                page.get_by_label("Existing project directory", exact=False).fill(str(project))
                page.get_by_role("dialog").get_by_role("button", name="Create project", exact=True).click()
                page.get_by_role("dialog").wait_for(state="hidden")
            else:
                page.locator(".conversation-list button").last.click()
            base = launch.split("/#", 1)[0]

            def get(route):
                response = page.request.get(base + "/api" + route)
                assert response.ok, response.text()
                return response.json()

            def post(route, data):
                response = page.request.post(base + "/api" + route, data=data, headers={"X-Observa-Request": "1"})
                assert response.ok, response.text()
                return response.json()

            conversation = get("/state")["conversations"][-1]["id"]
            prompt = (
                "Verify a simple research hypothesis. Read the Studio Observa contract, then create strategy.py "
                "with one strategy class that buys size 0.01 after exactly 3 prior bars and closes the exact "
                "position ticket after exactly 8 prior bars from dataset start, once only. Return [] otherwise. "
                "Use meaningful reasons. Use @sample, interval 15m, starting_balance 10000 and default costs. "
                "Prepare the backtest for my approval using Studio. Do not use shell commands or install anything. "
                "After it completes, inspect its canonical metrics and rejections. Publish a scatter plot with "
                "x = trade index and y = canonical net_realized_pnl from the result, with experiment_ids provenance. "
                "Keep your response concise."
            )
            if not args.review_existing:
                page.get_by_label("Message Codex").fill(prompt)
                page.get_by_role("button", name="Send message", exact=True).click()

            def finish_turn(expect_experiment=True):
                deadline = time.monotonic() + 600
                reported = set()
                while time.monotonic() < deadline:
                    snapshot = get("/conversations/" + conversation)
                    for approval in snapshot["approvals"]:
                        if approval["status"] != "pending":
                            continue
                        params = approval["params"]
                        if approval["method"] == "item/fileChange/requestApproval":
                            item = next(i for i in snapshot["items"] if i.get("provider_id") == params["itemId"])
                            check("file approval is confined to test strategy.py", all(Path(c["path"]).resolve() == project / "strategy.py" for c in item["changes"]))
                        elif approval["method"] == "mcpServer/elicitation/request":
                            check("MCP approval is scoped to Studio", params["serverName"] == "observa_studio" and not params["requestedSchema"]["properties"])
                        else:
                            raise AssertionError("Unexpected permission request: " + json.dumps(approval))
                        post("/approvals/" + approval["id"], {"approved": True})
                    for job in snapshot["experiments"]:
                        if job["status"] == "awaiting_approval":
                            check("approved input uses the intended fixture and interval", job["manifest"]["dataset_origin"] == "@sample" and job["manifest"]["config"]["interval"] == "15m")
                            page.get_by_role("button", name="Approve & run", exact=True).wait_for()
                            page.screenshot(path=str(out / "02-approval.png"))
                            page.get_by_role("button", name="Approve & run", exact=True).click()
                        elif job["status"] in ("failed", "interrupted", "cancelled", "declined"):
                            raise AssertionError("Experiment did not complete: " + json.dumps(job))
                    status = snapshot["conversation"]["status"]
                    if status not in reported:
                        print("Codex:", status, flush=True)
                        reported.add(status)
                    if status in ("error", "interrupted"):
                        raise AssertionError(snapshot["conversation"].get("error"))
                    if status == "idle" and (not expect_experiment or snapshot["experiments"]):
                        return snapshot
                    page.wait_for_timeout(500)
                raise AssertionError("Timed out waiting for a real Codex turn.")

            snapshot = finish_turn()
            job = snapshot["experiments"][-1]
            native_thread = snapshot["conversation"]["thread_id"]
            check("real engine experiment completed", job["status"] == "completed")
            check("one exact-ticket trade and no open positions", job["metrics"]["total_trades"] == 1 and job["metrics"]["open_positions_remaining"] == 0)
            check("Codex published a sourced research plot", bool(snapshot["artifacts"]) and job["id"] in snapshot["artifacts"][-1]["experiment_ids"])
            replay = get(f"/experiments/{job['id']}/replay")
            check("HTTP metrics match canonical result", replay["metrics"] == job["metrics"])
            page.get_by_role("button", name="Explore result", exact=False).click()
            canvas = page.get_by_label("Research canvas", exact=True)
            canvas.get_by_text("Run performance").wait_for()
            page.screenshot(path=str(out / "03-results.png"))
            page.get_by_title("Expand research canvas", exact=True).click()
            check("canvas expands to full screen", page.locator(".research.fullscreen").count() == 1)
            page.get_by_role("button", name="Trades", exact=True).click()
            page.locator("tbody tr").first.click()
            check("trade selection exposes canonical execution events", page.locator(".position-detail").is_visible())
            page.get_by_title("Expand trade explorer", exact=True).click()
            page.screenshot(path=str(out / "04-trades-fullscreen.png"))
            check("trade explorer has its own full screen", page.locator(".trade-overlay").count() == 1)
            page.get_by_title("Exit full-screen trades", exact=True).click()
            page.get_by_role("button", name="Jump to entry", exact=True).click()
            slider = page.get_by_label("Replay bar", exact=True)
            check("trade entry selects its canonical bar", int(slider.input_value()) == get(f"/experiments/{job['id']}/trades")["positions"][0]["opened_bar"])
            slider.fill("2")
            check("backward replay uses the selected canonical snapshot", "snapshots through bar 2" in canvas.inner_text())
            page.get_by_title("Play replay", exact=True).click()
            page.wait_for_timeout(700)
            page.get_by_title("Pause replay", exact=True).click()
            check("replay actually advances", int(slider.input_value()) > 2)
            page.screenshot(path=str(out / "05-replay.png"))
            # Share the authenticated browser context.
            legacy = page.context.new_page()
            legacy.on("pageerror", lambda error: errors.append(str(error)))
            legacy.goto(base + "/legacy/" + job["id"])
            legacy.wait_for_function("typeof payload !== 'undefined' && payload !== null")
            check("original replay remains functional", legacy.evaluate("payload.events.length") == len(replay["events"]))
            legacy.close()
            page.get_by_title("Close research canvas", exact=True).click()
            page.locator(".artifact-card").last.click()
            check("research plot is labeled as agent interpretation", page.get_by_text("Agent-generated interpretation", exact=True).is_visible())
            page.screenshot(path=str(out / "06-artifact.png"))
            page.get_by_title("Close artifact", exact=True).click()
            page.get_by_label("Search research").fill("hypothesis")
            page.wait_for_timeout(400)
            check("history search finds conversation content", page.locator(".conversation-list button").count() == 1)
            page.get_by_label("Search research").fill("")
            stop()
            launch = start()
            base = launch.split("/#", 1)[0]
            page.close()
            context.close()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            enter(launch)
            page.locator(".conversation-list button").first.click()
            page.get_by_role("button", name="Explore result", exact=False).wait_for()
            check("history and result survive service restart", get("/conversations/" + conversation)["experiments"][-1]["id"] == job["id"])
            page.get_by_label("Message Codex").fill("Resume our previous research. Without running any new backtest, inspect the existing experiment and state its canonical final equity and closed trade count. Keep it brief.")
            page.get_by_role("button", name="Send message", exact=True).click()
            # Wait until the submitted request is visible before accepting idle.
            page.wait_for_timeout(700)
            resumed = finish_turn(False)
            check("resume reuses the native Codex thread", resumed["conversation"]["thread_id"] == native_thread)
            check("resume does not duplicate experiments", len(resumed["experiments"]) == len(snapshot["experiments"]))
            check("resume produced a new real agent response", len([i for i in resumed["items"] if i["type"] == "agentMessage"]) > len([i for i in snapshot["items"] if i["type"] == "agentMessage"]))
            page.screenshot(path=str(out / "07-resumed.png"))
            page.get_by_label("Message Codex").fill("Read the strategy contract and draft a detailed research plan for this strategy. Do not edit files or run backtests; this turn will be interrupted to verify cancellation.")
            page.get_by_role("button", name="Send message", exact=True).click()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                state = get("/conversations/" + conversation)["conversation"]
                if state["status"] == "running" and state.get("turn_id"):
                    break
                page.wait_for_timeout(200)
            else:
                raise AssertionError("Codex did not start the cancellation test turn.")
            page.get_by_role("button", name="Stop agent", exact=True).click()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                cancelled = get("/conversations/" + conversation)
                if cancelled["conversation"]["status"] == "idle":
                    break
                page.wait_for_timeout(200)
            check("real Codex turn can be interrupted", cancelled["conversation"]["status"] == "idle" and not cancelled["conversation"].get("turn_id"))
            check("cancellation does not create another experiment", len(cancelled["experiments"]) == len(snapshot["experiments"]))
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            page.get_by_label("Message Codex").wait_for()
            check("mobile layout has no horizontal page overflow", page.evaluate("document.body.scrollWidth <= innerWidth"))
            page.screenshot(path=str(out / "08-mobile.png"))
            check("no browser runtime errors", not errors)
            evidence = {"checks": checks, "browser_errors": errors, "conversation": conversation,
                        "native_thread": native_thread, "experiment": job["id"], "metrics": job["metrics"],
                        "snapshot_hash": job["snapshot_hash"], "run_dir": job["run_dir"]}
            (out / "verification.json").write_text(json.dumps(evidence, indent=2))
            browser.close()
    finally:
        stop()


if __name__ == "__main__":
    main()
