"""Browser-level touch regression for the gender-specific admin photo editor.
Run after `python -m playwright install --with-deps chromium`.
"""
import http.server
import os
import sys
from pathlib import Path
import socketserver
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.template.loader import get_template
from playwright.sync_api import sync_playwright

OUT = ROOT / ".hero_mobile_scroll_fixture"
OUT.mkdir(exist_ok=True)
(OUT / "static").mkdir(exist_ok=True)
static_link = OUT / "static" / "booking"
if not static_link.exists():
    static_link.symlink_to(ROOT / "static" / "booking", target_is_directory=True)

html = get_template("booking/app_management.html").render({
    "section": "hero",
    "section_title": "Startseitenbilder",
    "section_subtitle": "Bilder für Damen, Herren und als Standard festlegen",
    "hero_images": [
        {"variant": "frau", "label": "Damen", "image_url": ""},
        {"variant": "herr", "label": "Herren", "image_url": ""},
        {"variant": "default", "label": "Standard", "image_url": ""},
    ],
    "view_only": False,
})
(OUT / "index.html").write_text(html, encoding="utf8")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUT), **kwargs)

    def log_message(self, *args):
        pass

class Server(socketserver.TCPServer):
    allow_reuse_address = True

with Server(("127.0.0.1", 0), Handler) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 393, "height": 852},
            device_scale_factor=2.6,
            is_mobile=True, has_touch=True,
        )
        missing_styles=[]
        page.on("response", lambda response: missing_styles.append(response.url)
                if "/static/booking/" in response.url and response.status >= 400 else None)
        page.goto(url, wait_until="networkidle")
        assert not missing_styles, f"Missing browser CSS: {missing_styles}"
        assert page.locator(".hero-admin-card").count() == 3
        metrics=page.evaluate("""() => ({
          overflow: getComputedStyle(document.documentElement).overflowY,
          mainOverflow: getComputedStyle(document.querySelector('main.app-management-shell')).overflowY,
          height: document.documentElement.scrollHeight,
          viewport: window.innerHeight,
          currentY: window.scrollY
        })""")
        assert metrics["height"] > metrics["viewport"] * 1.5, metrics
        assert metrics["overflow"] != "hidden", metrics
        assert metrics["mainOverflow"] != "hidden", metrics

        # Simulate a real Android finger swipe: user drags upward starting on
        # the first upload card. Scrolling must advance the document itself.
        session=page.context.new_cdp_session(page)
        session.send("Input.dispatchTouchEvent", {
            "type": "touchStart", "touchPoints": [{"x": 220, "y": 710, "id": 1}]
        })
        for y in range(690, 170, -20):
            session.send("Input.dispatchTouchEvent", {
                "type": "touchMove", "touchPoints": [{"x": 220, "y": y, "id": 1}]
            })
            time.sleep(0.014)
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(350)
        after_swipe=page.evaluate("window.scrollY")
        assert after_swipe > 80, f"Android touch swipe did not scroll the document: {metrics}, after={after_swipe}"

        # Standard (third) card must be reachable without nested scroll traps.
        page.locator(".hero-admin-card").last.scroll_into_view_if_needed()
        assert page.locator(".hero-admin-card").last.is_visible()
        assert page.locator(".hero-admin-card").last.locator("button.hero-admin-save").is_visible()
        print(f"PASS mobile touch scroll: first swipe y={after_swipe:.1f}; "
              "Damen, Herren and Standard forms reachable; stylesheets loaded")
        browser.close()
    server.shutdown()
