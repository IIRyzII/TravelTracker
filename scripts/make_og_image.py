"""Screenshot the link-preview image (static/icons/og-image.png, 1200x630).

    gunicorn wsgi:app -b 127.0.0.1:5055 &        # a throwaway local database
    python scripts/make_og_image.py http://127.0.0.1:5055

Signs up a demo traveller, colours in a few countries, hides the app chrome
and captures the globe beside the ORBIT headline.
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5055").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "icons", "og-image.png")
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")

VISITED = ["FRA", "ESP", "ITA", "DEU", "GBR", "PRT", "GRC", "NLD", "CHE", "AUT", "HRV", "IRL",
           "ISL", "NOR", "MAR", "EGY", "TUR", "KEN", "TZA", "ZAF", "BRA", "USA", "CAN"]
WISHLIST = ["Namibia", "Madagascar", "Finland", "Estonia", "Jordan", "Peru"]

HEADLINE = """() => {
  for (const sel of ['.topbar', '.stats-rail', '.globe-search', '.globe-legend', '.lod-pill', '#toast'])
    document.querySelector(sel).style.display = 'none';
  document.getElementById('globe').style.transform = 'translateX(24%)';
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;left:72px;top:0;bottom:0;display:flex;flex-direction:column;' +
    'justify-content:center;gap:18px;z-index:99;font-family:system-ui,sans-serif;color:#fff;width:520px';
  box.innerHTML = `
    <div style="display:flex;align-items:center;gap:18px">
      <img src="/static/icons/icon-192.png" style="width:72px;height:72px;border-radius:18px">
      <span style="font-size:64px;font-weight:800;letter-spacing:.14em">ORBIT</span></div>
    <div style="font-size:40px;font-weight:700;line-height:1.15">Every country you've set foot in, on a 3D globe.</div>
    <div style="font-size:24px;color:#c3c2b7">Compare maps with friends. Plan the next trip.</div>`;
  document.body.appendChild(box);
}"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM if os.path.exists(CHROMIUM) else None,
                                    args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.goto(BASE + "/")
        page.wait_for_selector("#authOverlay:not([hidden])")
        page.fill("#authName", "Demo")
        page.fill("#authEmail", f"demo-{int(time.time())}@example.com")
        page.fill("#authPassword", "demo password")
        page.click("#authSubmit")
        page.wait_for_selector("#authOverlay", state="hidden")
        page.evaluate("""async ([visited, wishes]) => {
            const post = (path, body) => fetch(path, {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            for (const code of visited) await post('/api/visited', {code});
            for (const place of wishes) await post('/api/wishlist', {place});
        }""", [VISITED, WISHLIST])
        page.reload()
        page.wait_for_selector("#globe canvas")
        time.sleep(2.5)
        page.evaluate(HEADLINE)
        time.sleep(0.8)
        page.screenshot(path=OUT)
        browser.close()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
