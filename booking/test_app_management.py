from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Appointment, Customer, PatientRecord, Service, StaffMember


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
    def test_wallet_management_renders_inside_focused_aplus_ui(self, api):
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
        self.assertContains(response, '50,00 €')
        self.assertContains(response, '/verwaltung/app/bookings/')
        self.assertContains(response, '/verwaltung/app/patients/')
        self.assertContains(response, 'Google Bewertungen')
        self.assertNotContains(response, '/verwaltung/einstellungen/')
        self.assertNotContains(response, '/verwaltung/behandlungen/')
        self.assertNotContains(response, 'Rewards')
        self.assertNotContains(response, 'Pakete')
        self.assertNotContains(response, 'App-Module')

    def test_calendar_keeps_original_detailed_book_ui(self):
        response = self.client.get('/verwaltung/kalender/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'PRIORITÄT 01')
        self.assertNotContains(response, '/verwaltung/app/bookings/', status_code=200)

    def test_focused_bookings_alias_returns_to_original_calendar(self):
        response = self.client.get('/verwaltung/app/bookings/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/verwaltung/kalender/')

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
        self.assertEqual(api.call_count, 1)
        args, kwargs = api.call_args
        self.assertEqual(args[1], 'customers/10/')
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['payload'], {'credit_delta_cents': 2500})

    @patch('booking.app_management_views._api')
    def test_reviews_render(self, api):
        api.return_value = {'ok': True, 'reviews': [{'id': 4, 'customer': 'Patient', 'email': 'p@example.test', 'status': 'submitted', 'status_label': 'Als abgegeben markiert', 'rating': 5, 'review_text': '', 'submitted_at': '2026-09-06T12:00:00+00:00', 'opened_at': '2026-09-06T11:00:00+00:00', 'google_review_url': ''}]}
        response = self.client.get('/verwaltung/app/reviews/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google Bewertungen')
        self.assertContains(response, 'Patient')

    def _booking_fixture(self):
        customer = Customer.objects.create(first_name='Anna', last_name='Muster', email='anna@example.test', phone='069123')
        service = Service.objects.create(name='Beratung', slug='beratung-test', duration_minutes=30, buffer_minutes=0)
        staff = StaffMember.objects.create(display_name='Dr. Test', role='doctor')
        staff.services.add(service)
        appointment = Appointment.objects.create(
            customer=customer,
            service=service,
            staff=staff,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, minutes=30),
            status='new',
            source='app',
        )
        return customer, service, staff, appointment

    def test_patient_record_timeline_shows_patient_and_practice_history(self):
        customer, _, _, appointment = self._booking_fixture()
        PatientRecord.objects.create(
            customer=customer,
            appointment=appointment,
            kind='note',
            title='Vom Patienten',
            note='Patient upload',
            source='a_esthetic_app_customer',
            captured_at=timezone.now(),
        )
        PatientRecord.objects.create(
            customer=customer,
            kind='document',
            title='Praxisdokument',
            note='Clinic note',
            source='book_staff',
            metadata={'shared_with_customer': True},
            captured_at=timezone.now(),
        )
        response = self.client.get(f'/verwaltung/app/patients/?customer={customer.pk}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, customer.full_name)
        self.assertContains(response, 'Vom Patienten')
        self.assertContains(response, 'Patient · Notiz')
        self.assertContains(response, 'Praxisdokument')
        self.assertContains(response, 'Praxis · Dokument')
        self.assertContains(response, 'Für Patient sichtbar')
