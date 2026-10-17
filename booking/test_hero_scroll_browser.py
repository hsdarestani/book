import importlib.util
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings


SLOTS = [
    {"variant": "frau", "label": "Damen", "image_url": ""},
    {"variant": "herr", "label": "Herren", "image_url": ""},
    {"variant": "default", "label": "Standard", "image_url": ""},
]


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Chromium browser smoke runs in its own CI job")
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class HeroMobileScrollBrowserTests(TestCase):
    def setUp(self):
        staff = User.objects.create_user("hero_scroll_test", "scroll@example.de", "test-only", is_staff=True)
        self.client.force_login(staff)
        session = self.client.session
        session["aplus_app_admin"] = True
        session["aplus_admin_authorization"] = "Bearer test-only"
        session.save()

    @patch("booking.app_management_views._api")
    def test_android_mobile_can_scroll_to_standard_and_find_hero_menu(self, api):
        # Render the ACTUAL Django HTML with all three cards, and load the
        # CSS in its exact document order into a real Chromium mobile viewport.
        api.return_value = {"ok": True, "hero_images": SLOTS}
        response = self.client.get("/verwaltung/app/hero/")
        self.assertEqual(response.status_code, 200)
        source = response.content.decode("utf-8")

        styles = []
        token = re.compile(r'<link\b[^>]*rel="stylesheet"[^>]*>|<style[^>]*>.*?</style>', re.I | re.S)
        for match in token.finditer(source):
            tag = match.group(0)
            if tag.lstrip().lower().startswith("<style"):
                styles.append(re.sub(r'^<style[^>]*>|</style>$', "", tag, flags=re.I | re.S))
                continue
            href = re.search(r'href="([^"]+)"', tag)
            if not href:
                continue
            path = urlparse(href.group(1)).path
            if not path.startswith("/static/"):
                continue
            file_path = finders.find(path[len("/static/"):])
            self.assertTrue(file_path, path)
            styles.append(Path(file_path).read_text(encoding="utf-8"))
        source = token.sub("", source)
        # Avoid trying to load unneeded assets from an unauthenticated origin.
        source = re.sub(r'<script\b[^>]*\bsrc="[^"]+"[^>]*></script>', "", source, flags=re.I)
        source = re.sub(r'(<img[^>]*?)\ssrc="[^"]+"', r'\1', source, flags=re.I)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context = browser.new_context(
                    viewport={"width": 390, "height": 820},
                    is_mobile=True, has_touch=True, device_scale_factor=2,
                )
                page = context.new_page()
                page.set_content(source, wait_until="domcontentloaded")
                for style in styles:
                    page.add_style_tag(content=style)
                page.add_script_tag(content=Path(
                    finders.find("booking/admin-unified-nav-v14.js")
                ).read_text(encoding="utf-8"))
                page.add_script_tag(content=Path(
                    finders.find("booking/admin-scroll-recovery-v9.js")
                ).read_text(encoding="utf-8"))

                self.assertEqual(page.locator(".hero-admin-card").count(), 3)
                self.assertGreater(page.evaluate("document.scrollingElement.scrollHeight"), 1300)
                self.assertIn("auto", page.evaluate(
                    "getComputedStyle(document.documentElement).overflowY"
                ))
                self.assertEqual(page.evaluate("getComputedStyle(document.body).position"), "static")

                # A real scroll gesture must move the document, not a nested
                # zero-height main element. The last upload must be reachable.
                page.mouse.move(170, 450)
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(250)
                self.assertGreater(page.evaluate("window.scrollY"), 100)
                standard = page.locator(".hero-admin-card").last
                standard.scroll_into_view_if_needed(timeout=3000)
                self.assertTrue(standard.locator("h2").inner_text() == "Standard")
                self.assertGreater(page.evaluate("window.scrollY"), 250)
                self.assertTrue(standard.locator("button.hero-admin-save").is_visible())

                # Hamburger must contain Kampagnen and adjacent Startseitenbilder.
                page.evaluate("window.scrollTo(0, 0)")
                page.locator("[data-drawer-open]").first.click()
                nav = page.locator(".sb-drawer-nav")
                campaign = nav.locator('a[href="/verwaltung/mehr/#campaigns"]')
                hero = nav.locator('a[href="/verwaltung/app/hero/"]')
                self.assertEqual(campaign.count(), 1)
                self.assertEqual(hero.count(), 1)
                self.assertTrue(campaign.is_visible())
                self.assertTrue(hero.is_visible())
                context.close()
            finally:
                browser.close()
