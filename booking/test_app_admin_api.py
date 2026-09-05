from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Appointment, Customer, Service, StaffMember, WorkingHour


class AppAdminApiTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Botox Test', slug='botox-test', duration_minutes=30, buffer_minutes=10,
            price_label='ab 100 €', active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name='Dr. Test', active=True)
        self.staff.services.add(self.service)
        WorkingHour.objects.create(staff=self.staff, weekday=timezone.localdate().weekday(), start_time='09:00', end_time='18:00')
        self.customer = Customer.objects.create(first_name='Anna', last_name='Muster', email='anna@example.com')
        start = timezone.now().replace(second=0, microsecond=0)
        start = start - timedelta(minutes=start.minute % 15)
        self.appointment = Appointment.objects.create(
            customer=self.customer,
            service=self.service,
            staff=self.staff,
            starts_at=start + timedelta(hours=2),
            ends_at=start + timedelta(hours=2, minutes=40),
            status='new',
            source='app',
        )
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer test-admin-token-abcdefghijklmnopqrstuvwxyz'}
        self.admin_patch = patch('booking.app_admin_api._verify_admin', return_value={'id': 1, 'name': 'Admin'})
        self.admin_patch.start()
        self.addCleanup(self.admin_patch.stop)

    def test_overview_is_available_to_verified_app_admin(self):
        response = self.client.get('/api/mobile/app-admin/overview/', **self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['stats']['customers'], 1)
        self.assertGreaterEqual(payload['stats']['active_services'], 1)

    def test_calendar_returns_book_data(self):
        day = timezone.localtime(self.appointment.starts_at).date().isoformat()
        response = self.client.get(
            f'/api/mobile/app-admin/calendar/?date={day}&staff={self.staff.pk}',
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['appointments'][0]['customer_name'], 'Anna Muster')
        self.assertEqual(payload['selected_staff'], self.staff.pk)

    def test_appointment_status_can_be_changed_from_app(self):
        response = self.client.post(
            f'/api/mobile/app-admin/appointments/{self.appointment.pk}/',
            data='{"status":"confirmed"}',
            content_type='application/json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')

    def test_service_can_be_disabled_from_app(self):
        response = self.client.post(
            f'/api/mobile/app-admin/services/{self.service.pk}/',
            data='{"bookable":false}',
            content_type='application/json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertFalse(self.service.bookable)
