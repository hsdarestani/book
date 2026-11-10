"""Regression for email cancellation without Safari login and unchanged booking ownership."""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from django.core import signing
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .email_cancellation import cancellation_token
from .emails import _booking_email_context
from .models import Appointment, Customer, Service, StaffMember


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    BOOKING_CHANGE_DEADLINE_HOURS=24,
)
class EmailCancellationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Anna', last_name='Muster',
            email='anna@example.test', phone='+491512341234',
        )
        self.staff = StaffMember.objects.create(display_name='Frau Test', active=True)
        self.service = Service.objects.create(
            name='Botox-Test', slug='botox-email-cancel-test',
            active=True, bookable=True, duration_minutes=15,
        )
        self.staff.services.add(self.service)
        start = timezone.now() + timedelta(days=4)
        self.appointment = Appointment.objects.create(
            customer=self.customer, staff=self.staff, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=15),
            status='confirmed', source='app',
        )
        self.url = f'/termin/{self.appointment.public_id}/stornieren/'
        self.token = cancellation_token(self.appointment)

    def test_email_has_one_appointment_scoped_cancel_link_and_never_requires_login(self):
        context = _booking_email_context(self.appointment)
        self.assertIn(str(self.appointment.public_id), context['email_cancel_url'])
        self.assertIn('token=', context['email_cancel_url'])
        self.assertIn('/stornieren/', context['email_cancel_url'])
        self.assertNotIn('login', context['email_cancel_url'].lower())

    def test_get_is_read_only_and_shows_confirmation_without_app_session(self):
        response = self.client.get(self.url, {'token': self.token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'verbindlich stornieren')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')

    @patch('booking.email_cancellation.notify_customer_cancelled')
    @patch('booking.email_cancellation._post_internal')
    def test_only_post_cancels_and_releases_package_credit_once(self, post, notify):
        post.return_value = {'ok': True, 'package_released': True}
        result = self.client.post(self.url, {'token': self.token})
        self.assertEqual(result.status_code, 200, result.content[:400])
        self.assertContains(result, 'Termin storniert')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'cancelled')
        post.assert_called_once()
        self.assertEqual(post.call_args.args[1], {'booking_public_id': str(self.appointment.public_id)})
        notify.assert_called_once()
        second = self.client.post(self.url, {'token': self.token})
        self.assertEqual(second.status_code, 200)
        post.assert_called_once()
        notify.assert_called_once()

    @patch('booking.email_cancellation.notify_customer_cancelled')
    @patch('booking.email_cancellation._post_internal', return_value={'ok': False, 'error': 'relay_unavailable'})
    def test_failed_package_credit_release_does_not_cancel_or_notify(self, post, notify):
        result = self.client.post(self.url, {'token': self.token})
        self.assertEqual(result.status_code, 503)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')
        notify.assert_not_called()

    def test_invalid_link_does_not_reveal_treatment_or_clinician_details(self):
        response = self.client.get(self.url, {'token': 'bad'})
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'Botox-Test', status_code=403)
        self.assertNotContains(response, 'Frau Test', status_code=403)

    def test_imported_simplybook_email_does_not_offer_a_local_cancel_link(self):
        from django.core import mail
        from .emails import send_customer_booking_email
        self.appointment.idempotency_key = 'simplybook-42'
        self.appointment.save(update_fields=['idempotency_key'])
        send_customer_booking_email(self.appointment)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn('SimplyBook-Termins', message.body)
        self.assertNotIn('Termin ohne Anmeldung stornieren:', message.body)
        self.assertNotIn('Termin stornieren · ohne Anmeldung', message.alternatives[0][0])

    def test_expired_or_tampered_link_cannot_view_or_cancel(self):
        for value in ('tampered-token', ''):
            response = self.client.post(self.url, {'token': value})
            self.assertEqual(response.status_code, 403)
        with patch('booking.email_cancellation.signing.loads',
                   side_effect=signing.SignatureExpired('expired')):
            response = self.client.get(self.url, {'token': self.token})
            self.assertEqual(response.status_code, 403)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')

    def test_token_does_not_authorize_a_different_booking(self):
        second = Appointment.objects.create(
            customer=self.customer, staff=self.staff, service=self.service,
            starts_at=self.appointment.starts_at + timedelta(hours=2),
            ends_at=self.appointment.ends_at + timedelta(hours=2),
            status='confirmed',
        )
        other_url = f'/termin/{second.public_id}/stornieren/'
        response = self.client.post(other_url, {'token': self.token})
        self.assertEqual(response.status_code, 403)
        second.refresh_from_db()
        self.assertEqual(second.status, 'confirmed')

    @patch('booking.email_cancellation._post_internal')
    def test_imported_simplybook_booking_cannot_be_cancelled_only_in_local_mirror(self, post):
        self.appointment.idempotency_key = 'simplybook-remote-42'
        self.appointment.source = 'admin'
        self.appointment.save(update_fields=['idempotency_key', 'source'])
        token = cancellation_token(self.appointment)
        response = self.client.post(self.url, {'token': token})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'SimplyBook', status_code=409)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')
        post.assert_not_called()

    def test_link_expires_if_original_slot_changes(self):
        self.appointment.starts_at += timedelta(hours=1)
        self.appointment.save(update_fields=['starts_at'])
        response = self.client.post(self.url, {'token': self.token})
        self.assertEqual(response.status_code, 403)

    def test_cancellation_deadline_enforced_even_with_valid_token(self):
        self.appointment.starts_at = timezone.now() + timedelta(hours=23)
        self.appointment.ends_at = self.appointment.starts_at + timedelta(minutes=15)
        self.appointment.save(update_fields=['starts_at', 'ends_at'])
        token = cancellation_token(self.appointment)
        response = self.client.post(self.url, {'token': token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stornierungsfrist')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')

    def test_csrf_required_before_confirmed_cancellation(self):
        secure = Client(enforce_csrf_checks=True)
        response = secure.post(self.url, {'token': self.token})
        self.assertEqual(response.status_code, 403)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')
