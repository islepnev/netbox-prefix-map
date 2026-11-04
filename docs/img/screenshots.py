"""
Regenerate the README screenshots (docs/img/*.png) from the synthetic dataset.

    OUTPUT_DIR=/tmp/pm python -c "from app.cli import full_update; from tests.synthetic_data import FakeNetboxManager; full_update(mgr=FakeNetboxManager())"
    OUTPUT_DIR=/tmp/pm INITIAL_UPDATE=0 NETBOX_API_URL=https://netbox.example.com python -m app.webapp &
    python docs/img/screenshots.py      # set PLAYWRIGHT_CHROMIUM_EXECUTABLE if needed

docs/img/z-order.svg is drawn by hand and not regenerated here.
"""
import os
import time
from playwright.sync_api import sync_playwright
B = "http://localhost:5000/prefix-map"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None)
    ctx = b.new_context(viewport={"width": 1720, "height": 900}, device_scale_factor=1, color_scheme="light")
    pg = ctx.new_page()
    pg.goto(B + "/map/1/10_20_0_0_17"); pg.wait_for_function("document.body.dataset.ready")
    pg.evaluate("localStorage.setItem('prefix-map.free-size','')")
    box = pg.locator("#map-img").bounding_box()
    pg.mouse.click(box["x"] + box["width"] * 0.655, box["y"] + box["height"] * 0.36)
    pg.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.12)
    time.sleep(0.4)
    pg.screenshot(path="docs/img/hero.png")
    # zoom levels: exported SVG of each level, rendered at one size
    for name, path in [("level-8", "/map/1/10_0_0_0_8"), ("level-16", "/map/1/10_20_0_0_16"), ("level-24", "/map/1/10_20_50_0_24")]:
        pg.goto(B + path); pg.wait_for_function("document.body.dataset.ready")
        svg = pg.evaluate("PrefixMapExport.build({mono: false})")
        q = b.new_page(viewport={"width": 380, "height": 520}, device_scale_factor=2)
        q.set_content(f"<html><body style='margin:0;background:#fff'><div style='width:380px'>{svg.replace('<svg ', '<svg style=\"width:380px;height:auto;display:block\" ', 1)}</div></body></html>")
        # The element screenshot covers the whole drawing, also when it is taller than the viewport
        q.locator("svg").screenshot(path=f"docs/img/{name}.png")
        q.close()
    b.close()
