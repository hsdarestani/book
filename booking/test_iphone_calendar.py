"""Regressions for the isolated iPhone calendar skin and navigation wiring.

No live appointment data is required: the integration is tested at source level;
authenticated API and booking persistence are covered by test_fast_calendar_and_login.
"""
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent


class IPhoneCalendarIntegrationTests(SimpleTestCase):
    def source(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_calendar_ui_assets_load_only_in_calendar_panel(self):
        admin = self.source("static/booking/admin.js")
        self.assertIn("document.querySelector('.sb-calendar-panel')", admin)
        self.assertIn("admin-calendar-iphone-v1.css", admin)
        self.assertIn("admin-calendar-iphone-v1.js", admin)
        self.assertIn("data-admin-calendar-iphone-v1", admin)

    def test_safety_and_navigating_contract(self):
        plus = self.source("static/booking/admin-calendar-plus.js")
        iphone = self.source("static/booking/admin-calendar-iphone-v1.js")
        self.assertIn("const token = ++latestNavigationToken", plus)
        self.assertIn("if (token !== latestNavigationToken) return true", plus)
        self.assertIn("window.aplusCalendarNavigate = navigateToDay", plus)
        self.assertIn("aplus:calendar-day-changed", plus)
        self.assertIn("updateHistory: false", plus)
        self.assertIn("window.aplusCalendarNavigate(value)", iphone)
        self.assertIn("window.addEventListener('popstate'", iphone)
        self.assertIn("location.assign(url)", iphone)

    def test_iphone_behaviors_and_clock_scale(self):
        iphone = self.source("static/booking/admin-calendar-iphone-v1.js")
        css = self.source("static/booking/admin-calendar-iphone-v1.css")
        self.assertIn("Kalendertag auswählen", iphone)
        self.assertIn("picker.type = 'date'", iphone)
        self.assertIn("shell.addEventListener('touchstart'", iphone)
        self.assertIn("shell.addEventListener('touchend'", iphone)
        self.assertIn("target.closest('button,a,input,select,textarea", iphone)
        self.assertIn("--sb-iphone-track: 1040px", css)
        self.assertIn("ferrari-calendar-sticky", css)
        self.assertIn("display: none !important", css)
        self.assertIn("body.sb-calendar-pro.sb-iphone-calendar-ready", css)
        self.assertIn(".sb-iphone-weekstrip", css)
        self.assertIn("@media (max-width: 760px)", css)

    def test_existing_note_booking_and_doctor_forms_retained(self):
        template = self.source("templates/booking/_shared_admin_calendar.html")
        for marker in ("data-fab", "data-open-note", "sb-provider-switcher",
                       "sb-calendar-event", "sb-calendar-block",
                       "delete_calendar_item", "data-open-booking"):
            self.assertIn(marker, template)
