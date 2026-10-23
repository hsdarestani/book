"""Static regression checks for the unified A+ Esthetic administration skin."""
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class PremiumManagementDesignTests(SimpleTestCase):
    def test_all_management_templates_compile_and_load_skin(self):
        paths = (
            "admin_dashboard_lambo.html",
            "app_management.html",
            "admin_more.html",
            "dashboard.html",
            "doctor_appointments.html",
            "app_wallet_management.html",
        )
        for filename in paths:
            with self.subTest(template=filename):
                tpl = get_template(f"booking/{filename}")
                source = tpl.template.source
                self.assertIn('data-clinic-design="premium"', source)
                self.assertIn("clinic-premium-all-v2.css", source)

    def test_shared_sidebar_has_real_routes_and_access_guard(self):
        source = get_template("booking/_premium_sidebar.html").template.source
        for route in (
            "/verwaltung/dashboard/",
            "/verwaltung/kalender/",
            "/verwaltung/app/patients/",
            "/verwaltung/app/wallet/",
            "/verwaltung/app/reviews/",
            "/verwaltung/app/referrals/",
            "/verwaltung/app/invoices/",
            "/verwaltung/app/hero/",
            "/verwaltung/mehr/",
            "/verwaltung/einstellungen/",
        ):
            with self.subTest(route=route):
                self.assertIn(route, source)
        self.assertIn("{% if not view_only %}", source)

    def test_new_skin_uses_manifest_independent_static_links(self):
        templates = ("admin_dashboard_lambo.html", "app_management.html",
                     "admin_more.html", "dashboard.html",
                     "doctor_appointments.html", "app_wallet_management.html")
        for filename in templates:
            with self.subTest(filename=filename):
                source = get_template(f"booking/{filename}").template.source
                self.assertNotIn("{% static 'booking/clinic-premium", source)
                self.assertEqual(source.count("clinic-premium-all-v2.css"), 1)


    def test_no_new_admin_navigation_for_doctor(self):
        doctor = get_template("booking/doctor_appointments.html").template.source
        calendar = get_template("booking/dashboard.html").template.source
        self.assertNotIn('_premium_sidebar.html', doctor)
        self.assertIn('{% if not doctor_mode %}{% include "booking/_premium_sidebar.html"', calendar)
        self.assertIn('data-doctor-role="1"', doctor)

    def test_css_keeps_calendar_controls_scoped_and_mobile_responsive(self):
        css = (ROOT / "static" / "booking" / "clinic-premium-all-v2.css").read_text(encoding="utf-8")
        self.assertIn('data-admin-page="calendar"', css)
        self.assertIn("max-width:760px", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertNotIn("display:none!important}.sb-calendar-grid", css)
