import base64
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings


SLOTS = [
    {"variant": "frau", "label": "Damen", "image_url": "https://app.a-esthetic.de/api/mobile/dashboard-hero/frau/"},
    {"variant": "herr", "label": "Herren", "image_url": ""},
    {"variant": "default", "label": "Standard", "image_url": ""},
]


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class HomeHeroAdminTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("hero_editor", "admin@example.de", "password", is_staff=True)
        self.client.force_login(user)
        session = self.client.session
        session["aplus_app_admin"] = True
        session["aplus_admin_authorization"] = "Bearer test-token"
        session.save()

    @patch("booking.app_management_views._api")
    def test_hero_page_has_independent_mobile_scroll_region(self, mock_api):
        mock_api.return_value = {"ok": True, "hero_images": SLOTS}
        response = self.client.get("/verwaltung/app/hero/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('data-admin-page="hero"', html)
        self.assertIn('overflow-y:auto!important;', html)
        self.assertIn('flex:1 1 auto!important;', html)
        self.assertIn('height:0!important;', html)
        self.assertIn('touch-action:pan-y!important;', html)
        self.assertIn('overscroll-behavior-y:contain!important;', html)
        # Scope the special scrollport to the hero editor; calendar and wallet
        # must continue using their existing interaction/scroll contracts.
        self.assertIn('html[data-admin-page="hero"]:not([data-admin-page="calendar"]):not([data-admin-page="wallet"])', html)
        self.assertEqual(html.count('class="hero-admin-card"'), 3)

    @patch("booking.app_management_views._api")
    def test_editor_sees_three_slots_in_existing_admin(self, mock_api):
        mock_api.return_value = {"ok": True, "hero_images": SLOTS}
        response = self.client.get("/verwaltung/app/hero/")
        self.assertEqual(response.status_code, 200, response.content[:500])
        for label in ("Damen", "Herren", "Standard", "Startseitenbilder"):
            self.assertContains(response, label)
        self.assertContains(response, "enctype=\"multipart/form-data\"")
        mock_api.assert_called_with(response.wsgi_request, "dashboard-hero/")

    @patch("booking.app_management_views._api")
    def test_valid_image_is_forwarded_to_authenticated_aesthetic_service(self, mock_api):
        mock_api.return_value = {"ok": True, "hero_images": SLOTS}
        photo = b"image-for-forwarding"
        response = self.client.post("/verwaltung/app/hero/", {
            "action": "hero_upload",
            "variant": "herr",
            "hero_image": SimpleUploadedFile("mann.jpg", photo, content_type="image/jpeg"),
        })
        self.assertEqual(response.status_code, 302)
        endpoint = mock_api.call_args.args[1]
        payload = mock_api.call_args.kwargs["payload"]
        self.assertEqual(endpoint, "dashboard-hero/")
        self.assertEqual(payload["variant"], "herr")
        self.assertEqual(payload["image_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(payload["image_data"]), photo)

    @patch("booking.app_management_views._api")
    def test_clear_only_one_hero_slot(self, mock_api):
        response = self.client.post("/verwaltung/app/hero/", {
            "action": "hero_clear", "variant": "frau"
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mock_api.call_args.kwargs["payload"], {"variant": "frau", "action": "clear"})

    @patch("booking.app_management_views._api")
    def test_unsupported_image_rejected_before_api_call(self, mock_api):
        response = self.client.post("/verwaltung/app/hero/", {
            "action": "hero_upload",
            "variant": "frau",
            "hero_image": SimpleUploadedFile("bad.svg", b"<svg/>", content_type="image/svg+xml"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "JPG, PNG oder WebP", status_code=400)
        # The GET only refreshes the form; an invalid image is never posted.
        self.assertEqual(mock_api.call_count, 1)
        self.assertEqual(mock_api.call_args.args[1], "dashboard-hero/")
        self.assertNotIn("method", mock_api.call_args.kwargs)
