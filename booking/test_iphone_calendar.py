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
            "admin-calendar-sheet-fix-v3.css",
            "admin-calendar-date-dock-v6.css",
            "20261029-view-modes1",
            "20261029-reference2",
        ):
            self.assertIn(marker, admin)

    def test_real_calendar_clearance_cannot_be_overridden_by_panel_padding(self):
        shared=self.source("templates/booking/_shared_admin_calendar.html")
        css=self.source("static/booking/admin-calendar-date-dock-v6.css")
        self.assertIn('class="sb-calendar-dock-space"',shared)
        self.assertIn('.sb-calendar-panel > .sb-calendar-dock-space',css)
        self.assertIn('height:150px!important',css)

    def test_date_controls_are_portaled_outside_scrolling_calendar(self):
        js = self.source("static/booking/admin-calendar-iphone-v1.js")
        css = self.source("static/booking/admin-calendar-date-dock-v6.css")
        self.assertIn("const dock=document.querySelector('[data-reference-date-dock]')", js)
        self.assertIn("dock.replaceChildren(nav,strip)", js)
        self.assertIn("position:fixed!important", css)
        self.assertIn("top:64px!important", css)
        self.assertIn("padding-top:150px!important", css)

    def test_calendar_is_final_style_from_first_html_frame(self):
        template=self.source("templates/booking/dashboard.html")
        script=self.source("static/booking/admin-calendar-iphone-v1.js")
        for marker in (
            'sb-calendar-pro sb-calendar-booting',
            'data-reference-date-dock',
            'sb-reference-date-preview',
            'calendar_strip_days',
            'admin-calendar-reference-v2.css',
            'admin-calendar-date-dock-v6.css',
            "history.scrollRestoration='manual'",
        ):
            self.assertIn(marker,template)
        self.assertIn('resetOnInitialOpen()',script)
        self.assertIn("main.scrollTop=0",script)
        self.assertIn("'pageshow'",script)
        self.assertIn("document.body.classList.remove('sb-calendar-booting')",script)

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

    def test_sheet_heading_dates_and_conditional_service_controls(self):
        css = self.source("static/booking/admin-calendar-sheet-fix-v3.css")
        js = self.source("static/booking/admin-calendar-iphone-v1.js")
        template = self.source("templates/booking/dashboard.html")
        server = self.source("booking/admin_views.py")
        legacy = self.source("static/booking/admin-ferrari-v17.js")
        for marker in (".sb-reference-date-time", ".sb-reference-end-date",
                       ".sb-form-row.sb-service-scope-row:not(.is-visible)",
                       ".sb-form-row.sb-block-service-row:not(.is-visible)",
                       ".sb-form-row.sb-edit-service-row:not(.is-visible)"):
            self.assertIn(marker, css)
        self.assertIn("data-note-end-date", template)
        self.assertIn("data-block-end-date", server)
        self.assertIn("syncConditionalServiceFields", js)
        self.assertIn("button.textContent = '×'", legacy)

    def test_directory_theme_shared_across_customer_surfaces(self):
        css = self.source("static/booking/clinic-signature-surfaces-v1.css")
        self.assertIn('html[data-clinic-design="premium"] body.admin-body .premium-customer-panel .premium-list-heading', css)
        self.assertIn('html[data-clinic-design="premium"] body.admin-body .premium-patient-list', css)

    def test_all_four_real_mode_links_are_exposed(self):
        template=self.source("templates/booking/dashboard.html")
        views=self.source("booking/views.py")
        javascript=self.source("static/booking/admin-calendar-iphone-v1.js")
        for mode in ("day","week","provider","service"):
            self.assertIn("cal_view="+mode,template)
        self.assertIn("Dienstleister-Ansicht",template)
        self.assertIn("Dienstleistungsansicht",template)
        self.assertIn("sb-reference-mode-chevron",template)
        self.assertIn("admin-calendar-view-modes-v1.css",template)
        self.assertIn("viewMode()",javascript)
        self.assertIn("'provider', 'service'",views)

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
