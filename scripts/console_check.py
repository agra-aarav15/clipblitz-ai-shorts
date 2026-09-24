"""V4 console gate: zero JS errors and zero failed requests across a full screen sweep.

Runs the app in the system Edge via Playwright so the evidence does not depend on the
embedded browser panel (whose console recorder is not attachable in this environment).
Walks all five screens, then reports every console error/warning, every uncaught page
error, and every request that did not return 2xx/3xx.
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4301"
URL = f"{BASE}/?v=400&screen=studio"
SCREENS = ["studio", "clips", "lab", "transcript", "connect"]

errors = []
warnings = []
page_errors = []
bad_requests = []
console_all = []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        def on_console(msg):
            rec = {"type": msg.type, "text": msg.text}
            console_all.append(rec)
            if msg.type == "error":
                errors.append(rec)
            elif msg.type == "warning":
                warnings.append(rec)

        page.on("console", on_console)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        def on_response(resp):
            if resp.status >= 400:
                bad_requests.append(f"{resp.status} {resp.url}")

        page.on("response", on_response)
        page.on("requestfailed",
                lambda r: bad_requests.append(f"FAILED {r.url} {r.failure}"))

        page.goto(URL, wait_until="load", timeout=30000)
        page.wait_for_timeout(2500)

        # Sweep every screen twice so lazy render paths and their fetches all execute.
        # Record the active screen each time: a no-op click would make this gate vacuous.
        reached = []
        for _round in range(2):
            for s in SCREENS:
                page.evaluate(
                    "s => { const b = document.querySelector("
                    "`.snavbtn[data-screen='${s}']`); if (b) b.click(); }", s)
                page.wait_for_timeout(350)
                reached.append(page.evaluate(
                    "() => (document.querySelector('.screen:not([hidden])')"
                    " || {}).id || '?'"))
        page.wait_for_timeout(1500)

        # Exercise the real interactive surfaces the brief calls out.
        page.evaluate("""() => {
            const w = document.getElementById('wave');
            if (w) w.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            const t = document.querySelector('#screen-transcript .wplay');
            if (t) t.click();
            document.querySelectorAll('#screen-lab .fbtn').forEach(b => b.click());
            document.querySelectorAll('.capcard').forEach(c => c.click());
        }""")
        page.wait_for_timeout(1200)

        fonts = page.evaluate(
            "() => ['Inter','JetBrains Mono','Space Grotesk']"
            ".map(f => [f, document.fonts.check(`12px \"${f}\"`)])")
        title = page.title()
        browser.close()

    print(f"url            {URL}")
    print(f"title          {title}")
    print(f"screens swept  {' '.join(reached)}")
    print(f"console total  {len(console_all)}")
    for f, ok in fonts:
        print(f"font loaded    {f:16} {ok}")
    print(f"console errors {len(errors)}")
    for e in errors:
        print(f"  ERR  {e['text'][:200]}")
    print(f"console warns  {len(warnings)}")
    for w in warnings:
        print(f"  WARN {w['text'][:200]}")
    print(f"page errors    {len(page_errors)}")
    for e in page_errors:
        print(f"  PAGEERR {e[:300]}")
    print(f"bad requests   {len(bad_requests)}")
    for b in bad_requests:
        print(f"  REQ  {b[:200]}")

    swept = set(r for r in reached if r and r != "?")
    want = set("screen-" + s for s in SCREENS)
    missing = want - swept
    print(f"sweep covered  {len(swept)}/5 screens  missing={sorted(missing)}")
    ok = (not errors and not page_errors and not bad_requests and not missing)
    print(f"verdict        {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
