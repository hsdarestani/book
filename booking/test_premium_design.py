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
                expected = "clinic-premium-all-v2.css?v=20261024-gutters1"
                self.assertIn(expected, src)

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

    def test_mobile_management_gutters_are_single_source_of_truth(self):
        css = (ROOT / "static" / "booking" / "clinic-premium-all-v2.css").read_text(encoding="utf-8")
        mobile = css.split("Mobile management alignment, 2026-10-24", 1)[1]
        self.assertIn('not([data-admin-page="calendar"])', mobile)
        self.assertIn('not([data-doctor-role])', mobile)
        self.assertIn('main.admin-shell.sb-admin-shell.app-management-shell', mobile)
        self.assertIn('padding-left:max(14px,env(safe-area-inset-left))!important;', mobile)
        self.assertIn('padding-right:max(14px,env(safe-area-inset-right))!important;', mobile)
        self.assertIn('main.app-management-shell > :is(', mobile)
        self.assertIn('.app-patient-layout[data-customer-panel=records] > .app-core-panel', mobile)
        self.assertIn('.app-patient-layout[data-customer-panel=records] .patient-goae-panel', mobile)
        self.assertNotIn('width:calc(100% - 24px)', mobile)
        self.assertNotIn('margin:0 12px', mobile)
        self.assertNotIn('overflow-x:hidden', mobile)
        self.assertNotIn('transform:none', mobile)

    def test_records_markup_no_longer_introduces_double_mobile_insets(self):
        source = get_template("booking/app_management.html").template.source
        component_rules = source.split('id="patient-upload-studio-inline-v2"', 1)[1].split('</style>', 1)[0]
        self.assertIn('.app-patient-layout[data-customer-panel=records]>.app-core-panel', component_rules)
        self.assertIn('.app-patient-layout[data-customer-panel=records] .patient-goae-panel', component_rules)
        self.assertNotIn('width:calc(100% - 24px)', component_rules)
        self.assertNotIn('margin:0 12px', component_rules)

    def test_signature_dashboard_uses_live_values_and_actionable_links(self):
        template = get_template("booking/admin_dashboard_lambo.html").template.source
        self.assertIn('class="premium-welcome signature-hero"', template)
        self.assertIn('id="premium-dashboard-title"', template)
        self.assertIn('class="signature-hero-emblem"', template)
        self.assertIn('clinic-premium-dashboard-v3.css?v=20261024-signature1', template)
        self.assertIn('class="command-stats premium-stats signature-stats"', template)
        for value in ("{{ today_count }}", "{{ upcoming_count }}", "{{ patient_count }}",
                      "{{ contact_group_count }}", "{{ anonymous_booking_count }}"):
            self.assertIn(value, template)
        self.assertIn('href="/verwaltung/kalender/" class="signature-stat-link"', template)
        self.assertIn('href="/verwaltung/app/patients/" class="signature-stat-link"', template)
        self.assertIn('role="search"', template)
        self.assertIn('name="q" value="{{ query }}"', template)
        self.assertIn('next_day_appointments', template)
        self.assertIn('class="shortcut-grid"', template)

    def test_signature_dashboard_styles_are_scoped_responsive_and_not_decorative_only(self):
        css = (ROOT / "static" / "booking" / "clinic-premium-dashboard-v3.css").read_text(encoding="utf-8")
        self.assertIn('html[data-clinic-design="premium"][data-admin-page="dashboard"]', css)
        self.assertIn('--signature-forest', css)
        self.assertIn('.signature-hero-emblem', css)
        self.assertIn('.signature-stat-link:hover', css)
        self.assertIn('.signature-search-field input', css)
        self.assertIn('.shortcut-grid>a:last-child', css)
        self.assertIn('@media (max-width:760px)', css)
        self.assertIn('@media(max-width:365px)', css)
        self.assertIn('prefers-reduced-motion', css)
        self.assertNotIn('overflow-x:hidden!important', css)

    def test_signature_dashboard_loads_after_other_premium_styles(self):
        template = get_template("booking/admin_dashboard_lambo.html").template.source
        self.assertLess(template.index('clinic-premium-all-v2.css'), template.index('clinic-premium-dashboard-v3.css'))
        middleware = (ROOT / "booking" / "app_admin_middleware.py").read_text(encoding="utf-8")
        self.assertIn('(?:v1|all-v2|dashboard-v3)', middleware)
