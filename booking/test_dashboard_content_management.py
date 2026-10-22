from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class DashboardContentManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="content-admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)

    @patch("booking.admin_dashboard_views.app_management_views._api")
    def test_banner_cover_is_forwarded_to_app_api(self, api):
        cover = SimpleUploadedFile("special.png", b"\x89PNG\r\n\x1a\ncover", content_type="image/png")
        response = self.client.post("/verwaltung/dashboard/", {
            "action": "banner_save",
            "title": "Special",
            "text": "Test",
            "active": "on",
            "sort_order": "100",
            "cover_image": cover,
        })
        self.assertEqual(response.status_code, 302)
        payload = api.call_args.kwargs["payload"]
        self.assertEqual(payload["cover_type"], "image/png")
        self.assertEqual(payload["cover_name"], "special.png")
        self.assertTrue(payload["cover_data"])

    @patch("booking.admin_dashboard_views.app_management_views._api")
    def test_banner_cover_rejects_unsupported_file(self, api):
        cover = SimpleUploadedFile("bad.svg", b"<svg></svg>", content_type="image/svg+xml")
        response = self.client.post("/verwaltung/dashboard/", {
            "action": "banner_save",
            "title": "Special",
            "sort_order": "100",
            "cover_image": cover,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "JPG-, PNG- oder WebP")
        api.assert_not_called()

    @patch("booking.admin_dashboard_views.app_management_views._api")
    def test_dashboard_does_not_wait_for_unused_banner_api(self, remote):
        session = self.client.session
        session["aplus_app_admin"] = True
        session.save()
        response = self.client.get("/verwaltung/dashboard/")
        self.assertEqual(response.status_code, 200)
        remote.assert_not_called()

    def test_dashboard_reuses_customer_snapshot(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import Customer, WhatsAppTemplate
        Customer.objects.create(first_name="Anna", last_name="Muster",
                                email="anna.speed@example.com", phone="+491511234567")
        Customer.objects.create(first_name="Anne", last_name="Muster",
                                email="anne.speed@example.com", phone="+491511234567")
        WhatsAppTemplate.objects.create(name="Info", body="Hallo {vorname}", active=True)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/verwaltung/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patient suchen")
        customer_queries = [
            q for q in captured.captured_queries
            if 'FROM "booking_customer"' in q["sql"] and q["sql"].lstrip().startswith("SELECT")
        ]
        self.assertEqual(len(customer_queries), 1, customer_queries)

    def test_middleware_skips_services_when_no_select_options(self):
        from types import SimpleNamespace
        from django.http import HttpResponse
        from django.test import RequestFactory
        from .app_admin_middleware import APlusAdminNavigationMiddleware
        request = RequestFactory().get("/verwaltung/dashboard/")
        request.user = self.admin
        request.session = {"aplus_app_admin": True}
        request.resolver_match = SimpleNamespace(url_name="dashboard")
        middleware = APlusAdminNavigationMiddleware(
            lambda req: HttpResponse("<html><head></head><body>Dashboard</body></html>")
        )
        with patch("booking.app_admin_middleware.Service.objects.filter") as services:
            response = middleware(request)
        self.assertEqual(response.status_code, 200)
        services.assert_not_called()

    def test_service_dropdown_enrichment_keeps_exact_names_and_selection(self):
        from types import SimpleNamespace
        from django.http import HttpResponse
        from django.test import RequestFactory
        from .app_admin_middleware import APlusAdminNavigationMiddleware
        request = RequestFactory().get("/verwaltung/kalender/")
        request.user = self.admin
        request.session = {"aplus_app_admin": True}
        request.resolver_match = SimpleNamespace(url_name="calendar")
        content = ('<html><head></head><body><select>'
                   '<option value="17">Gesicht &amp; Hals</option>'
                   '<option value="17" selected>Gesicht &amp; Hals</option>'
                   '<option value="17">Something else</option>'
                   '</select></body></html>')
        middleware = APlusAdminNavigationMiddleware(lambda req: HttpResponse(content))
        with patch("booking.app_admin_middleware.Service.objects.filter") as services:
            services.return_value.only.return_value = [
                SimpleNamespace(pk=17, name="Gesicht & Hals", duration_minutes=45)
            ]
            response = middleware(request)
        page = response.content.decode()
        self.assertIn('<option value="17">Gesicht &amp; Hals · 45 Min.</option>', page)
        self.assertIn('<option value="17" selected>Gesicht &amp; Hals · 45 Min.</option>', page)
        self.assertIn('<option value="17">Something else</option>', page)
