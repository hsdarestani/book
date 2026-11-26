from datetime import timedelta
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AdminAccessProfile, Appointment, Customer, PatientRecord, Service, StaffMember, WhatsAppTemplate


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

    @patch('booking.app_management_views.urlopen')
    def test_unavailable_referrals_does_not_erase_other_app_admin_access(self, upstream):
        upstream.side_effect = HTTPError('https://example.invalid/', 403, '', {}, BytesIO(b'{"error":"admin_required"}'))
        response = self.client.get('/verwaltung/app/referrals/')
        self.assertContains(response, 'erfordert eine Freigabe', status_code=403)
        self.assertNotContains(response, 'Noch keine Empfehlungen', status_code=403)
        self.assertEqual(self.client.session['aplus_admin_authorization'], 'Bearer test-admin-token')
        upstream.side_effect = None
        remote = upstream.return_value.__enter__.return_value
        remote.status = 200
        remote.read.return_value = b'{"ok":true,"banners":[{"title":"Synthetic Campaign"}]}'
        self.assertContains(self.client.get('/verwaltung/mehr/'), 'Synthetic Campaign')
        self.assertEqual(upstream.call_args.args[0].get_header('Authorization'), 'Bearer test-admin-token')

    @patch('booking.app_management_views.urlopen')
    def test_expired_app_session_disables_campaigns_but_keeps_local_templates(self, upstream):
        WhatsAppTemplate.objects.create(name='Synthetic Vorlage', body='Synthetic content')
        upstream.side_effect = HTTPError('https://example.invalid/', 401, '', {}, BytesIO(b''))
        response = self.client.get('/verwaltung/mehr/')
        self.assertContains(response, 'Bitte öffnen Sie die Verwaltung erneut aus der A+ App.')
        self.assertContains(response, 'data-ferrari-open="campaign-new" disabled')
        self.assertContains(response, 'Synthetic Vorlage')
        self.assertNotContains(response, 'Noch keine Kampagnen vorhanden.')
        self.assertContains(self.client.get('/verwaltung/app/referrals/'), 'Bitte öffnen Sie', status_code=403)
        session = self.client.session
        session.pop('aplus_app_admin')
        session.save()
        upstream.reset_mock()
        self.assertContains(self.client.get('/verwaltung/mehr/'), 'Bitte öffnen Sie')
        self.assertContains(self.client.get('/verwaltung/app/referrals/'), 'Bitte öffnen Sie', status_code=403)
        self.assertContains(self.client.post('/verwaltung/mehr/', {'action': 'banner_delete', 'banner_id': 1}), 'Bitte öffnen Sie')
        upstream.assert_not_called()

    @patch('booking.app_management_views._api')
    def test_referral_activity_distinguishes_pending_and_awarded_points(self, api):
        api.return_value = {'ok': True, 'referrals': [
            {'customer': 'Synthetic Waiting', 'code': 'WAIT', 'status': 'invited',
             'status_label': 'Eingeladen', 'created_at': '2026-04-10T22:10:00Z', 'reward_coins': 450},
            {'customer': 'Synthetic Awarded', 'code': 'DONE', 'status': 'rewarded',
             'status_label': 'Belohnt', 'reward_coins': 500, 'rewarded_at': '2026-04-11T22:10:00Z'},
        ]}
        response = self.client.get('/verwaltung/app/referrals/')
        self.assertContains(response, '450 Punkte ausstehend')
        self.assertContains(response, '500 Punkte vergeben am 12.04.2026')
        self.assertContains(response, 'Eingeladen am 11.04.2026')

    @patch('booking.app_management_views._api')
    def test_points_management_renders_inside_focused_aplus_ui(self, api):
        api.return_value = {
            'ok': True,
            'customers': [{
                'id': 10,
                'name': 'Test Patient',
                'email': 'patient@example.test',
                'phone': '',
                'member_number': 'AP-TEST123',
                'member_status': 'active',
                'coins': 500,
            }],
        }
        response = self.client.get('/verwaltung/app/wallet/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A+ Punkte')
        self.assertContains(response, 'Test Patient')
        self.assertContains(response, 'AP-TEST123')
        self.assertContains(response, '500')
        self.assertContains(response, 'QR-Code scannen')
        self.assertContains(response, 'data-wallet-scan-open')
        self.assertContains(response, 'app-wallet-scanner.js')
        self.assertContains(response, '/verwaltung/dashboard/')
        self.assertContains(response, '/verwaltung/app/patients/')
        self.assertNotContains(response, '/verwaltung/app/reviews/')
        self.assertNotContains(response, 'Guthaben')
        self.assertNotContains(response, '€')

    def test_calendar_keeps_original_detailed_book_ui(self):
        response = self.client.get('/verwaltung/kalender/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'POINTS CONTROL')
        self.assertNotContains(response, 'admin-dashboard-v11.css')

    def test_focused_bookings_alias_returns_to_original_calendar(self):
        response = self.client.get('/verwaltung/app/bookings/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/verwaltung/kalender/')

    def test_aplus_admin_logout_clears_book_session_and_returns_to_aplus(self):
        response = self.client.get('/verwaltung/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://esthetic.smarbiz.sbs/?admin_logout=1')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotIn('aplus_app_admin', self.client.session)
        self.assertNotIn('aplus_admin_authorization', self.client.session)

    def test_regular_book_staff_logout_stays_on_book_login(self):
        session = self.client.session
        session.pop('aplus_app_admin', None)
        session.pop('aplus_admin_authorization', None)
        session.save()
        response = self.client.get('/verwaltung/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/verwaltung/login/')

    @patch('booking.app_management_views._api')
    def test_points_adjust_posts_coin_delta_only(self, api):
        api.return_value = {'ok': True, 'customer': {'id': 10, 'coins': 725}}
        response = self.client.post('/verwaltung/app/wallet/', {
            'action': 'points_adjust',
            'customer_id': '10',
            'point_delta': '250',
            'q': 'patient@example.test',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verwaltung/app/wallet/', response['Location'])
        args, kwargs = api.call_args
        self.assertEqual(args[1], 'customers/10/')
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['payload'], {'coin_delta': 250})

    @patch('booking.app_management_views._api')
    def test_wallet_scan_resolves_qr_and_redirects_to_customer(self, api):
        api.return_value = {
            'ok': True,
            'resolved_by': 'wallet_qr',
            'customer': {'id': 10, 'email': 'patient@example.test', 'member_number': 'AP-TEST123'},
        }
        response = self.client.post('/verwaltung/app/wallet/', {'action': 'wallet_scan', 'qr_token': 'secure-qr-token'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('q=patient%40example.test', response['Location'])
        self.assertIn('scan=1', response['Location'])
        args, kwargs = api.call_args
        self.assertEqual(args[1], 'wallet/lookup/')
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['payload'], {'qr_token': 'secure-qr-token'})

    @patch('booking.app_management_views._api')
    def test_reviews_render_with_verified_points_gate(self, api):
        api.return_value = {'ok': True, 'reviews': [{'id': 4, 'customer': 'Patient', 'email': 'p@example.test', 'status': 'submitted', 'status_label': 'Als abgegeben markiert', 'rating': 5, 'google_review_url': '', 'points_awarded': False, 'points_value': 250}]}
        response = self.client.get('/verwaltung/app/reviews/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google Bewertungen')
        self.assertContains(response, 'Verifizieren + Punkte')

    def _booking_fixture(self):
        customer = Customer.objects.create(first_name='Anna', last_name='Muster', email='anna@example.test', phone='069123')
        service = Service.objects.create(name='Beratung', slug='beratung-test', duration_minutes=30, buffer_minutes=0)
        staff = StaffMember.objects.create(display_name='Dr. Test', role='doctor')
        staff.services.add(service)
        start = timezone.now() + timedelta(days=1)
        appointment = Appointment.objects.create(customer=customer, service=service, staff=staff, starts_at=start, ends_at=start + timedelta(minutes=30), status='new', source='app')
        return customer, service, staff, appointment

    @patch('booking.app_management_views._api')
    def test_patient_record_is_360_profile_with_actions_points_and_duration(self, api):
        customer, _, _, appointment = self._booking_fixture()
        customer.salutation = 'frau'
        customer.save(update_fields=['salutation'])
        WhatsAppTemplate.objects.create(name='Nachsorge', body='Hallo {anrede} {nachname}, alles gut?', sort_order=1)
        PatientRecord.objects.create(customer=customer, appointment=appointment, kind='note', title='Vom Patienten', note='Patient upload', source='a_esthetic_app_customer', captured_at=timezone.now())
        api.return_value = {'ok': True, 'customers': [{'id': 90, 'email': customer.email, 'coins': 720}]}
        base = f'/verwaltung/app/patients/?customer={customer.pk}'
        overview = self.client.get(base)
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, customer.full_name)
        self.assertContains(overview, '720')
        self.assertContains(overview, 'Anrufen')
        self.assertContains(overview, 'WhatsApp')
        self.assertContains(overview, 'Frau Muster')
        self.assertNotContains(overview, 'Foto aufnehmen')
        self.assertNotContains(overview, '30 Min.')

        appointments = self.client.get(base + '&tab=appointments')
        self.assertEqual(appointments.status_code, 200)
        self.assertContains(appointments, '30 Min.')
        self.assertNotContains(appointments, 'Foto aufnehmen')

        records = self.client.get(base + '&tab=records')
        self.assertEqual(records.status_code, 200)
        self.assertContains(records, 'Foto aufnehmen')
        self.assertContains(records, 'admin-native-camera-v11.js')

    @patch('booking.app_management_views._api')
    def test_patient_tab_get_submission_keeps_selected_tab(self, api):
        """Reproduce live click bug: submitter can be disabled, hidden tab still sent."""
        customer, _, _, _ = self._booking_fixture()
        api.return_value = {'ok': True, 'customers': []}
        path = '/verwaltung/app/patients/'
        expected = {
            'overview': ('Anrede & Kommunikation', 'Neuer Akteneintrag'),
            'appointments': ('Alle Reservierungen dieses Patienten.', 'Neuer Akteneintrag'),
            'records': ('Neuer Akteneintrag', 'Anrede & Kommunikation'),
            'points': ('Punkte anpassen', 'Anrede & Kommunikation'),
        }
        for tab, (visible, absent) in expected.items():
            with self.subTest(tab=tab):
                # Browser sends hidden GET fields even if submit button is disabled.
                response = self.client.get(path, {
                    'customer': str(customer.pk), 'q': 'Anna', 'tab': tab,
                })
                self.assertEqual(response.status_code, 200, response.content[:300])
                self.assertContains(response, visible)
                self.assertNotContains(response, absent)
                self.assertContains(response, f'<input type="hidden" name="tab" value="{tab}">')
                self.assertContains(response, 'data-clinic-profile-build="4"')
                self.assertEqual(response.context['customer_tab'], tab)

    def test_local_view_only_doctor_can_read_patient_but_cannot_post(self):
        customer, _, staff, _ = self._booking_fixture()
        session = self.client.session
        session.pop('aplus_app_admin', None)
        session.pop('aplus_admin_authorization', None)
        session.save()
        AdminAccessProfile.objects.create(user=self.user, staff=staff, view_only=True)

        read = self.client.get(f'/verwaltung/app/patients/?customer={customer.pk}')
        self.assertEqual(read.status_code, 200)
        self.assertContains(read, customer.full_name)

        write = self.client.post('/verwaltung/app/patients/', {
            'action': 'patient_salutation',
            'customer_id': customer.pk,
            'salutation': 'frau',
        })
        self.assertEqual(write.status_code, 403)
