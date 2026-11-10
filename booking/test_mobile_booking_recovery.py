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

    def test_same_email_phone_with_legacy_name_allows_booking_without_changing_patient(self):
        known = Customer.objects.create(
            first_name='Different', last_name='Patient',
            email=self.member['email'], phone=self.member['phone'],
        )
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            response = self.post(key='identity-compatible-attempt')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Appointment.objects.get().customer_id, known.pk)
        self.assertEqual(Customer.objects.count(), 1)
        known.refresh_from_db()
        self.assertEqual(known.first_name, 'Different')
        self.assertEqual(known.last_name, 'Patient')

    def test_email_match_is_not_blocked_by_another_record_sharing_the_phone(self):
        known = Customer.objects.create(
            first_name='Anna', last_name='Muster',
            email=self.member['email'], phone=self.member['phone'],
        )
        other = Customer.objects.create(
            first_name='Someone', last_name='Else',
            email='someone@example.invalid', phone=self.member['phone'],
        )
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            response = self.post(key='shared-family-phone')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Appointment.objects.get().customer_id, known.pk)
        self.assertEqual(Customer.objects.count(), 2)
        self.assertTrue(Customer.objects.filter(pk=other.pk).exists())

    def test_different_email_with_same_phone_gets_independent_booking_customer(self):
        previous = Customer.objects.create(
            first_name='Someone', last_name='Else',
            email='someone@example.invalid', phone=self.member['phone'],
        )
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            response = self.post(key='new-account-shared-phone')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Customer.objects.count(), 2)
        self.assertNotEqual(Appointment.objects.get().customer_id, previous.pk)

    def test_conflicting_email_and_phone_and_name_still_blocked(self):
        known = Customer.objects.create(
            first_name='Unrelated', last_name='Person',
            email=self.member['email'], phone='+4915123451234',
        )
        response = self.post(key='identity-mismatch-attempt')
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['error'], 'identity_conflict')
        self.assertEqual(Appointment.objects.count(), 0)
        known.refresh_from_db()
        self.assertEqual(known.phone, '+4915123451234')

    def test_duplicate_email_without_unambiguous_match_does_not_expose_records(self):
        Customer.objects.create(first_name='Different', last_name='Person',
                                email=self.member['email'], phone='')
        Customer.objects.create(first_name='Another', last_name='Person',
                                email=self.member['email'], phone='')
        response = self.post(key='duplicated-email')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'identity_conflict')
        self.assertEqual(Appointment.objects.count(), 0)

    def test_duplicate_email_with_one_exact_phone_and_name_is_resolved(self):
        first = Customer.objects.create(first_name='Someone', last_name='Else',
                                        email=self.member['email'], phone='+4915123451234')
        matched = Customer.objects.create(first_name='Anna', last_name='Muster',
                                          email=self.member['email'], phone=self.member['phone'])
        with patch('booking.mobile_api.send_booking_emails'), \
             patch('booking.mobile_api.notify_booking_created'), \
             self.captureOnCommitCallbacks(execute=True):
            response = self.post(key='duplicate-email-disambiguated')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Appointment.objects.get().customer_id, matched.pk)
        self.assertNotEqual(Appointment.objects.get().customer_id, first.pk)

    def test_missing_new_patient_name_requires_profile_completion(self):
        anon_member = {**self.member, 'first_name': '', 'last_name': ''}
        response = self.post(key='missing-name-attempt', member=anon_member)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error'], 'profile_completion_required')
        self.assertEqual(Customer.objects.count(), 0)

    def test_readonly_history_does_not_expose_ambiguous_duplicate_email(self):
        Customer.objects.create(first_name='A', last_name='One',
                                email=self.member['email'], phone='')
        Customer.objects.create(first_name='B', last_name='Two',
                                email=self.member['email'], phone='')
        with patch('booking.mobile_api._member', return_value=(self.member, None)):
            history = self.client.get('/api/mobile/booking/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['appointments'], [])


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
