"""End-to-end smoke test in a real browser, at phone and desktop sizes.

    pip install -r requirements-dev.txt
    gunicorn wsgi:app -b 127.0.0.1:5055 &      # with RATELIMIT_ENABLED=0
    python tests/e2e/smoke.py http://127.0.0.1:5055 screenshots/

Signs up, logs a country from the search box, walks every tab checking that
nothing spills off the side of the screen, builds and saves a trip, opens the
account sheet, and fails on any console error or CSP violation. Screenshots of
each screen land in the output folder.
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5055").rstrip("/")
OUT = sys.argv[2] if len(sys.argv) > 2 else "screenshots"
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")

VIEWPORTS = {
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                  is_mobile=True, has_touch=True),
    "desktop": dict(viewport={"width": 1440, "height": 900}),
}

# anything wider than the screen (the globe canvas is allowed to fill it)
OVERFLOW_JS = """() => {
  const w = window.innerWidth;
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('#globe') || el.closest('[hidden]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.right > w + 1 || r.left < -1) bad.push(`${el.tagName}.${el.className} ${Math.round(r.left)}..${Math.round(r.right)}`);
  }
  return {bad: bad.slice(0, 8), scroll: document.documentElement.scrollWidth, w};
}"""


def wait_until(page, expr, timeout=15):
    """Poll a JS expression (wait_for_function would need eval, which our CSP blocks)."""
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(f"() => {expr}"):
            return
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {expr}")


def run(name, opts, browser, failures):
    ctx = browser.new_context(**opts, service_workers="allow")
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("""document.addEventListener('securitypolicyviolation',
        e => console.error('CSP violation: ' + e.violatedDirective + ' ' + e.blockedURI));""")

    def shot(label):
        print(f"  {name}: {label}", flush=True)
        page.screenshot(path=os.path.join(OUT, f"{name}-{label}.png"))

    def check_overflow(label):
        res = page.evaluate(OVERFLOW_JS)
        if res["bad"] or res["scroll"] > res["w"]:
            failures.append(f"{name}/{label}: overflow {res}")

    def tab(view):
        page.click(f'.tab[data-view="{view}"]')
        page.wait_for_selector(f"#view-{view}.active")
        time.sleep(0.4)

    page.goto(BASE + "/")
    page.wait_for_selector("#authOverlay:not([hidden])")
    shot("1-signup")
    check_overflow("signup")

    page.fill("#authName", "Robin")
    page.fill("#authEmail", f"robin-{name}-{int(time.time())}@example.com")
    page.fill("#authPassword", "a good password")
    page.click("#authSubmit")
    page.wait_for_selector("#authOverlay", state="hidden")
    page.wait_for_selector("#globe canvas")
    time.sleep(1.5)
    shot("2-globe")
    check_overflow("globe")

    # city search runs on ORBIT's own place data (accents don't matter)
    page.fill("#countrySearch", "Zürich")
    page.wait_for_selector('#searchResults li[data-kind="city"]', timeout=5000)
    first_city = page.inner_text('#searchResults li[data-kind="city"]')
    if "Zuerich" not in first_city:
        failures.append(f"{name}: city search for Zürich found {first_city!r}")
    page.fill("#countrySearch", "")

    page.fill("#countrySearch", "Japan")
    page.wait_for_selector('#searchResults li[data-kind="country"]')
    page.click('#searchResults li[data-kind="country"]')
    page.wait_for_selector("#countryPop:not([hidden])", timeout=5000)
    time.sleep(0.4)
    if name == "phone" and "as-sheet" not in (page.get_attribute("#countryPop", "class") or ""):
        failures.append("phone: country popover isn't a bottom sheet")
    shot("3-country")
    check_overflow("country popover")
    page.click('#popActions [data-act="visit"]')
    wait_until(page, "document.getElementById('statVisited').textContent === '1'")

    page.click('#lodPill button[data-mode="city"]')
    wait_until(page, "performance.getEntriesByType('resource').some(r => r.name.includes('cities-1.json'))")
    time.sleep(2)
    shot("4-cities")

    for view in ("logbook", "wishlist", "friends", "trips"):
        tab(view)
        check_overflow(view)
        shot(f"5-{view}")

    tab("planner")
    page.click('#destChips .chip')
    page.wait_for_selector("#itinerary:not([hidden])")
    time.sleep(0.6)
    check_overflow("planner")
    shot("6-planner")
    page.click("#saveTrip")
    page.wait_for_selector("#tripDetail:not([hidden])")
    time.sleep(0.4)
    check_overflow("trip detail")
    shot("7-trip")

    page.click("#profileChip")
    page.wait_for_selector("#accountOverlay:not([hidden])")
    time.sleep(0.3)
    check_overflow("account")
    shot("8-account")
    page.click("#accountClose")

    # the service worker takes over after a reload
    page.reload()
    page.wait_for_selector("#globe canvas")
    time.sleep(1)
    controlled = page.evaluate("!!navigator.serviceWorker && !!navigator.serviceWorker.controller")
    if not controlled:
        failures.append(f"{name}: service worker isn't controlling the page")
    manifest = page.evaluate("""fetch(document.querySelector('link[rel=manifest]')?.href || '/none')
        .then(r => r.ok ? r.json() : null).then(m => m && m.name).catch(() => null)""")
    if not manifest:
        failures.append(f"{name}: no valid web manifest")

    real_errors = [e for e in errors if "favicon" not in e]
    if real_errors:
        failures.append(f"{name}: console errors: {real_errors[:5]}")
    ctx.close()


def main():
    os.makedirs(OUT, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM if os.path.exists(CHROMIUM) else None,
                                    args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for name, opts in VIEWPORTS.items():
            try:
                run(name, opts, browser, failures)
            except Exception as exc:  # keep going so both sizes report
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        browser.close()
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print(f"OK — screenshots in {OUT}/")


if __name__ == "__main__":
    main()
