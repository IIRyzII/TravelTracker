"""Render the app icons from the ORBIT logo (needs Playwright + Chromium).

    python scripts/make_icons.py

Writes static/icons/: icon-192.png, icon-512.png, icon-maskable-512.png,
apple-touch-icon.png and icon.svg.
"""

import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "icons")
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")


def logo_svg(scale):
    """The brand mark (blue planet + dark orbit ring) on the page colour.
    `scale` is the planet's diameter as a share of the canvas."""
    r = 50 * scale
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <defs><radialGradient id="glow" cx="50%" cy="50%" r="50%">
    <stop offset="0%" stop-color="#3987e5" stop-opacity="0.45"/>
    <stop offset="100%" stop-color="#3987e5" stop-opacity="0"/></radialGradient></defs>
  <rect width="100" height="100" fill="#0d0d0d"/>
  <circle cx="50" cy="50" r="{r * 1.35:.2f}" fill="url(#glow)"/>
  <circle cx="50" cy="50" r="{r:.2f}" fill="#3987e5"/>
  <ellipse cx="50" cy="50" rx="{r * 1.22:.2f}" ry="{r * 0.36:.2f}" fill="none" stroke="#0d0d0d"
           stroke-width="{r * 0.16:.2f}" transform="rotate(-18 50 50)"/>
</svg>"""


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "icon.svg"), "w") as f:
        f.write(logo_svg(0.62))
    jobs = [
        ("icon-192.png", 192, 0.62),
        ("icon-512.png", 512, 0.62),
        ("apple-touch-icon.png", 180, 0.58),
        ("icon-maskable-512.png", 512, 0.46),  # stays inside the 80% safe zone
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM if os.path.exists(CHROMIUM) else None)
        for name, size, scale in jobs:
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(f"<html><body style='margin:0'>{logo_svg(scale)}</body></html>")
            page.eval_on_selector("svg", f"s => {{ s.setAttribute('width', {size}); s.setAttribute('height', {size}); }}")
            page.screenshot(path=os.path.join(OUT, name), clip={"x": 0, "y": 0, "width": size, "height": size})
            page.close()
            print("wrote", name)
        browser.close()


if __name__ == "__main__":
    main()
