from pathlib import Path
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import AdminAccessProfile, Customer, DailyAvailabilityOverride, Service, StaffMember, WhatsAppTemplate


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class FullManagementSurfaceRegressionTests(TestCase):
    """High-level guard for the user + admin management surfaces."""

    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username='full-regression-admin', password='test-password', is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer regression-admin-token'
        session.save()

        self.service = Service.objects.create(
            name='Regression Beratung', slug='regression-beratung', duration_minutes=30,
            buffer_minutes=0, price_label='50 €', active=True, bookable=True, sort_order=1,
        )
        self.staff = StaffMember.objects.create(display_name='Regression Ärztin', role='doctor', active=True, sort_order=1)
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name='Sophie', last_name='Regression', email='sophie.regression@example.test', phone='+491701234567',
        )

    def _fake_aplus_api(self, request, endpoint, method='GET', payload=None, query=None):
        endpoint = endpoint.lstrip('/')
        if endpoint == 'customers/':
            return {
                'ok': True,
                'customers': [{
                    'id': 10, 'name': 'Sophie Regression', 'email': self.customer.email,
                    'phone': self.customer.phone, 'member_number': 'AP-REGRESSION',
                    'member_status': 'active', 'coins': 550,
                }],
            }
        if endpoint == 'customers/10/wallet-history/':
            return {
                'ok': True,
                'customer': {'id': 10, 'name': 'Sophie Regression', 'email': self.customer.email, 'member_number': 'AP-REGRESSION', 'coins': 550},
                'transactions': [{
                    'direction': 'in', 'amount_cents': 0, 'coin_amount': 250,
                    'description': 'Google Bewertung verifiziert', 'kind': 'coin',
                    'reference': 'review:4', 'created_at': '2026-09-07T12:00:00+00:00',
                }],
            }
        if endpoint == 'reviews/':
            return {'ok': True, 'reviews': []}
        if endpoint == 'referrals/':
            return {'ok': True, 'referrals': []}
        if endpoint == 'dashboard-banners/':
            return {'ok': True, 'banners': [{'id': 1, 'title': 'Autumn Glow', 'text': 'Special', 'image_url': '', 'cta_label': 'Termin', 'cta_url': '', 'active': True, 'starts_at': '2026-09-01T09:00:00+00:00', 'ends_at': '2026-10-31T22:00:00+00:00', 'sort_order': 10}]}
        return {'ok': True}

    def test_legacy_calendar_and_list_routes_stay_stable(self):
        for path in ('/verwaltung/', '/verwaltung/kalender/', '/verwaltung/buchungen/', '/verwaltung/kunden/'):
            with self.subTest(path=path):
                response = self.client.get(path, {'staff': self.staff.pk})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="sb-mobile-bar')
                self.assertContains(response, 'admin-shell-v10.css')

    def test_new_customer_functional_flow_persists_and_redirects(self):
        response = self.client.post('/verwaltung/kunden/', {
            'action': 'add_customer', 'first_name': 'Neue', 'last_name': 'Kundin',
            'email': 'neue.kundin@example.test', 'phone': '+4969123456', 'return_to': 'kunden',
        })
        self.assertEqual(response.status_code, 302)
        saved = Customer.objects.get(email='neue.kundin@example.test')
        self.assertEqual((saved.first_name, saved.last_name), ('Neue', 'Kundin'))
        self.assertIn('notice=customer', response['Location'])

    @patch('booking.admin_more_views.app_management_views._api')
    def test_dashboard_is_focused_and_more_contains_campaigns_and_templates(self, api):
        api.side_effect = self._fake_aplus_api
        WhatsAppTemplate.objects.create(name='Recall', body='Hallo {vorname}', sort_order=1)

        dashboard = self.client.get('/verwaltung/dashboard/?q=Regression')
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'Management')
        self.assertContains(dashboard, 'Patient suchen')
        self.assertNotContains(dashboard, 'Kampagnen & Banner')
        self.assertNotContains(dashboard, 'Nachrichten-Vorlagen')
        self.assertContains(dashboard, 'Regression')
        self.assertContains(dashboard, 'Mehr')
        self.assertContains(dashboard, 'admin-app-inset-v5.css?v=20260912-v20')

        more = self.client.get('/verwaltung/mehr/')
        self.assertEqual(more.status_code, 200)
        self.assertContains(more, 'Kampagnen')
        self.assertContains(more, 'WhatsApp-Vorlagen')
        self.assertContains(more, 'Autumn Glow')
        self.assertContains(more, 'Praxis & Buchung')

    @patch('booking.app_management_views._api')
    def test_focused_aplus_sections_have_one_header_contract(self, api):
        api.side_effect = self._fake_aplus_api
        paths = ('/verwaltung/app/patients/', '/verwaltung/app/referrals/', '/verwaltung/app/reviews/', '/verwaltung/app/wallet/')
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.content[:300])
                self.assertContains(response, 'class="sb-mobile-bar app-mobile-bar"')
                self.assertContains(response, 'data-drawer-open')
                self.assertContains(response, 'data-drawer')
                self.assertContains(response, 'admin-app-inset-v5.css?v=20260912-v20')

    @patch('booking.app_management_views._api')
    def test_patient_wallet_green_finish_is_server_rendered_and_reload_safe(self, api):
        api.side_effect = self._fake_aplus_api
        finish = 'clinic-patient-wallet-finish-v4.css?v=20261029-v5'
        for path in ('/verwaltung/app/patients/', '/verwaltung/app/wallet/'):
            with self.subTest(path=path):
                for attempt in range(2):  # first render and hard-reload equivalent
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    body = response.content.decode('utf-8')
                    self.assertEqual(body.count(finish), 1)
                    self.assertLess(body.index('clinic-signature-surfaces-v1.css'), body.index(finish))
        for path in ('/verwaltung/app/reviews/', '/verwaltung/app/referrals/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, finish)

    def test_green_finish_is_in_templates_even_without_aplus_sso_session(self):
        from django.template.loader import get_template
        # The template source is delivered to every already-authorized viewer,
        # regardless of which valid session mechanism was used.
        style = 'clinic-patient-wallet-finish-v4.css?v=20261029-v5'
        for template in ('app_wallet_management.html', 'app_management.html'):
            with self.subTest(template=template):
                source = get_template('booking/' + template).template.source
                self.assertEqual(source.count(style), 1)
        wallet = get_template('booking/app_wallet_management.html').template.source
        patient = get_template('booking/app_management.html').template.source
        self.assertLess(wallet.index('clinic-signature-surfaces-v1.css'), wallet.index(style))
        self.assertIn("{% if section == 'patients' %}", patient)

    def test_calendar_scroll_owner_is_not_document_body(self):
        source = (Path(__file__).resolve().parent.parent /
                  'static/booking/admin-calendar-scroll-v5.css').read_text(encoding='utf-8')
        for rule in ("main.sb-admin-shell", "overflow-y:scroll!important",
                     "height:calc(100dvh - 64px", "touch-action:pan-y pinch-zoom",
                     ".sb-day-track", ".sb-calendar-shell.is-week"):
            self.assertIn(rule, source)
        response = self.client.get('/verwaltung/kalender/', {'staff': self.staff.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-calendar-scroll-v5.css?v=20261029-scroll-v5')

    @patch('booking.app_management_views._api')
    def test_private_admin_html_is_not_cached_and_has_final_ui_marker(self, api):
        api.side_effect = self._fake_aplus_api
        for path in ('/verwaltung/kalender/', '/verwaltung/app/wallet/', '/verwaltung/app/patients/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-store', response.get('Cache-Control',''))
                self.assertIn('private', response.get('Cache-Control',''))
        calendar = self.client.get('/verwaltung/kalender/')
        self.assertContains(calendar,'admin-calendar-date-dock-v6.css?v=20261029-firstpaint7')
        wallet = self.client.get('/verwaltung/app/wallet/')
        self.assertContains(wallet,'background:linear-gradient(118deg,#10271d')
        customers = self.client.get('/verwaltung/app/patients/')
        self.assertContains(customers,'class="premium-customer-panel" aria-label="Kundenverzeichnis" style="width:100%!important')

    def test_calendar_add_menu_remains_real_and_accessible(self):
        response = self.client.get('/verwaltung/kalender/', {'staff': self.staff.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-fab-wrap')
        self.assertContains(response, 'data-fab-actions')
        self.assertContains(response, 'data-fab')
        script = (Path(__file__).resolve().parent.parent /
                  'static/booking/admin.js').read_text(encoding='utf-8')
        for marker in ('admin-calendar-mobile-finish-v4.css',
                       "fab.setAttribute('aria-expanded'",
                       "event.key === 'Escape'"):
            self.assertIn(marker, script)

    @patch('booking.app_management_views._api')
    def test_points_history_renders_only_points_not_money(self, api):
        api.side_effect = self._fake_aplus_api
        response = self.client.get('/verwaltung/app/wallet/?q=Sophie&wallet=10')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PUNKTEVERLAUF')
        self.assertContains(response, 'Google Bewertung verifiziert')
        self.assertContains(response, '+250 Punkte')
        self.assertContains(response, '550')
        self.assertNotContains(response, 'Guthaben')
        self.assertNotContains(response, '€')

    def test_calendar_remains_isolated_and_keeps_add_action(self):
        response = self.client.get('/verwaltung/kalender/', {'staff': self.staff.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-calendar-stability-v8.css')
        self.assertContains(response, 'class="sb-fab"')
        self.assertContains(response, 'data-fab')
        self.assertNotContains(response, 'admin-patient-detail-v7.css')
        self.assertNotContains(response, 'admin-fast-drawer-v7.js')
        self.assertNotContains(response, 'admin-dashboard-v11.css')

    def test_service_select_labels_include_duration_without_changing_calendar_grid(self):
        response = self.client.get('/verwaltung/kalender/', {'staff': self.staff.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Regression Beratung · 30 Min.')
        self.assertContains(response, 'sb-day-track')

    def test_non_calendar_pages_keep_scroll_recovery(self):
        for path in ('/verwaltung/buchungen/', '/verwaltung/kunden/'):
            response = self.client.get(path, {'staff': self.staff.pk})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'data-view-menu-open')
            self.assertNotContains(response, 'data-iphone-date-open')
            self.assertNotContains(response, 'data-iphone-filter-open')
            self.assertNotContains(response, 'sb-reference-calendar-bar')
            self.assertContains(response, 'admin-scroll-recovery-v9.css')

    def test_view_only_access_blocks_all_admin_writes(self):
        AdminAccessProfile.objects.create(user=self.admin, staff=self.staff, view_only=True)
        response = self.client.post('/verwaltung/kunden/', {
            'action': 'add_customer', 'first_name': 'Blocked', 'last_name': 'Write', 'email': 'blocked@example.test',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Customer.objects.filter(email='blocked@example.test').exists())

    def test_customer_default_order_is_family_name_then_first_name(self):
        Customer.objects.create(first_name='Zoe', last_name='Alpha', email='za@example.test')
        Customer.objects.create(first_name='Anna', last_name='Zulu', email='az@example.test')
        names = list(Customer.objects.values_list('last_name', 'first_name'))
        self.assertEqual(names[0], ('Alpha', 'Zoe'))
        self.assertEqual(names[-1], ('Zulu', 'Anna'))

    def test_logout_clears_admin_bridge_state(self):
        response = self.client.get('/verwaltung/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('aplus_app_admin', self.client.session)
        self.assertNotIn('aplus_admin_authorization', self.client.session)
