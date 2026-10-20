"""Server-side isolated customer tabs.

The browser must NEVER receive another tab's medical/booking section.
Prior JS/CSS-only hiding leaked Termine and made the tab bar sticky.
"""
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings


class TabInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.active_links = []
        self.goae_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('data-customer-panel'):
            self.sections.append(a['data-customer-panel'])
        if tag == "button" and a.get("aria-current") == "page":
            self.active_links.append(a.get("data-customer-tab", ""))


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PatientTabVisibilityTests(SimpleTestCase):
    def render_tab(self, tab):
        customer = SimpleNamespace(
            id=1123, pk=1123, first_name="Sophie", last_name="Muster",
            email="sophie@example.invalid", phone="", salutation="",
        )
        return get_template("booking/app_management.html").render({
            "section": "patients", "section_title": "Kunden",
            "section_subtitle": "Patientenakten und Kommunikation",
            "selected_customer": customer, "customer_tab": tab,
            "patient_appointments": [], "patient_records": [],
            "remote_customer_id": None, "view_only": False,
            "query": "Sophie",
        })

    def test_only_requested_section_is_in_html(self):
        for tab, expected in (
            ("overview", ["overview"]),
            ("appointments", ["appointments"]),
            ("points", ["points"]),
            ("records", ["records"]),
        ):
            with self.subTest(tab=tab):
                html = self.render_tab(tab)
                inspector = TabInspector()
                inspector.feed(html)
                self.assertEqual(set(inspector.sections), set(expected))
                self.assertEqual(len(inspector.active_links), 1)
                self.assertEqual(tab, inspector.active_links[0])
                self.assertEqual(html.count('data-customer-panel="' + tab + '"'), len(inspector.sections))

    def test_termine_never_leaks_into_overview_points_or_records(self):
        for tab in ("overview", "points", "records"):
            html = self.render_tab(tab)
            self.assertNotIn('class="patient-appointment-list"', html, tab)
            self.assertNotIn('class="patient-appointments-panel"', html, tab)
        html = self.render_tab("appointments")
        self.assertIn("Noch keine Termine.", html)
        self.assertNotIn("Neuer Akteneintrag", html)
        self.assertNotIn("Punkte anpassen", html)

    def test_medical_record_only_on_akte_tab(self):
        for tab in ("overview", "appointments", "points"):
            html = self.render_tab(tab)
            self.assertNotIn("Neuer Akteneintrag", html)
            self.assertNotIn("Rechnung nach GOÄ", html)
        records = self.render_tab("records")
        self.assertIn("Neuer Akteneintrag", records)
        self.assertIn("patient-goae-details", records)
        self.assertIn("Rechnung nach GOÄ", records)
        self.assertNotIn("Punkte anpassen", records)
        self.assertNotIn("Anrede & Kommunikation", records)

    def test_points_and_overview_have_different_controls(self):
        ov = self.render_tab("overview")
        points = self.render_tab("points")
        self.assertIn("Anrede & Kommunikation", ov)
        self.assertNotIn("Punkte anpassen", ov)
        self.assertIn("Punkte anpassen", points)
        self.assertNotIn("Anrede & Kommunikation", points)

    def test_tabs_are_native_get_buttons_and_do_not_require_js(self):
        html = self.render_tab("overview")
        self.assertIn('id="patient-tab-nav"', html)
        self.assertIn('<input type="hidden" name="tab" value="records">', html)
        self.assertIn('name="q" value="Sophie"', html)
        self.assertIn('name="customer" value="1123"', html)
        self.assertEqual(html.count('class="patient-tab-form"'), 4)
        self.assertNotIn('type="submit" name="tab"', html)
        self.assertNotIn("clinic-patient-tabs-v2.js", html)
        self.assertIn('clinic-patient-finish-v4.css', html)
        self.assertIn('location.replace(u.pathname+u.search)', html)
        css = (Path(__file__).resolve().parent.parent
               / "static/booking/clinic-patient-finish-v4.css").read_text()
        self.assertIn("position:static!important", css)
        self.assertIn("patient-tab-button", css)
        self.assertIn("grid-template-columns:repeat(4", css)
        self.assertIn("patient-profile-single", html)
