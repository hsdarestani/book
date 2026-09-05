from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase


class AppAdminSsoTests(TestCase):
    def test_entry_never_exposes_token_server_side(self):
        response = self.client.get('/verwaltung/app/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "location.hash")
        self.assertContains(response, "/verwaltung/app-sso/")
        self.assertEqual(response['Cache-Control'].find('no-store') >= 0, True)

    @patch('booking.app_admin_api._verify_admin')
    def test_verified_aesthetic_admin_gets_book_staff_session(self, verify):
        verify.return_value = {
            'id': 77,
            'name': 'A Plus Admin',
            'email': 'admin@example.test',
            'superuser': True,
        }
        response = self.client.post(
            '/verwaltung/app-sso/',
            HTTP_AUTHORIZATION='Bearer test-token-that-is-long-enough',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], '/verwaltung/kalender/')

        user = User.objects.get(username='aplus_app_admin_77')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.session.get('aplus_app_admin'), True)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.pk))
        self.assertEqual(
            self.client.session.get('aplus_admin_authorization'),
            'Bearer test-token-that-is-long-enough',
        )
        self.assertEqual(response.cookies['aplus_admin_ui'].value, '1')

    @patch('booking.app_admin_api._verify_admin', return_value=None)
    def test_unverified_actor_is_rejected(self, _verify):
        response = self.client.post(
            '/verwaltung/app-sso/',
            HTTP_AUTHORIZATION='Bearer invalid-token-that-is-long-enough',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertFalse(User.objects.filter(username__startswith='aplus_app_admin_').exists())