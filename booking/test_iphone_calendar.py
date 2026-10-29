"""Regression contracts for the SimplyBook reference based mobile calendar.

The Django suites exercise authenticated booking and appointment permissions.
This file checks that UI parity additions remain scoped and wired correctly.
"""
from pathlib import Path
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class IPhoneCalendarIntegrationTests(SimpleTestCase):
    def source(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_calendar_only_assets_and_cache_busting(self):
        admin = self.source("static/booking/admin.js")
        for marker in (
            "document.querySelector('.sb-calendar-panel')",
            "admin-calendar-iphone-v1.css",
            "admin-calendar-iphone-v1.js",
            "admin-calendar-reference-v2.css",
            "data-admin-calendar-reference-v2",
            "20261029-reference2",
        ):
            self.assertIn(marker, admin)

    def test_race_safe_calendar_navigation_and_initial_edit_hydration(self):
        plus = self.source("static/booking/admin-calendar-plus.js")
        iphone = self.source("static/booking/admin-calendar-iphone-v1.js")
        for marker in (
            "const token = ++latestNavigationToken",
            "if (token !== latestNavigationToken) return true",
            "window.aplusCalendarNavigate = navigateToDay",
            "aplus:calendar-day-changed",
            "updateHistory: false",
        ):
            self.assertIn(marker, plus)
        self.assertIn("window.aplusCalendarNavigate(value)", iphone)
        self.assertIn("window.addEventListener('popstate'", iphone)
        self.assertIn("location.assign(urlFor(value,'day'))", iphone)

    def test_reference_navigation_is_not_same_as_appointment_navigation(self):
        iphone = self.source("static/booking/admin-calendar-iphone-v1.js")
        self.assertIn("function changeWeek(direction)", iphone)
        self.assertIn("visibleMonday=next;", iphone)
        self.assertIn("renderStrip();", iphone)
        self.assertIn("location.assign(urlFor(next,'week'))", iphone)
        self.assertIn("nav.querySelectorAll('.sb-date-arrow')", iphone)
        self.assertIn("event.stopImmediatePropagation()", iphone)
        self.assertIn("shell.addEventListener('touchstart'", iphone)
        self.assertIn("shell.addEventListener('touchend'", iphone)
        self.assertIn("scrollWeekTo(value)", iphone)
        self.assertIn("scrollWeekTo(selectedDate)", iphone)
        self.assertIn("Kalendertag auswählen", iphone)
        self.assertIn("picker.type='date'", iphone)

    def test_visual_css_follows_reference_and_overrides_global_premium(self):
        css = self.source("static/booking/admin-calendar-reference-v2.css")
        for marker in (
            "--sb-ref-navy: #26394e",
            "--sb-ref-cyan: #10b7d8",
            "--sb-ref-gold: #ffd17b",
            ".sb-iphone-weekstrip.is-week::before",
            ".sb-calendar-shell.is-week",
            "grid-template-columns:repeat(7,calc((100vw - 62px) / 2))",
            ".sb-reference-filter-sheet",
            ".sb-reference-header-save",
            ".sb-reference-human-date",
            'html[data-clinic-design="premium"][data-admin-page="calendar"]',
            ".sb-calendar-event:not(.is-overlap-layout)",
        ):
            self.assertIn(marker, css)

    def test_note_form_save_and_mobile_calendar_modes(self):
        dashboard = self.source("templates/booking/dashboard.html")
        for marker in (
            "Kalender ({% if calendar_view == 'week' %}Woche",
            "data-iphone-date-open",
            "data-iphone-filter-open",
            'data-view-menu',
            'role="menuitem"',
            'form="sb-new-note-form"',
            'id="sb-new-note-form"',
            "sb-reference-scope-message",
            "sb-reference-note-type",
        ):
            self.assertIn(marker, dashboard)

    def test_original_booking_and_security_critical_controls_still_exist(self):
        shared = self.source("templates/booking/_shared_admin_calendar.html")
        for marker in (
            "data-fab", "data-open-note", "sb-provider-switcher",
            "sb-calendar-event", "sb-calendar-block",
            "delete_calendar_item", "data-open-booking",
        ):
            self.assertIn(marker, shared)
        plus = self.source("static/booking/admin-calendar-plus.js")
        self.assertIn("credentials: 'same-origin'", plus)
        self.assertIn("openDynamicAppointment(data)", plus)
        self.assertIn("openDynamicBlock(data)", plus)
