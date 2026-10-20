from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.template.loader import get_template

from .models import Customer


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class SameDomainInvoicesTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="invoice-book-admin", is_staff=True)
        self.url = "/verwaltung/app/invoices/"
        self.data = {
            "ok": True,
            "settings": {
                "ready_for_issue": False, "invoice_prefix": "RE",
                "next_sequence": 1, "company_name": "Privatpraxis Ariane Regaei",
                "street": "Stiftstrasse 14", "postal_code": "60313",
                "city": "Frankfurt am Main",
            },
            "stats": {"issued": 0, "drafts": 1, "configured_services": 0,
                      "active_services": 0},
            "services": [],
            "customers": [{"id": 1, "name": "Anna Muster",
                           "email": "patient@example.test"}],
            "invoices": [{"id": 3, "number": "", "status": "draft",
                          "billing_method": "goae", "status_label": "Entwurf",
                          "customer_name": "Anna Muster", "customer_email": "patient@example.test",
                          "service_date": "20.10.2026", "total": "23,00"}],
        }

    @patch("booking.app_management_views._billing_api")
    def test_book_admin_views_rechnungen_without_app_bearer_and_without_redirect(self, billing):
        billing.return_value = self.data
        self.client.force_login(self.staff)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200, res.content[:400])
        self.assertContains(res, "Rechnungen direkt in der Verwaltung")
        self.assertContains(res, "Rechnung nach GOÄ")
        self.assertContains(res, "/verwaltung/app/invoices/3/pdf/")
        self.assertNotIn("office.a-esthetic.de", res.content.decode("utf-8"))
        billing.assert_called_once_with(res.wsgi_request, "billing/")

    @patch("booking.app_management_views._billing_api")
    def test_creates_physician_invoice_draft_on_same_domain(self, billing):
        self.client.force_login(self.staff)
        res = self.client.post(self.url, {
            "action": "billing_create_goae", "customer_id": 1,
            "service_date": "2026-10-20", "goae_number": "1",
            "goae_description": "Beratung", "goae_base_eur": "10",
            "goae_factor": "2,30", "goae_vat_rate": "0",
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], "/verwaltung/app/invoices/?notice=goae_draft")
        args, kwargs = billing.call_args
        self.assertEqual(args[1], "billing/invoices/")
        self.assertEqual(kwargs["payload"]["billing_method"], "goae")
        self.assertEqual(kwargs["payload"]["customer_id"], 1)

    @patch("booking.invoice_bridge._request_bridge", return_value=b"%PDF-1.4\nTEST")
    def test_invoice_pdf_stays_authenticated_on_booking(self, bridge):
        self.client.force_login(self.staff)
        res = self.client.get("/verwaltung/app/invoices/42/pdf/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertIn("no-store", res["Cache-Control"])

    def test_pdf_requires_staff_login(self):
        res = self.client.get("/verwaltung/app/invoices/42/pdf/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/verwaltung/login/", res["Location"])

    def test_calendar_has_shared_header_but_calendar_grid_is_unchanged(self):
        source = get_template("booking/dashboard.html").template.source
        self.assertIn("{% include \"booking/_clinic_web_header_v3.html\" %}", source)
        self.assertIn("clinic-calendar-topbar-v1.css", source)
        self.assertIn('data-admin-page="calendar"', source)
        grid = get_template("booking/_shared_admin_calendar.html").template.source
        self.assertIn('class="sb-calendar-shell', grid)
        self.assertNotIn("clinic-header-v3", grid)
        self.assertNotIn("clinic-calendar-topbar", grid)
