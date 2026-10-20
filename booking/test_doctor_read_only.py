from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import AdminAccessProfile, Appointment, Customer, Service, StaffMember


class DoctorReadOnlyTests(TestCase):
    def setUp(self):
        doctor = StaffMember.objects.create(display_name='Qamar Hameed', role='doctor')
        another = StaffMember.objects.create(display_name='Andere Ärztin', role='doctor')
        service = Service.objects.create(name='Beratung Arzt', slug='beratungsarzt')
        customer = Customer.objects.create(first_name='Meine', last_name='Patientin', email='mine@example.test')
        other_customer = Customer.objects.create(first_name='Fremde', last_name='Patientin', email='other@example.test')
        now = timezone.now() + timedelta(days=1)
        for staff, patient in [(doctor, customer), (another, other_customer)]:
            Appointment.objects.create(staff=staff, customer=patient, service=service,
                starts_at=now, ends_at=now + timedelta(minutes=30))
        self.user = User.objects.create_user(username='doctor-qamar', password='test-secret', is_staff=True)
        AdminAccessProfile.objects.create(user=self.user, staff=doctor, view_only=True)
        self.client.force_login(self.user)

    def test_only_own_appointments_are_visible(self):
        response = self.client.get('/verwaltung/arzt/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Meine Patientin')
        self.assertNotContains(response, 'Fremde Patientin')

    def test_other_admin_surfaces_are_rejected(self):
        for url in ['/verwaltung/dashboard/', '/verwaltung/kalender/', '/verwaltung/kunden/',
                    '/verwaltung/mehr/', '/verwaltung/patienten/1/', '/admin/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_writes_are_rejected(self):
        self.assertEqual(self.client.post('/verwaltung/arzt/').status_code, 403)

    @patch('booking.auth_views._verify_doctor')
    @patch('booking.app_admin_api._verify_admin', return_value=None)
    def test_doctor_sso_uses_scoped_session(self, _admin, verify_doctor):
        verify_doctor.return_value = {'id': 908, 'name': 'Qamar Hameed', 'email': ''}
        self.client.logout()
        response = self.client.post('/verwaltung/app-sso/',
            HTTP_AUTHORIZATION='Bearer a-verified-doctor-token-that-is-long')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], '/verwaltung/arzt/')
        user = User.objects.get(username='aplus_app_admin_908')
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.aesthetic_access.view_only)
        self.assertEqual(user.aesthetic_access.staff.display_name, 'Qamar Hameed')
