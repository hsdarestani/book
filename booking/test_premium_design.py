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

    def test_mobile_navigation_hides_desktop_header_and_preserves_contrast(self):
        css = (ROOT / "static" / "booking" / "clinic-premium-all-v2.css").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:980px)", css)
        self.assertIn('body.admin-body .clinic-header-v3,', css)
        self.assertIn("display:none!important;", css)
        self.assertIn('body.admin-body>.sb-mobile-bar{', css)
        self.assertIn("background:#fffcf7!important;", css)
        self.assertIn(".sb-mobile-title{", css)
        self.assertIn("-webkit-text-fill-color:#29251f!important;", css)
        self.assertIn(".billing-command .billing-command-copy h2{", css)
        self.assertIn("-webkit-text-fill-color:#29241e!important;", css)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))!important;", css)

    def test_mobile_premium_css_cache_key_on_all_admin_screens(self):
        paths = (
            "admin_dashboard_lambo.html", "app_management.html",
            "admin_more.html", "dashboard.html",
            "doctor_appointments.html", "app_wallet_management.html",
        )
        for filename in paths:
            with self.subTest(template=filename):
                src = get_template(f"booking/{filename}").template.source
                self.assertIn("clinic-premium-all-v2.css?v=20261023-workspace-v3", src)

    def test_desktop_workspace_has_single_brand_and_legible_hero(self):
        css = (ROOT / "static" / "booking" / "clinic-premium-all-v2.css").read_text(encoding="utf-8")
        self.assertIn("A+ ESTHETIC WORKSPACE / EXPERIENCE V3", css)
        self.assertIn("premium-sidebar-nav>a", css)
        self.assertIn("background:linear-gradient(180deg,#242b29", css)
        self.assertIn("premium-utility-context", css)
        self.assertIn("clinic-header-v3 .clinic-header-brand", css)
        self.assertIn("display:none!important", css)
        self.assertIn(".premium-welcome h1", css)
        self.assertIn("color:#fffaf0!important", css)
        self.assertIn(".sb-calendar-block.is-blocked", css)

    def test_invoice_workflow_is_usable_without_wall_of_forms(self):
        source = get_template("booking/app_management.html").template.source
        self.assertIn("{% if section != 'invoices' %}", source)
        self.assertIn("<h2>Rechnungen verwalten</h2>", source)
        self.assertIn('class="premium-settings-disclosure"', source)
        self.assertIn('data-premium-catalog', source)
        self.assertIn('data-clinic-service-list', source)
        self.assertIn('data-billing-create-form', source)
        self.assertIn('name="action" value="billing_settings"', source)
        self.assertIn('name="action" value="billing_service"', source)
        self.assertIn("catalog.open=true", source)
        self.assertIn('billing-customer-modal', source)

    def test_one_context_header_for_premium_desktop(self):
        source = get_template("booking/_clinic_web_header_v3.html").template.source
        self.assertIn('class="premium-utility-context"', source)
        self.assertIn("section_title|default", source)
