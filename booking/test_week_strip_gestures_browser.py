"""Browser-level regression for the fixed mobile week strip in day and week views.

The browser receives CDP touch events (not just synthetic JS click handlers),
so iOS-style touch arbitration and actual event propagation are exercised.
No live services, customer records, or network calls are required.
"""
import importlib.util
import unittest
from pathlib import Path

from django.test import SimpleTestCase
from django.contrib.staticfiles import finders

HTML = """<!doctype html>
<html lang="de" data-admin-page="calendar">
<head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body class="sb-calendar-pro">
  <main class="sb-admin-shell">
    <div class="sb-date-nav">
      <a class="sb-date-arrow" href="#">‹</a>
      <div class="sb-date-title"></div>
      <a class="sb-date-arrow" href="#">›</a>
    </div>
    <section class="sb-calendar-shell is-day">
      <div class="sb-day-head"></div>
    </section>
  </main>
</body></html>"""


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright is installed in browser CI")
class MobileWeekStripGestureBrowserTests(SimpleTestCase):
    def swipe(self, page, start_x, end_x, y=170):
        # Dispatch genuine Chromium touch input; moving before touchEnd is
        # important because Safari may cancel a touch after scroll arbitration.
        session = page.context.new_cdp_session(page)
        try:
            session.send("Input.dispatchTouchEvent", {
                "type": "touchStart",
                "touchPoints": [{"x": start_x, "y": y, "id": 1}],
            })
            for x in (start_x + (end_x-start_x)/2, end_x):
                session.send("Input.dispatchTouchEvent", {
                    "type": "touchMove",
                    "touchPoints": [{"x": x, "y": y, "id": 1}],
                })
                page.wait_for_timeout(40)
            session.send("Input.dispatchTouchEvent", {
                "type": "touchEnd", "touchPoints": [],
            })
        finally:
            session.detach()

    def fixture(self, browser, mode):
        context = browser.new_context(
            viewport={"width": 390, "height": 820},
            device_scale_factor=2, is_mobile=True, has_touch=True,
        )
        page = context.new_page()
        page.route("https://calendar.test/verwaltung/**",
                   lambda route: route.fulfill(status=200, content_type="text/html", body=HTML))
        page.goto("https://calendar.test/verwaltung/?date=2026-11-22&cal_view="+mode)
        dock_css = finders.find("booking/admin-calendar-date-dock-v6.css")
        iphone_js = finders.find("booking/admin-calendar-iphone-v1.js")
        self.assertTrue(dock_css)
        self.assertTrue(iphone_js)
        page.add_style_tag(content=Path(dock_css).read_text(encoding="utf-8"))
        page.add_script_tag(content=Path(iphone_js).read_text(encoding="utf-8"))
        page.locator(".sb-iphone-weekstrip .sb-iphone-day").first.wait_for()
        self.assertEqual(page.locator(".sb-iphone-weekstrip .sb-iphone-day").count(), 7)
        self.assertEqual(
            page.locator(".sb-iphone-weekstrip .sb-iphone-day").first.get_attribute("data-date"),
            "2026-11-16")
        return context, page

    def test_swiping_fixed_strip_browses_weeks_in_day_view(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context, page = self.fixture(browser, "day")
                self.swipe(page, 300, 90)
                page.wait_for_function(
                    "() => document.querySelector('.sb-iphone-day')?.dataset.date === '2026-11-23'")
                self.assertEqual(
                    page.locator(".sb-iphone-weekstrip .sb-iphone-day").first.get_attribute("data-date"),
                    "2026-11-23")
                # Swiping the date strip should not accidentally submit a
                # booking or silently change the selected appointment day.
                self.assertIn("date=2026-11-22", page.url)
                context.close()
            finally:
                browser.close()

    def test_swiping_fixed_strip_changes_complete_week_view(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context, page = self.fixture(browser, "week")
                self.swipe(page, 300, 90)
                page.wait_for_url("**date=2026-11-23&cal_view=week*", timeout=5000)
                self.assertIn("cal_view=week", page.url)
                context.close()
            finally:
                browser.close()
