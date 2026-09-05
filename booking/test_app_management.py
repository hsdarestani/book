from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase


class AppManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='aplus_app_admin_test', password='x', is_staff=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer test-admin-token'
        session.save()

    @patch('booking.app_management_views._api')
    def test_customer_club_management_renders_inside_book_ui(self, api):
        api.side_effect = [
            {
                'ok': True,
                'stats': {'customers': 1, 'active_packages': 2, 'pending_rewards': 0, 'push_devices': 1},
                'modules': [],
            },
            {
                'ok': True,
                'customers': [{
                    'id': 10,
                    'name': 'Test Member',
                    'email': 'member@example.test',
                    'phone': '',
                    'member_number': 'AP-TEST',
                    'tier': 'A+ Member',
                    'member_status': 'active',
                    'coins': 200,
                    'credit_cents': 500,
                    'active_packages': 2,
                    'devices': 1,
                }],
            },
        ]
        response = self.client.get('/verwaltung/app/club/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer Club')
        self.assertContains(response, 'Test Member')
        self.assertContains(response, '/verwaltung/kalender/')
        self.assertContains(response, 'Push &amp; Mitteilungen')
        self.assertNotContains(response, 'nav-center-disc')

    def test_regular_book_staff_cannot_open_app_management(self):
        session = self.client.session
        session.pop('aplus_app_admin', None)
        session.pop('aplus_admin_authorization', None)
        session.save()
        response = self.client.get('/verwaltung/app/club/')
        self.assertEqual(response.status_code, 403)

    @patch('booking.app_management_views._api')
    def test_module_toggle_posts_to_aesthetic_admin_api(self, api):
        api.side_effect = [
            {'ok': True, 'module': {'key': 'events', 'enabled': False, 'customer_visible': False}},
        ]
        response = self.client.post('/verwaltung/app/modules/', {
            'action': 'module_update',
            'key': 'events',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verwaltung/app/modules/', response['Location'])
        api.assert_called_once()