"""Real-browser review of the metrics panel (desktop + mobile screenshots).

    python harness/metrics_panel_review.py NAME=URL [NAME=URL ...]

Start one replay server per run first (e.g. `observa replay RUN --port N`).
Requires development-only playwright and a Chromium installation
(`OBSERVA_CHROMIUM` may point at a Chromium executable). Writes PNGs to
docs/engineering/metrics-panel-screenshots/ and fails on console errors,
horizontal overflow, or "NaN"/"undefined" in the rendered panel.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("docs/engineering/metrics-panel-screenshots")
OUT.mkdir(parents=True, exist_ok=True)
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " :: %s" % detail))
    if not ok:
        failures.append(label)


targets = dict(arg.split("=", 1) for arg in sys.argv[1:])
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=os.environ.get("OBSERVA_CHROMIUM"))
    for name, url in targets.items():
        for vp_name, vp in VIEWPORTS.items():
            page = browser.new_page(viewport=vp, device_scale_factor=2 if vp_name == "mobile" else 1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(url)
            page.wait_for_function("document.querySelector('#metrics-grid') && !document.querySelector('#metrics-grid .empty-note:only-child') || document.querySelector('#run-banner')", timeout=20000)
            page.click('[data-panel="metrics"]')
            page.wait_for_timeout(300)
            # Natural layout first (default panel size), as a user sees it.
            page.screenshot(path=str(OUT / ("%s-%s-natural.png" % (name, vp_name))))
            # Give the analysis panel most of the viewport for the review shot.
            page.evaluate("""() => { const bp = document.getElementById('bottom-panel');
                bp.style.height = Math.round(innerHeight * 0.82) + 'px'; }""")
            page.wait_for_timeout(300)
            text = page.inner_text("#metrics-grid")
            check("%s/%s: no NaN/undefined/Infinity rendered" % (name, vp_name),
                  not any(bad in text for bad in ("NaN", "undefined", "Infinity")), text[:200])
            overflow = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
            check("%s/%s: no horizontal page overflow" % (name, vp_name), overflow <= 1, overflow)
            cards_overflow = page.evaluate("""() => [...document.querySelectorAll('#metrics-grid .metric-card')]
                .filter(c => c.scrollWidth > c.clientWidth + 1).map(c => c.dataset.metric)""")
            check("%s/%s: no card content overflows its card" % (name, vp_name), not cards_overflow, cards_overflow)
            check("%s/%s: no console errors" % (name, vp_name), not errors, errors[:3])
            page.screenshot(path=str(OUT / ("%s-%s.png" % (name, vp_name))), full_page=False)
            # Full panel content as a separate image: grow the viewport and the
            # panel to the content height, then clip to the panel.
            content = page.evaluate("document.getElementById('metrics-grid').scrollHeight")
            page.set_viewport_size({"width": vp["width"], "height": content + 420})
            page.evaluate("""(h) => { document.getElementById('bottom-panel').style.height = (h + 90) + 'px'; }""", content)
            page.wait_for_timeout(300)
            box = page.query_selector("#metrics-panel").bounding_box()
            page.screenshot(path=str(OUT / ("%s-%s-panel.png" % (name, vp_name))), clip=box)
            page.close()
    browser.close()

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
