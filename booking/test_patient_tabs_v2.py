"""Regressions for the bug where all patient tabs displayed together.

The previous UI looked like working tabs, but the controller was included
only on the Hero page. Keep both safe initial HTML visibility and executable
patient-specific JavaScript on the actual page.
"""
from pathlib import Path
from types import SimpleNamespace
from html.parser import HTMLParser

from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings


class PanelInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.panels = []
        self.goa_parent_panels = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("div", "section", "nav"):
            if "patient-goae-panel" in attrs.get("class", "").split():
                self.goa_parent_panels.append(
                    [a.get("data-customer-panel") for _, a in self.stack
                     if a.get("data-customer-panel")])
            if attrs.get("data-customer-panel"):
                self.panels.append(attrs)
        if tag not in {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                break


@override_settings(STORAGES={"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PatientTabVisibilityTests(SimpleTestCase):
    def render_patient(self):
        profile = SimpleNamespace(id=1123, pk=1123, first_name="Sophie", last_name="Muster",
                                  email="sophie@example.invalid", phone="", salutation="")
        return get_template("booking/app_management.html").render({
            "section": "patients", "section_title": "Kunden", "section_subtitle": "",
            "selected_customer": profile,
            "patient_appointments": [], "patient_records": [],
            "remote_customer_id": None, "view_only": False,
        })

    def test_patient_page_loads_actual_controller(self):
        html = self.render_patient()
        self.assertIn("clinic-patient-tabs-v2.js?v=20261020-tabs2", html)
        self.assertIn("clinic-patient-tabs-v2.css?v=20261020-tabs2", html)
        self.assertIn('data-customer-tab="records"', html)

    def test_default_panels_hidden_and_goae_only_under_records(self):
        parser = PanelInspector()
        parser.feed(self.render_patient())
        by_key = {}
        for attributes in parser.panels:
            by_key.setdefault(attributes["data-customer-panel"], []).append(attributes)
        self.assertEqual(set(by_key), {"overview","appointments","records","points"})
        for name in ("appointments", "records", "points"):
            self.assertTrue(all("hidden" in attrs for attrs in by_key[name]), name)
        self.assertTrue(all("hidden" not in attrs for attrs in by_key["overview"]))
        self.assertEqual(parser.goa_parent_panels, [["records"]])
        self.assertEqual(len(by_key["appointments"]), 1)
        self.assertEqual(len(by_key["records"]), 1)

    def test_controller_and_css_also_support_deep_linking(self):
        root = Path(__file__).resolve().parent.parent / "static" / "booking"
        js = (root / "clinic-patient-tabs-v2.js").read_text()
        css = (root / "clinic-patient-tabs-v2.css").read_text()
        self.assertIn("window.addEventListener('hashchange'", js)
        self.assertIn("showTab(requestedTab())", js)
        self.assertIn("panel.hidden = !active", js)
        self.assertIn("controls.hidden = !openControls", js)
        self.assertIn("position:relative!important", css)
        self.assertIn("[data-customer-panel][hidden]", css)
        self.assertIn("display:none!important", css)

    def test_goae_is_collapsible_for_unlinked_app_patient(self):
        html = self.render_patient()
        self.assertIn("patient-goae-details", html)
        self.assertIn("noch kein App Konto eindeutig verknüpft", html)
        self.assertIn("/verwaltung/app/invoices/", html)
