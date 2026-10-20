from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.template.loader import get_template

from . import app_wallet_views


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class ReadableClinicUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="readability-admin", is_staff=True)

    def test_patient_panels_hidden_even_with_legacy_important_display_rules(self):
        template = get_template("booking/app_management.html").template.source
        self.assertIn("clinic-readable-ui-v1.css", template)
        css = open("static/booking/clinic-readable-ui-v1.css", encoding="utf-8").read()
        self.assertIn('[data-customer-panel][hidden]', css)
        self.assertIn("[data-customer-control-grid][hidden]", css)
        self.assertIn("display:none!important", css)
        self.assertNotIn("clinic-readable-ui-v1", get_template("booking/_shared_admin_calendar.html").template.source)

    def test_rechnungen_has_searchable_collapsed_service_editors(self):
        template = get_template("booking/app_management.html").template.source
        self.assertIn("data-clinic-service-search", template)
        self.assertIn("<details class=\"billing-service-card clinic-service-card\"", template)
        self.assertIn("clinic-readable-ui-v1.js", template)
        self.assertIn("data-clinic-service-count", template)

    @patch("booking.app_wallet_views._wallet_api")
    def test_desktop_wallet_works_without_native_app_login(self, api):
        api.return_value = {"ok": True, "customers": []}
        self.client.force_login(self.user)
        res = self.client.get("/verwaltung/app/wallet/")
        self.assertEqual(res.status_code, 200, res.content[:500])
        self.assertContains(res, "A+ Punkte")
        self.assertNotIn("Bitte Verwaltung erneut aus der A+ App öffnen", res.content.decode())
        api.assert_called_once()

    def test_wallet_anonymous_redirects_to_staff_login(self):
        res = self.client.get("/verwaltung/app/wallet/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/verwaltung/login/", res["Location"])

    @patch("booking.app_wallet_views._wallet_api")
    def test_wallet_coin_correction_uses_bounded_route(self, api):
        self.client.force_login(self.user)
        res = self.client.post("/verwaltung/app/wallet/", {
            "action": "points_adjust", "customer_id": "4",
            "wallet_id": "4", "point_delta": "50",
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res["Location"].startswith("/verwaltung/app/wallet/"))
        self.assertEqual(api.call_args.args[1], "customers/4/")
        self.assertEqual(api.call_args.kwargs["payload"], {"coin_delta": 50})
