"""Guard against the recurring giant logo and double-row desktop navbar.

These tests cover all non-calendar admin pages, including the previously
unpatched wallet page. The calendar template and scripts stay unchanged.
"""
from pathlib import Path

from django.template import Context, Template
from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings


ROOT = Path(__file__).resolve().parent.parent


class ClinicWebHeaderTests(SimpleTestCase):
    def test_single_header_component_is_included_on_all_non_calendar_surfaces(self):
        pages = (
            "booking/admin_dashboard_lambo.html",
            "booking/app_management.html",
            "booking/admin_more.html",
            "booking/app_wallet_management.html",
        )
        for page in pages:
            with self.subTest(page=page):
                source = get_template(page).template.source
                self.assertIn('_clinic_web_header_v3.html', source)
                self.assertIn('clinic-header-v3.css', source)
                self.assertIn('clinic-header-v3.js', source)
                self.assertIn('clinic-desktop-notifications-v1.js', source)
                # Prior duplicated headers and unbounded logo are gone.
                self.assertNotIn('<header class="admin-topbar', source)
        header = get_template("booking/_clinic_web_header_v3.html").template.source
        self.assertEqual(header.count('class="admin-topbar'), 1)
        self.assertEqual(header.count('class="clinic-header-nav"'), 1)
        self.assertIn('width="36" height="36"', header)
        self.assertIn('data-clinic-page="points"', header)

    def test_calendar_shared_partial_remains_untouched(self):
        source = get_template("booking/_shared_admin_calendar.html").template.source
        self.assertNotIn('clinic-header-v3', source)
        self.assertNotIn('clinic-web-polish-v2', source)

    def test_brand_is_hard_bounded_and_navigation_does_not_wrap(self):
        css = (ROOT / "static" / "booking" / "clinic-header-v3.css").read_text(encoding="utf-8")
        self.assertIn("width:34px!important;height:34px!important", css)
        self.assertIn("flex-wrap:nowrap!important", css)
        self.assertIn('data-admin-page="calendar"', css)
        self.assertIn("clinic-header-more", css)

    @override_settings(STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    def test_header_renders_without_active_section(self):
        html = get_template("booking/_clinic_web_header_v3.html").render({})
        self.assertIn("A+ Esthetic", html)
        self.assertIn("/verwaltung/app/wallet/", html)
        self.assertIn("/verwaltung/logout/", html)
