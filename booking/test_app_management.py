from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class AppManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='aplus_app_admin_test', password='x', is_staff=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer test-admin-token'
        session.save()

    @patch('booking.app_management_views._api')
    def test_wallet_management_renders_inside_book_ui(self, api):
        api.return_value = {
            'ok': True,
            'customers': [{
                'id': 10,
                'name': 'Test Patient',
                'email': 'patient@example.test',
                'phone': '',
                'credit_cents': 5000,
            }],
        }
        response = self.client.get('/verwaltung/app/wallet/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A+ Wallet')
        self.assertContains(response, 'Test Patient')
        self.assertContains(response, '/verwaltung/kalender/')
        self.assertContains(response, 'Google Bewertungen')
        self.assertNotContains(response, 'Rewards')
        self.assertNotContains(response, 'Pakete')
        self.assertNotContains(response, 'App-Module')

    def test_regular_book_staff_cannot_open_app_management(self):
        session = self.client.session
        session.pop('aplus_app_admin', None)
        session.pop('aplus_admin_authorization', None)
        session.save()
        response = self.client.get('/verwaltung/app/wallet/')
        self.assertEqual(response.status_code, 403)

    @patch('booking.app_management_views._api')
    def test_wallet_adjust_posts_credit_only(self, api):
        api.return_value = {'ok': True, 'customer': {'id': 10, 'credit_cents': 7500}}
        response = self.client.post('/verwaltung/app/wallet/', {
            'action': 'wallet_adjust',
            'customer_id': '10',
            'credit_delta_eur': '25.00',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verwaltung/app/wallet/', response['Location'])
        api.assert_called_once_with(self.client.request().wsgi_request if False else response.wsgi_request, 'customers/10/', method='POST', payload={'credit_delta_cents': 2500})

    @patch('booking.app_management_views._api')
    def test_reviews_render(self, api):
        api.return_value = {'ok': True, 'reviews': [{'id': 4, 'customer': 'Patient', 'email': 'p@example.test', 'status': 'submitted', 'status_label': 'Als abgegeben markiert', 'rating': 5, 'review_text': '', 'submitted_at': '2026-09-06T12:00:00+00:00', 'opened_at': '2026-09-06T11:00:00+00:00', 'google_review_url': ''}]}
        response = self.client.get('/verwaltung/app/reviews/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google Bewertungen')
        self.assertContains(response, 'Patient')
