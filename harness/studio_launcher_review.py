"""Exercise the actual Linux desktop entry and browser against disposable data.

No model calls. The browser-launch hook captures the private launch URL so
Playwright can inspect it; the desktop entry, launcher and service are real.
Requires gio, desktop-file-validate and Playwright Chromium.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

from observa.studio.launcher import install_desktop
from observa.studio.local_control import data_root, request, control_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix="observa-desktop-") as temp:
        root = Path(temp)
        capture = root / "browser-urls"
        browser_hook = root / "capture-browser"
        browser_hook.write_text(f"#!{sys.executable}\nimport sys\n"
                                f"with open({str(capture)!r}, 'a') as output:\n"
                                "    output.write(sys.argv[1] + '\\n')\n")
        browser_hook.chmod(0o700)
        environment = {"XDG_DATA_HOME": str(root / "share"), "XDG_CONFIG_HOME": str(root / "config"),
                       "XDG_RUNTIME_DIR": str(root / "runtime"), "BROWSER": str(browser_hook),
                       "PATH": "/usr/bin:/bin"}
        with patch.dict(os.environ, environment):
            desktop = install_desktop()
            subprocess.run(["desktop-file-validate", str(desktop)], check=True)
            assert sys.executable in desktop.read_text()
            registered = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/observa"],
                                        check=True, capture_output=True, text=True, timeout=15)
            assert registered.stdout.strip() == desktop.name
            checks.append("desktop entry validates and uses an absolute installed interpreter")
            data = data_root()

            def launch(uri=None):
                count = len(capture.read_text().splitlines()) if capture.exists() else 0
                command = ["gio", "launch", str(desktop)] + ([uri] if uri else [])
                subprocess.run(command, check=True, timeout=10, stdout=subprocess.DEVNULL)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    urls = capture.read_text().splitlines() if capture.exists() else []
                    if len(urls) > count:
                        return urls[-1]
                    time.sleep(.1)
                raise AssertionError("Desktop launch did not open the browser")

            def wait_closed():
                deadline = time.monotonic() + 15
                while control_path(data).exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                assert not control_path(data).exists(), "Studio did not finish shutdown"

            try:
                first_url = launch()
                pid = request(data, "status")["pid"]
                second_url = launch("observa://open")
                assert request(data, "status")["pid"] == pid
                assert first_url != second_url
                checks.append("desktop icon and fixed deep link reopen one service with fresh launch tokens, without shell PATH")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, executable_path=os.environ.get("OBSERVA_CHROMIUM"))
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(second_url)
                    expect(page.get_by_role("button", name="Quit Studio", exact=True)).to_be_visible()
                    expect(page).to_have_url(second_url.split("#", 1)[0])
                    headers = {"X-Observa-Request": "1"}
                    project = page.request.post(page.url.rstrip("/") + "/api/projects",
                                                data={"name": "Desktop research"}, headers=headers)
                    assert project.ok
                    conversation = page.request.post(page.url.rstrip("/") + "/api/conversations",
                                                     data={"project": project.json()["id"]}, headers=headers)
                    assert conversation.ok
                    page.reload()
                    page.locator(".conversation-list button").first.click()
                    expect(page.get_by_label("Message Codex")).to_be_visible()
                    checks.append("desktop-launched UI authenticates, removes bootstrap URL and opens saved research")
                    page.screenshot(path=str(args.out / "desktop-open.png"))
                    page.once("dialog", lambda dialog: dialog.dismiss())
                    page.get_by_role("button", name="Quit Studio", exact=True).click()
                    assert request(data, "status")["pid"] == pid
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="Quit Studio", exact=True).click()
                    expect(page.get_by_role("heading", name="Studio is closing")).to_be_visible()
                    expect(page.get_by_label("Message Codex")).to_have_count(0)
                    wait_closed()
                    page.screenshot(path=str(args.out / "desktop-quit.png"))
                    checks.append("Quit can be declined; confirmed Quit closes service and removes active chat controls")
                    page.goto(launch())
                    assert request(data, "status")["pid"] != pid
                    page.locator(".conversation-list button").first.click()
                    expect(page.get_by_label("Message Codex")).to_be_visible()
                    snapshot = page.request.get(page.url.rstrip("/") + "/api/conversations/" + conversation.json()["id"])
                    assert snapshot.ok and snapshot.json()["conversation"]["project"] == project.json()["id"]
                    checks.append("application icon restarts service and restores conversation without any model call")
                    page.screenshot(path=str(args.out / "desktop-reopened.png"))
                    browser.close()
                assert not errors, errors
                checks.append("no browser JavaScript errors")
            finally:
                try:
                    request(data, "shutdown")
                    wait_closed()
                except (OSError, RuntimeError):
                    pass
    (args.out / "verification.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2))
    print(json.dumps({"checks": checks, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
