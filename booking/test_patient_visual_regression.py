"""Protect the patient profile against the exact live UI regressions:
blue unstyled anchors, tiny text, massive mobile checkbox, sticky tab bar.
"""
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static" / "booking"


class PatientVisualRegressionTests(SimpleTestCase):
    def test_customer_view_has_native_buttons_and_independent_inline_styles(self):
        tpl = get_template("booking/app_management.html").template.source
        self.assertIn("clinic-patient-critical-v4", tpl)
        self.assertIn("clinic-patient-finish-v4.css", tpl)
        self.assertIn('#patient-tab-nav.customer-profile-tabs .patient-tab-button', tpl)
        self.assertIn("text-decoration:none!important", tpl)
        self.assertIn("position:static!important", tpl)
        self.assertIn("grid-template-columns:repeat(4", tpl)
        self.assertIn('<input type="hidden" name="tab" value="records">', tpl)
        self.assertIn('data-clinic-profile-build="4"', tpl)
        self.assertIn('class="patient-profile-single"', tpl)
        self.assertIn("display:block!important;width:100%!important", tpl)
        self.assertNotIn('<a href="?customer=', tpl)
        self.assertIn("{% if section == 'patients' %}", tpl)

    def test_checkbox_is_normal_size_and_remains_accessible(self):
        tpl = get_template("booking/app_management.html").template.source
        self.assertIn('type="checkbox" name="shared_with_customer"', tpl)
        self.assertIn('label class="app-share-check patient-studio-share"', tpl)
        self.assertIn('patient-upload-studio-inline-v2', tpl)
        style = (STATIC / "clinic-patient-finish-v3.css").read_text()
        self.assertIn('label.app-share-check>input[type="checkbox"]', style)
        self.assertIn("width:21px!important;height:21px!important", style)
        self.assertIn("min-width:21px!important;min-height:21px!important", style)
        self.assertIn("accent-color:#b88a39!important", style)
        self.assertIn("content:none!important", style)

    def test_readable_text_and_mobile_rules_included(self):
        css = (STATIC / "clinic-patient-finish-v3.css").read_text()
        self.assertIn("patient-command-copy p", css)
        self.assertIn("patient-appointment-list>.empty", css)
        self.assertIn("wa-template-list>a small", css)
        self.assertIn("@media(max-width:650px)", css)
        self.assertIn("app-patient-layout[data-customer-panel=\"records\"]", css)
        self.assertIn("#patient-tab-nav.customer-profile-tabs", css)

    def test_calendar_template_does_not_receive_patient_css(self):
        calendar = get_template("booking/dashboard.html").template.source
        self.assertNotIn("clinic-patient-finish-v4.css", calendar)
        self.assertNotIn("clinic-patient-critical-v4", calendar)
