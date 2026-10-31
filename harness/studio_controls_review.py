"""Replay/browser regression with real engine data and native Codex settings.

Run after building Studio: python harness/studio_controls_review.py --out <dir>
Requires Playwright Chromium and an authenticated installed Codex (catalog only).
--real-codex additionally makes two small model calls to verify mode/permissions
and persisted native thread resume. Never enables full access.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright, expect
from observa.studio.store import Store
from observa.studio.experiments import Experiments

STRATEGY = '''
class ReplayFixture:
    def initialize(self, params=None):
        self.first = None
    def on_bar(self, bar, portfolio, history):
        n = len(history)
        self.first = self.first or bar["timestamp"]
        signals = []
        if n == 3:
            signals = [{"direction": "buy", "size": 0.01, "sl": bar["close"] - 0.05,
                        "tp": bar["close"] + 0.05, "reason": "Replay regression entry"}]
        elif n == 8 and portfolio["has_open_position"]:
            p = portfolio["open_positions"][0]
            signals = [{"direction": "close", "size": p["size"], "ticket": p["position_id"], "reason": "Replay regression exit"}]
        drawings = [
            {"id": "sma", "type": "series", "value": sum(b["close"] for b in list(history)[-3:]) / 3 if n >= 3 else None,
             "color": "#2867cc", "width": 2, "label": "SMA 3"},
            {"id": "range", "type": "series", "series_type": "histogram", "pane": "separate",
             "value": bar["high"] - bar["low"], "color": "#559181", "label": "Bar range"},
            {"id": "level", "type": "hline", "price": bar["open"], "color": "#d29922", "label": "Reference open"},
            {"id": "window", "type": "region", "time_start": self.first, "time_end": bar["timestamp"], "color": "#58a6ff", "opacity": 0.06},
        ]
        if n == 3:
            drawings.append({"id": "signal", "type": "marker", "time": bar["timestamp"], "color": "#2867cc", "text": "Strategy signal"})
        return {"signals": signals, "drawings": drawings}
    def teardown(self):
        pass
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-codex', action='store_true')
    parser.add_argument('--chart-only', action='store_true', help='Check chart behavior without launching Codex')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    def check(label, condition=True):
        assert condition, label
        checks.append(label)
        print('PASS', label, flush=True)
    with tempfile.TemporaryDirectory(prefix='observa-controls-') as temp:
        root = Path(temp)
        project = root / 'project'
        project.mkdir()
        (project / 'strategy.py').write_text(STRATEGY)
        async def seed():
            store = Store(root / 'data')
            store.put('project', {'id': 'p', 'name': 'Replay controls', 'path': str(project)})
            store.put('conversation', {'id': 'c', 'project': 'p', 'title': 'Replay regression', 'status': 'idle'}, 'p')
            experiments = Experiments(store)
            job = experiments.prepare('c', {'strategy_file': 'strategy.py', 'config': {'interval': '15m'}})
            experiments.decide(job['id'], True, job['snapshot_hash'])
            await experiments.tasks[job['id']]
            job = store.require('experiment', job['id'])
            assert job['status'] == 'completed', job
            await experiments.close()
            store.close()
            return job
        job = asyncio.run(seed())
        check('real isolated engine produced the annotated trade fixture', job['metrics']['total_trades'] == 1)
        log = (args.out / 'server.log').open('w')
        process = subprocess.Popen([sys.executable, '-c', 'from observa.cli import main; raise SystemExit(main())',
            'studio', '--no-browser', '--data-dir', str(root / 'data')], stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                match = re.search(r'Open: (http://127\.0\.0\.1:\d+/\#token=\S+)', (args.out / 'server.log').read_text())
                if match: break
                time.sleep(.1)
            assert match, 'Studio did not start'
            launch = match.group(1)
            base = launch.split('/#', 1)[0]
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, executable_path=os.environ.get('OBSERVA_CHROMIUM'))
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(launch)
                page.locator('.conversation-list button').first.click()
                page.get_by_role('button', name='Explore result', exact=False).click()
                page.get_by_title('Expand research canvas', exact=True).click()
                page.get_by_role('button', name='Trades', exact=True).click()
                page.locator('tbody tr').first.click()
                expect(page.get_by_text('Price replay', exact=True)).to_be_visible()
                slider = page.get_by_label('Replay bar', exact=True)
                trades = page.request.get(base + '/api/experiments/' + job['id'] + '/trades').json()['positions']
                expect(slider).to_have_value(str(trades[0]['closed_bar']))
                check('clicking a trade opens replay at its canonical exit and focuses the trade')
                expect(page.get_by_label('Strategy indicators')).to_contain_text('SMA 3')
                expect(page.get_by_label('Strategy indicators')).to_contain_text('Bar range')
                check('recorded price indicator and separate histogram pane render')
                expect(page.locator('a[href^="/legacy/"]')).to_have_count(0)
                replay = page.request.get(base + '/api/experiments/' + job['id'] + '/replay').json()
                surface = page.locator('.chart-surface').first
                box = surface.bounding_box()
                tooltip = page.get_by_role('tooltip', name='Chart values')
                for ratio in [0.4, 0.45, 0.5, 0.55]:
                    page.mouse.move(box['x'] + box['width'] * ratio, box['y'] + 90)
                    if tooltip.is_visible(): break
                expect(tooltip).to_be_visible()
                bar_index = int(tooltip.locator(':scope > small').inner_text().split()[1]) - 1
                close = tooltip.locator('dl > div').filter(has=page.get_by_text('Close', exact=True)).locator('dd').inner_text()
                check('chart tooltip displays the hovered canonical candle', abs(float(close.replace(',', '')) - replay['bars'][bar_index]['close']) < 0.00001)
                sma = tooltip.locator('dl > div').filter(has=page.get_by_text('SMA 3', exact=True)).locator('dd').inner_text()
                recorded = next(d['value'] for d in replay['drawings'][bar_index] if d['id'] == 'sma')
                check('indicator tooltip displays the recorded sample at the same bar', (sma == '—' if recorded is None else abs(float(sma.replace(',', '')) - recorded) < 0.00001))
                page.screenshot(path=str(args.out / 'chart-tooltip.png'))
                page.mouse.move(5, 5)
                expect(tooltip).not_to_be_visible()
                check('tooltip clears when leaving the chart')
                page.screenshot(path=str(args.out / 'trade-highlight.png'))
                for label in ['Indicators & drawings', 'Trade markers', 'Entry / SL / TP']:
                    page.get_by_label(label, exact=True).uncheck()
                    page.get_by_label(label, exact=True).check()
                page.get_by_role('button', name='Jump to entry', exact=True).click()
                expect(slider).to_have_value(str(trades[0]['opened_bar']))
                check('trade entry jump preserves canonical bar identity')
                page.get_by_role('button', name='First bar', exact=True).click()
                page.get_by_label('Replay speed', exact=True).select_option('0.5×')
                page.get_by_title('Play replay', exact=True).click()
                page.wait_for_timeout(1100)
                page.get_by_title('Pause replay', exact=True).click()
                slow = int(slider.input_value())
                page.get_by_role('button', name='First bar', exact=True).click()
                page.get_by_label('Replay speed', exact=True).select_option('5×')
                page.get_by_title('Play replay', exact=True).click()
                page.wait_for_timeout(1100)
                page.get_by_title('Pause replay', exact=True).click()
                check('speed selection changes actual playback rate', int(slider.input_value()) > slow + 3)
                page.get_by_role('button', name='First bar', exact=True).click()
                expect(page.get_by_label('Strategy indicators')).to_contain_text('SMA 3 · 0 points')
                check('backward replay does not display future indicator samples')
                page.get_by_role('button', name='Last bar', exact=True).click()
                page.get_by_role('button', name='Fit chart', exact=True).click()
                account = page.locator('.chart-wrap').last
                account.scroll_into_view_if_needed()
                expect(account.get_by_label('Balance', exact=True)).to_be_checked()
                account.get_by_label('Balance', exact=True).uncheck()
                account.get_by_label('Balance', exact=True).check()
                if replay['metrics'].get('max_drawdown_start') and replay['metrics'].get('max_drawdown_end'):
                    account.get_by_role('button', name='Inspect drawdown', exact=True).click()
                    account.get_by_role('button', name='Fit account chart', exact=True).click()
                box = account.locator('.chart-surface').bounding_box()
                page.mouse.move(box['x'] + box['width'] * 0.5, box['y'] + 70)
                expect(page.get_by_role('tooltip', name='Account values')).to_contain_text('Balance')
                check('balance and maximum-drawdown inspection are integrated in the account chart')
                page.mouse.move(5, 5)
                page.get_by_title('Expand trade explorer', exact=True).click()
                check('trade explorer retains fullscreen', page.locator('.trade-overlay').count() == 1)
                page.get_by_title('Exit full-screen trades', exact=True).click()
                legacy = page.context.new_page()
                legacy.on('pageerror', lambda e: errors.append(str(e)))
                legacy.goto(base + '/legacy/' + job['id'])
                legacy.wait_for_function("() => typeof payload !== 'undefined' && payload !== null && typeof chart !== 'undefined'")
                legacy.evaluate('() => applyDrawingState(ObservaDrawings.fold(payload.drawings, 8, payload.bars.map(b => toUnix(b.time))))')
                legacy.screenshot(path=str(args.out / 'legacy-drawings.png'))
                check('legacy replay still renders shared drawing primitives and indicators')
                legacy.close()
                page.get_by_title('Close research canvas', exact=True).click()
                if args.chart_only:
                    check('chart browser reports no JavaScript errors', not errors)
                    (args.out / 'verification.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'real_codex': False}, indent=2))
                    browser.close()
                    return
                composer = page.get_by_label('Message Codex')
                composer.fill('/model')
                page.get_by_role('button', name='/model Choose model and reasoning effort', exact=True).click()
                dialog = page.get_by_role('dialog')
                expect(dialog.get_by_label('Model', exact=True)).to_be_visible(timeout=60000)
                check('slash model menu reads the real installed Codex model catalog', dialog.get_by_label('Model', exact=True).locator('option').count() > 0)
                dialog.get_by_label('Mode', exact=True).select_option('plan')
                dialog.get_by_label('Permissions', exact=True).select_option('full-access')
                expect(dialog.get_by_role('button', name='Save settings')).to_be_disabled()
                check('full access requires explicit confirmation')
                dialog.get_by_label('Permissions', exact=True).select_option('automatic')
                page.screenshot(path=str(args.out / 'codex-controls.png'))
                dialog.get_by_role('button', name='Save settings').click()
                expect(dialog).not_to_be_visible(timeout=60000)
                page.reload()
                expect(page.get_by_title('Mode (/mode)')).to_have_text('Plan')
                expect(page.get_by_title('Permissions (/permissions)')).to_contain_text('Approve for me')
                check('model, plan mode and automatic review persist across browser refresh')
                def get():
                    response = page.request.get(base + '/api/conversations/c')
                    assert response.ok, response.text()
                    return response.json()
                def run(text):
                    prior = len(get()['items'])
                    composer.fill(text)
                    page.get_by_role('button', name='Send message', exact=True).click()
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        value = get()
                        if value['conversation']['status'] in ('error', 'interrupted'):
                            raise AssertionError(value['conversation'])
                        if value['conversation']['status'] == 'idle' and len(value['items']) > prior + 1:
                            return value
                        page.wait_for_timeout(250)
                    raise AssertionError('Native Codex turn timed out')
                if args.real_codex:
                    value = run('Reply in one sentence describing your role. Do not call tools, edit files, or run backtests.')
                    thread = value['conversation']['thread_id']
                    check('real Codex turn accepts selected model, effort, Plan and native automatic review', bool(thread))
                    page.get_by_title('Mode (/mode)').click()
                    dialog.get_by_label('Mode', exact=True).select_option('default')
                    dialog.get_by_label('Permissions', exact=True).select_option('sandboxed')
                    dialog.get_by_role('button', name='Save settings').click()
                    expect(dialog).not_to_be_visible(timeout=60000)
                    value = run('Without tools, state in one short sentence what I asked in my previous message.')
                    check('changing mode and permissions resumes the same real native thread', value['conversation']['thread_id'] == thread)
                    check('settings changes do not duplicate experiments', len(value['experiments']) == 1)
                composer.fill('/')
                page.screenshot(path=str(args.out / 'slash-menu.png'))
                page.set_viewport_size({'width': 390, 'height': 844})
                if page.get_by_title('Hide sidebar').is_visible():
                    page.get_by_title('Hide sidebar').click()
                check('mobile chat controls fit the viewport', page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'))
                page.screenshot(path=str(args.out / 'mobile-controls.png'))
                check('browser reports no JavaScript errors', not errors)
                (args.out / 'verification.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'real_codex': args.real_codex}, indent=2))
                browser.close()
        finally:
            process.send_signal(signal.SIGINT)
            try: process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            log.close()

if __name__ == '__main__':
    main()
