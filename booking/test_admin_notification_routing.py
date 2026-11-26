from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from booking.emails import send_booking_emails
from booking.models import Appointment, Customer, Service, StaffMember
from booking.notifications import (appointment_snapshot, notify_admin_created, notify_admin_changed, notify_admin_deleted, notify_admin_source_changed)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    BOOKING_NOTIFICATION_EMAIL="info@a-esthetic.de",
    BOOKING_NOTIFICATION_BCC_EMAIL="audit@example.com",
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
        self.assertEqual(admin.bcc, ["audit@example.com"])
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
        self.assertEqual(mail.outbox[0].bcc, ["audit@example.com"])
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

    @patch("booking.notifications._post_internal", return_value={"ok": True})
    def test_staff_created_alerts_admin_without_duplicate_customer_email(self, relay):
        notify_admin_created(self.appointment)
        targets = [call.args[1].get("target") for call in relay.call_args_list]
        self.assertEqual(targets.count("admin"), 1)
        self.assertEqual(targets.count("customer"), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["info@a-esthetic.de"])
        self.assertIn("NEUER TERMIN", mail.outbox[0].subject)

    @patch("booking.notifications._post_internal", return_value={"ok": True})
    def test_staff_status_changes_alert_admin_and_noop_does_not(self, relay):
        before = appointment_snapshot(self.appointment)
        notify_admin_changed(self.appointment, before)
        relay.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)
        self.appointment.status = "completed"
        notify_admin_changed(self.appointment, before)
        self.assertEqual(sum(c.args[1].get("target") == "admin" for c in relay.call_args_list), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["info@a-esthetic.de"])

    @patch("booking.notifications._post_internal", return_value={"ok": True})
    def test_staff_cancel_and_delete_alert_admin_and_customer_once(self, relay):
        before = appointment_snapshot(self.appointment)
        self.appointment.status = "cancelled"
        notify_admin_changed(self.appointment, before)
        self.assertEqual(sum(c.args[1].get("target") == "admin" for c in relay.call_args_list), 1)
        self.assertEqual(len(mail.outbox), 2)
        relay.reset_mock()
        mail.outbox.clear()
        notify_admin_deleted(self.appointment)
        self.assertEqual(sum(c.args[1].get("target") == "admin" for c in relay.call_args_list), 1)
        self.assertEqual(len(mail.outbox), 2)

    @patch("booking.notifications._post_internal", return_value={"ok": True})
    def test_verified_source_change_alerts_only_admin(self, relay):
        before = appointment_snapshot(self.appointment)
        self.appointment.status = "cancelled"
        notify_admin_source_changed(self.appointment, before)
        self.assertEqual([c.args[1].get("target") for c in relay.call_args_list], ["admin"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["info@a-esthetic.de"])

    @patch("booking.notifications._post_internal", return_value={"ok": True})
    def test_cancellation_reconciliation_does_not_repeat_admin_alert(self, relay):
        before = appointment_snapshot(self.appointment)
        self.appointment.status = "cancelled"
        notify_admin_source_changed(self.appointment, before)
        notify_admin_changed(self.appointment, before, include_admin=False)
        targets = [c.args[1].get("target") for c in relay.call_args_list]
        self.assertEqual(targets.count("admin"), 1)
        self.assertEqual(targets.count("customer"), 1)
        self.assertEqual(len(mail.outbox), 2)
