import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

src = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
theme = sys.argv[3] if len(sys.argv) > 3 else "light"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1800, "height": 1300}, device_scale_factor=2,
                            color_scheme=theme)
    page.goto(src.as_uri())
    page.wait_for_timeout(600)
    page.locator(".poster").screenshot(path=str(out))
    box = page.locator(".poster").bounding_box()
    browser.close()
print(f"saved {out} poster={box['width']:.0f}x{box['height']:.0f}css px")
