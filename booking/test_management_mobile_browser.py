"""Browser-level regression for the actual management templates, not CSS source strings."""
import importlib.util
import re
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import StaffMember

ROOT = Path(__file__).resolve().parent.parent

@unittest.skipUnless(importlib.util.find_spec("playwright"), "requires Chromium browser CI")
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ManagementMobileBrowserTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_user(
            username="mobile-browser-admin", password="test-password",
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["aplus_app_admin"] = True
        session["aplus_admin_authorization"] = "Bearer test-browser"
        session.save()
        self.staff = StaffMember.objects.create(
            display_name="Browser Test Doctor", active=True, sort_order=1, role="doctor",
        )

    def _html_with_styles(self, response, calendar=False):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        collected = []
        pattern = re.compile(r'<link\b[^>]*rel="stylesheet"[^>]*>|<style[^>]*>.*?</style>', re.I | re.S)
        for match in pattern.finditer(html):
            tag = match.group(0)
            if tag.lower().startswith("<style"):
                collected.append(re.sub(r"^<style[^>]*>|</style>$", "", tag, flags=re.I | re.S))
                continue
            href = re.search(r'href="([^"]+)"', tag)
            if not href: continue
            path = urlparse(href.group(1)).path
            if not path.startswith("/static/"): continue
            item = finders.find(path[len("/static/"):])
            self.assertTrue(item, path)
            collected.append(Path(item).read_text(encoding="utf-8"))
        html = pattern.sub("", html)
        html = re.sub(r'<script\b[^>]*>.*?</script>', "", html, flags=re.I | re.S)
        html = re.sub(r'(<img[^>]*?)\s+src="[^"]+"', r"\1", html, flags=re.I)
        if calendar:
            # These are loaded by admin.js after the initial template response.
            # The last scroll stylesheet is intentionally injected last.
            css_names = ["admin-simply.css", "admin-calendar-plus.css",
                         "admin-calendar-mobile-v2.css", "admin-calendar-iphone-v1.css",
                         "admin-calendar-reference-v2.css", "admin-calendar-sheet-fix-v3.css",
                         "admin-calendar-mobile-finish-v4.css", "admin-calendar-scroll-v5.css"]
            for name in css_names:
                item = finders.find("booking/"+name)
                self.assertTrue(item, name)
                collected.append(Path(item).read_text(encoding="utf-8"))
        return html, collected

    def _page(self, browser, html, styles, *, calendar=False):
        context = browser.new_context(
            viewport={"width":390,"height":820}, is_mobile=True,
            has_touch=True, device_scale_factor=2,
        )
        page = context.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        if calendar:
            page.evaluate("document.body.classList.add('sb-calendar-pro')")
        for style in styles:
            page.add_style_tag(content=style)
        return context, page

    def test_android_swipe_reaches_late_calendar_hours(self):
        from playwright.sync_api import sync_playwright
        date = timezone.localdate().isoformat()
        response = self.client.get("/verwaltung/kalender/", {
            "date":date, "staff":self.staff.pk,
        })
        html, styles = self._html_with_styles(response, calendar=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context, page = self._page(browser, html, styles, calendar=True)
                self.assertTrue(page.locator(".sb-calendar-shell.is-day").count())
                before = page.evaluate("""() => {
                    const m=document.querySelector('main.sb-admin-shell');
                    return {y:m.scrollTop, height:m.scrollHeight, client:m.clientHeight,
                            overflow:getComputedStyle(m).overflowY};
                }""")
                self.assertGreater(before["height"], before["client"]+300, before)
                self.assertIn(before["overflow"], ("scroll","auto"), before)
                page.mouse.move(220, 640)
                page.mouse.wheel(0, 680)
                page.wait_for_timeout(200)
                self.assertGreater(page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"), 70)
                page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop=0")
                # Touch on an appointment card/time track must not deadlock scrolling.
                session=context.new_cdp_session(page)
                session.send("Input.dispatchTouchEvent",{
                    "type":"touchStart","touchPoints":[{"x":210,"y":680,"id":1}]
                })
                for y in range(660,200,-20):
                    session.send("Input.dispatchTouchEvent",{
                        "type":"touchMove","touchPoints":[{"x":210,"y":y,"id":1}]
                    })
                    time.sleep(.011)
                session.send("Input.dispatchTouchEvent",{
                    "type":"touchEnd","touchPoints":[]
                })
                page.wait_for_timeout(220)
                self.assertGreater(
                    page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"),
                    60, "Android finger gesture did not move the calendar scrollport"
                )
                context.close()
            finally:
                browser.close()

    @patch("booking.app_management_views._api")
    def test_points_and_patient_emerald_hero_is_visible_in_chromium(self, api):
        api.return_value = {"ok":True, "customers":[]}
        # Fetch Django responses before Playwright starts its event loop:
        # synchronous ORM access inside its context is prohibited by Django.
        sources = []
        for path, selector in (
            ("/verwaltung/app/wallet/", ".points-admin-hero"),
            ("/verwaltung/app/patients/", ".premium-list-heading"),
        ):
            response = self.client.get(path)
            html, styles = self._html_with_styles(response)
            sources.append((path, selector, html, styles))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for path, selector, html, styles in sources:
                    with self.subTest(path=path):
                        context,page=self._page(browser,html,styles)
                        hero=page.locator(selector).first
                        self.assertTrue(hero.is_visible())
                        computed=hero.evaluate("""el => ({
                            image:getComputedStyle(el).backgroundImage,
                            box:el.getBoundingClientRect().toJSON()
                        })""")
                        self.assertIn("rgb(16, 39, 29)",computed["image"],computed)
                        if path.endswith("/patients/"):
                            panel=page.locator(".premium-customer-panel").first
                            inset=page.evaluate("""() => {
                                let p=document.querySelector('.premium-customer-panel').getBoundingClientRect();
                                let h=document.querySelector('.premium-list-heading').getBoundingClientRect();
                                return {left:Math.abs(p.left-h.left),right:Math.abs(p.right-h.right)}
                            }""")
                            self.assertLess(inset["left"],3,inset)
                            self.assertLess(inset["right"],3,inset)
                        context.close()
            finally:
                browser.close()
