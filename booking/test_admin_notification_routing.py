from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from booking.emails import send_booking_emails
from booking.models import Appointment, Customer, Service, StaffMember


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    BOOKING_NOTIFICATION_EMAIL="info@a-esthetic.de",
    BOOKING_NOTIFICATION_BCC_EMAIL="hsdf7rb@gmail.com",
)
class AdminNotificationRoutingTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name="Beratung", slug="admin-reminder-test", duration_minutes=30, active=True, bookable=True
        )
        self.staff = StaffMember.objects.create(display_name="Frau Ariane Regaei", active=True)
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name="Anna", last_name="Muster",
            email="anna@example.com", phone="+491234567890",
        )
        start = timezone.now() + timedelta(minutes=45)
        self.appointment = Appointment.objects.create(
            customer=self.customer, service=self.service, staff=self.staff,
            starts_at=start, ends_at=start + timedelta(minutes=30),
            status="confirmed", source="app",
        )

    def test_confirmation_uses_info_and_hidden_bcc_only_for_admin(self):
        send_booking_emails(self.appointment)
        self.assertEqual(len(mail.outbox), 2)
        customer, admin = mail.outbox
        self.assertEqual(customer.to, ["anna@example.com"])
        self.assertEqual(customer.bcc, [])
        self.assertEqual(admin.to, ["info@a-esthetic.de"])
        self.assertEqual(admin.cc, [])
        self.assertEqual(admin.bcc, ["hsdf7rb@gmail.com"])
        self.assertIn("Neuer Termin", admin.subject)

    @patch("booking.management.commands.send_booking_reminders.notify_admin_1h_reminder", return_value={"ok": True})
    @patch("booking.management.commands.send_booking_reminders.notify_1h_reminder", return_value={"ok": True})
    def test_one_hour_customer_and_admin_reminders_sent_once(self, customer_push, admin_push):
        call_command("send_booking_reminders")
        self.appointment.refresh_from_db()
        self.assertIsNotNone(self.appointment.reminder_1h_sent_at)
        self.assertIsNotNone(self.appointment.reminder_1h_admin_email_sent_at)
        self.assertIsNotNone(self.appointment.reminder_1h_admin_push_sent_at)
        customer_push.assert_called_once()
        admin_push.assert_called_once()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["info@a-esthetic.de"])
        self.assertEqual(mail.outbox[0].bcc, ["hsdf7rb@gmail.com"])
        self.assertIn("IN EINER STUNDE", mail.outbox[0].subject)

        call_command("send_booking_reminders")
        self.assertEqual(len(mail.outbox), 1)
        customer_push.assert_called_once()
        admin_push.assert_called_once()

    @patch("booking.management.commands.send_booking_reminders.notify_admin_1h_reminder")
    @patch("booking.management.commands.send_booking_reminders.notify_1h_reminder", return_value={"ok": True})
    def test_retry_only_failed_admin_push_not_customer_or_email(self, customer_push, admin_push):
        admin_push.side_effect = [{"ok": False}, {"ok": True}]
        call_command("send_booking_reminders")
        self.appointment.refresh_from_db()
        self.assertIsNotNone(self.appointment.reminder_1h_sent_at)
        self.assertIsNotNone(self.appointment.reminder_1h_admin_email_sent_at)
        self.assertIsNone(self.appointment.reminder_1h_admin_push_sent_at)
        self.assertEqual(len(mail.outbox), 1)

        call_command("send_booking_reminders")
        self.appointment.refresh_from_db()
        self.assertIsNotNone(self.appointment.reminder_1h_admin_push_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        customer_push.assert_called_once()
        self.assertEqual(admin_push.call_count, 2)

    @patch("booking.management.commands.send_booking_reminders.notify_admin_1h_reminder", return_value={"ok": True})
    @patch("booking.management.commands.send_booking_reminders.notify_1h_reminder", return_value={"ok": True})
    def test_existing_customer_reminder_still_triggers_admin(self, customer_push, admin_push):
        self.appointment.reminder_1h_sent_at = timezone.now()
        self.appointment.save(update_fields=["reminder_1h_sent_at"])
        call_command("send_booking_reminders")
        customer_push.assert_not_called()
        admin_push.assert_called_once()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["info@a-esthetic.de"])
