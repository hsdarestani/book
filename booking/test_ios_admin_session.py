"""Regression checks for persistent iPhone admin SSO sessions only."""
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class IosAppAdminSessionTests(TestCase):
    identity = {"id": 912341, "name": "Test Admin", "email": "ios-admin@example.test"}

    def sign_in(self, agent):
        with patch("booking.app_admin_api._verify_admin", return_value=self.identity):
            return self.client.post(reverse("booking:app_admin_sso"), HTTP_USER_AGENT=agent)

    def test_iphone_admin_sso_persists_cookie_and_renews_on_visit(self):
        agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
        login = self.sign_in(agent)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(self.client.session.get("aplus_app_admin"))
        self.assertGreater(self.client.session.get_expiry_age(), 29 * 24 * 60 * 60)
        self.assertIn(settings.SESSION_COOKIE_NAME, login.cookies)

        dashboard = self.client.get(reverse("booking:admin_dashboard"), HTTP_USER_AGENT=agent)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(settings.SESSION_COOKIE_NAME, dashboard.cookies)

        logout = self.client.get(reverse("booking:admin_logout"), HTTP_USER_AGENT=agent)
        self.assertEqual(logout.status_code, 302)
        self.assertNotIn("aplus_app_admin", self.client.session)

    def test_android_admin_sso_keeps_existing_expiry(self):
        agent = "Mozilla/5.0 (Linux; Android 16; Mobile)"
        login = self.sign_in(agent)
        self.assertEqual(login.status_code, 200)
        self.assertLess(self.client.session.get_expiry_age(), 29 * 24 * 60 * 60)

        dashboard = self.client.get(reverse("booking:admin_dashboard"), HTTP_USER_AGENT=agent)
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, dashboard.cookies)
