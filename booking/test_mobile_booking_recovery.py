"""Regression coverage for customer-app HTTP 409 booking failures.

All appointments are created in the isolated Django test database. No
production patient, booking, push recipient or email address is used.
"""
import json
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Appointment, Customer, Service, StaffMember, WorkingHour


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MobileBookingRecoveryTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Botox - Bestandspatient', slug='botox-test-recovery',
            duration_minutes=15, buffer_minutes=0,
            active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name='Frau Testärztin', active=True)
        self.staff.services.add(self.service)
        for weekday in range(7):
            WorkingHour.objects.create(
                staff=self.staff, weekday=weekday, start_time=time(9), end_time=time(18),
            )
        day = timezone.localdate() + timedelta(days=3)
        self.starts_at = timezone.make_aware(datetime.combine(day, time(10, 0)))
        self.member = {
            'email': 'patient@example.invalid',
            'phone': '+49 151 0000001',
            'first_name': 'Anna',
            'last_name': 'Muster',
        }

    def post(self, *, key='unique-test-attempt', member=None):
        with patch('booking.mobile_api._member', return_value=(member or self.member, None)), \
             patch('booking.mobile_api.sync_package',
                   return_value={'ok': True, 'package_used': False}):
            return self.client.post(
                '/api/mobile/booking/',
                data=json.dumps({
                    'service_id': self.service.pk,
                    'staff_id': self.staff.pk,
                    'starts_at': self.starts_at.isoformat(),
                    'consent_acknowledged': True,
                }),
                content_type='application/json',
                HTTP_IDEMPOTENCY_KEY=key,
            )

    def test_retry_after_saved_booking_is_200_with_same_id_and_no_duplicate(self):
        with patch('booking.mobile_api.send_booking_emails') as email, \
             patch('booking.mobile_api.notify_booking_created') as push, \
             self.captureOnCommitCallbacks(execute=True):
            first = self.post()
            retry = self.post()

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(first.json()['appointment_id'], retry.json()['appointment_id'])
        self.assertEqual(Appointment.objects.count(), 1)
        email.assert_called_once()
        push.assert_called_once()

    def test_same_idempotency_key_cannot_expose_other_patients_appointment(self):
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            first = self.post()
            another = {**self.member, 'email': 'other@example.invalid'}
            retry = self.post(member=another)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()['error'], 'time_not_available')
        self.assertNotIn('appointment_id', retry.json())
        self.assertEqual(Appointment.objects.count(), 1)

    def test_name_conflict_returns_actionable_message_without_merging_patient(self):
        known = Customer.objects.create(
            first_name='Different', last_name='Patient',
            email=self.member['email'], phone=self.member['phone'],
        )
        response = self.post(key='identity-conflict-attempt')
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['error'], 'identity_conflict')
        self.assertIn('Praxis', response.json()['message'])
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 1)
        known.refresh_from_db()
        self.assertEqual(known.first_name, 'Different')

    def test_notification_error_cannot_fail_already_persisted_appointment(self):
        with patch('booking.mobile_api.send_booking_emails', side_effect=RuntimeError('smtp down')), \
             patch('booking.mobile_api.notify_booking_created', side_effect=RuntimeError('push down')), \
             self.captureOnCommitCallbacks(execute=True):
            response = self.post(key='notification-error-attempt')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cancelled_attempt_is_not_replayed_as_success(self):
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            first = self.post(key='cancelled-test-attempt')
            appointment = Appointment.objects.get()
            appointment.status = 'cancelled'
            appointment.save(update_fields=['status', 'updated_at'])
            repeat = self.post(key='cancelled-test-attempt')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(repeat.json()['error'], 'booking_attempt_closed')
        self.assertEqual(Appointment.objects.count(), 1)
