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
