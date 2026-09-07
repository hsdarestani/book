from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Customer, Service, StaffMember


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class FullManagementSurfaceRegressionTests(TestCase):
    """High-level regression guard for the management surfaces used by the app."""

    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username='full-regression-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer regression-admin-token'
        session.save()

        self.service = Service.objects.create(
            name='Regression Beratung',
            slug='regression-beratung',
            duration_minutes=30,
            buffer_minutes=0,
            price_label='50 €',
            active=True,
            bookable=True,
            sort_order=1,
        )
        self.staff = StaffMember.objects.create(
            display_name='Regression Ärztin',
            role='doctor',
            active=True,
            sort_order=1,
        )
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name='Sophie',
            last_name='Regression',
            email='sophie.regression@example.test',
            phone='+491701234567',
        )

    def _fake_aplus_api(self, request, endpoint, method='GET', payload=None, query=None):
        endpoint = endpoint.lstrip('/')
        if endpoint == 'customers/':
            return {
                'ok': True,
                'customers': [{
                    'id': 10,
                    'name': 'Sophie Regression',
                    'email': self.customer.email,
                    'phone': self.customer.phone,
                    'member_number': 'AP-REGRESSION',
                    'member_status': 'active',
                    'credit_cents': 5500,
                }],
            }
        if endpoint == 'customers/10/wallet-history/':
            return {
                'ok': True,
                'customer': {
                    'id': 10,
                    'name': 'Sophie Regression',
                    'email': self.customer.email,
                    'member_number': 'AP-REGRESSION',
                    'credit_cents': 5500,
                },
                'transactions': [{
                    'direction': 'in',
                    'amount_cents': 6500,
                    'coin_amount': 0,
                    'description': 'A+ Startguthaben',
                    'kind_label': 'Guthaben',
                    'reference': '',
                    'created_at': '2026-09-07T12:00:00+00:00',
                }],
            }
        if endpoint == 'reviews/':
            return {'ok': True, 'reviews': []}
        if endpoint == 'referrals/':
            return {'ok': True, 'referrals': []}
        return {'ok': True}

    def test_legacy_management_routes_render_and_customer_sheet_is_upgraded(self):
        for path in ('/verwaltung/kalender/', '/verwaltung/buchungen/', '/verwaltung/kunden/'):
            with self.subTest(path=path):
                response = self.client.get(path, {'staff': self.staff.pk})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="sb-mobile-bar')
                self.assertContains(response, 'admin-shell-v10.css')

        customers = self.client.get('/verwaltung/kunden/', {'staff': self.staff.pk})
        self.assertContains(customers, 'data-modal="customer"')
        self.assertContains(customers, 'Neuen Kunden hinzufügen')
        self.assertContains(customers, 'name="action" value="add_customer"')

    def test_new_customer_functional_flow_persists_and_redirects(self):
        response = self.client.post('/verwaltung/kunden/', {
            'action': 'add_customer',
            'first_name': 'Neue',
            'last_name': 'Kundin',
            'email': 'neue.kundin@example.test',
            'phone': '+4969123456',
            'return_to': 'kunden',
        })
        self.assertEqual(response.status_code, 302)
        saved = Customer.objects.get(email='neue.kundin@example.test')
        self.assertEqual(saved.first_name, 'Neue')
        self.assertEqual(saved.last_name, 'Kundin')
        # The legacy form deliberately returns to the customer anchor on the
        # canonical admin document; client-side routing then normalizes the URL.
        self.assertIn('notice=customer', response['Location'])
        self.assertTrue(response['Location'].endswith('#kunden'))

    @patch('booking.app_management_views._api')
    def test_focused_aplus_sections_have_one_header_contract(self, api):
        api.side_effect = self._fake_aplus_api
        paths = (
            '/verwaltung/app/patients/',
            '/verwaltung/app/referrals/',
            '/verwaltung/app/reviews/',
            '/verwaltung/app/wallet/',
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.content[:300])
                self.assertContains(response, 'class="sb-mobile-bar app-mobile-bar"')
                self.assertContains(response, 'admin-shell-v10.css')
                self.assertContains(response, 'data-drawer-open')
                self.assertContains(response, 'data-drawer')

    def test_patient_detail_keeps_management_header_and_drawer(self):
        response = self.client.get(f'/verwaltung/patienten/{self.customer.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="sb-mobile-bar app-mobile-bar"')
        self.assertContains(response, 'data-drawer-open')
        self.assertContains(response, 'data-drawer')
        self.assertContains(response, 'admin-patient-detail-v7.css')

    @patch('booking.app_management_views._api')
    def test_wallet_history_functional_contract_renders_real_transaction_data(self, api):
        api.side_effect = self._fake_aplus_api
        response = self.client.get('/verwaltung/app/wallet/?q=Sophie&wallet=10')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="wallet-history"')
        self.assertContains(response, 'A+ Startguthaben')
        self.assertContains(response, '+65,00 €')
        self.assertContains(response, '55,00')

    def test_calendar_remains_isolated_and_keeps_add_action(self):
        response = self.client.get('/verwaltung/kalender/', {'staff': self.staff.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-calendar-stability-v8.css')
        self.assertContains(response, 'class="sb-fab"')
        self.assertContains(response, 'data-fab')
        self.assertNotContains(response, 'admin-patient-detail-v7.css')
        self.assertNotContains(response, 'admin-fast-drawer-v7.js')

    def test_non_calendar_pages_do_not_expose_calendar_view_switcher(self):
        for path in ('/verwaltung/buchungen/', '/verwaltung/kunden/'):
            response = self.client.get(path, {'staff': self.staff.pk})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'data-view-menu-open')
            self.assertNotContains(response, 'data-view-menu')
            self.assertContains(response, 'admin-scroll-recovery-v9.css')

    def test_logout_clears_admin_bridge_state(self):
        response = self.client.get('/verwaltung/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('aplus_app_admin', self.client.session)
        self.assertNotIn('aplus_admin_authorization', self.client.session)
