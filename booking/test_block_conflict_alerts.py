import io
import os
from datetime import datetime, timedelta, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from booking.models import (
    Appointment, BlockedBookingConflictAlert, BlockedPeriod,
    Customer, Service, StaffMember,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    BOOKING_NOTIFICATION_EMAIL="info@a-esthetic.de",
    BOOKING_NOTIFICATION_BCC_EMAIL="audit@example.com",
)
class SimplyBookBlockedBookingAlertTests(TestCase):
    def setUp(self):
        self.staff = StaffMember.objects.create(
            display_name="Frau Ariane Regaei", role="doctor", active=True,
        )
        self.service = Service.objects.create(
            name="Hyaluron", slug="block-conflict-test", duration_minutes=40,
            buffer_minutes=0, active=True, bookable=True,
        )
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name="Anna", last_name="Beispiel",
            phone="+490000000", email="anna@example.org",
        )
        local_day = timezone.localdate() + timedelta(days=5)
        tz = ZoneInfo("Europe/Berlin")
        self.slot = datetime.combine(local_day, time(19, 0), tzinfo=tz)
        self.appointment = Appointment.objects.create(
            staff=self.staff, service=self.service, customer=self.customer,
            starts_at=self.slot, ends_at=self.slot + timedelta(minutes=40),
            status="confirmed", source="app",
        )
        self.note = {
            "id": 700,
            "start_date_time": self.slot.replace(hour=16).strftime("%Y-%m-%d %H:%M:%S"),
            "end_date_time": self.slot.replace(hour=20).strftime("%Y-%m-%d %H:%M:%S"),
            "note": "Gesperrt",
            "time_blocked": True,
        }

    def sync(self, *, suppress=False):
        def source(url, **kwargs):
            if url.endswith("/admin/auth"):
                return {"token": "test-token"}
            return [dict(self.note)] if self.note is not None else []
        with patch.dict(os.environ, {
            "SIMPLYBOOK_COMPANY_LOGIN": "test-company",
            "SIMPLYBOOK_USER_LOGIN": "test-user",
            "SIMPLYBOOK_USER_PASSWORD": "test-password",
        }):
            with patch("booking.management.commands.sync_simplybook_notes._request_json", side_effect=source):
                output = io.StringIO()
                call_command(
                    "sync_simplybook_notes", suppress_conflict_alerts=suppress,
                    stdout=output,
                )
                return output.getvalue()

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_new_source_block_warns_admin_by_email_and_push_once(self, push):
        output = self.sync()
        self.assertIn('"conflicts_queued": 1', output)
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["info@a-esthetic.de"])
        self.assertEqual(message.bcc, ["audit@example.com"])
        self.assertNotIn(self.customer.email, message.to)
        self.assertIn("Terminkonflikt", message.subject)
        self.assertIn("Anna Beispiel", message.body)
        self.assertIn("16:00", message.body)
        self.assertIn("19:00", message.body)
        push.assert_called_once()
        alert = BlockedBookingConflictAlert.objects.get()
        self.assertIsNotNone(alert.email_sent_at)
        self.assertIsNotNone(alert.push_sent_at)

        # The 10-minute source sync must not re-notify for an unchanged note.
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        push.assert_called_once()

        self.note["note"] = "Gesperrt bitte beachten"
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 1)
        push.assert_called_once()

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_plain_note_then_block_generates_new_alert(self, push):
        self.note["time_blocked"] = False
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

        self.note["time_blocked"] = True
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        push.assert_called_once()

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_unblock_resolves_alert_reblock_creates_new_event(self, push):
        self.sync()
        self.note["time_blocked"] = False
        self.sync()
        old = BlockedBookingConflictAlert.objects.order_by("pk").first()
        self.assertIsNotNone(old.resolved_at)

        self.note["time_blocked"] = True
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(push.call_count, 2)

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_non_overlapping_block_and_cancelled_appointments_do_not_alert(self, push):
        self.appointment.status = "cancelled"
        self.appointment.save(update_fields=["status"])
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        push.assert_not_called()

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_baseline_does_not_send_historic_block_alerts(self, push):
        self.sync(suppress=True)
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 0)
        self.sync()
        self.assertEqual(BlockedBookingConflictAlert.objects.count(), 0)
        push.assert_not_called()

    @patch("booking.block_conflict_alerts._send_admin_conflict_push")
    def test_retry_failed_push_without_repeating_email(self, push):
        push.side_effect = [{"ok": False, "error": "temporarily_unavailable"}, {"ok": True}]
        self.sync()
        self.assertEqual(len(mail.outbox), 1)
        alert = BlockedBookingConflictAlert.objects.get()
        self.assertIsNotNone(alert.email_sent_at)
        self.assertIsNone(alert.push_sent_at)
        # The unchanged note still retries the missing channel.
        self.sync()
        self.assertEqual(len(mail.outbox), 1)
        alert.refresh_from_db()
        self.assertIsNotNone(alert.push_sent_at)
        self.assertEqual(push.call_count, 2)

    @patch("booking.block_conflict_alerts._send_admin_conflict_push", return_value={"ok": True})
    def test_removed_source_note_does_not_send_again(self, push):
        self.sync()
        self.note = None
        self.sync()
        alert = BlockedBookingConflictAlert.objects.get()
        self.assertIsNotNone(alert.resolved_at)
        self.assertIsNone(alert.blocked_period_id)
        self.assertEqual(BlockedPeriod.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        push.assert_called_once()
