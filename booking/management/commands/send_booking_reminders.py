import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from booking.block_conflict_alerts import process_pending_block_conflict_alerts
from booking.emails import send_admin_appointment_event_email
from booking.models import Appointment
from booking.notifications import notify_1h_reminder, notify_admin_1h_reminder


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send one-hour booking reminders to customers and admins via email and push."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now + timedelta(hours=1)
        appointments = (
            Appointment.objects.filter(
                status__in=["new", "confirmed"],
                starts_at__gt=now,
                starts_at__lte=cutoff,
            )
            .filter(
                Q(reminder_1h_sent_at__isnull=True)
                | Q(reminder_1h_admin_email_sent_at__isnull=True)
                | Q(reminder_1h_admin_push_sent_at__isnull=True)
            )
            .select_related("customer", "service", "staff")
            .order_by("starts_at")[:500]
        )
        complete = 0
        pending_retry = 0
        for appointment in appointments:
            # Keep the existing customer reminder intact. An admin failure must
            # never cause a repeat of a successful customer reminder.
            if appointment.reminder_1h_sent_at is None:
                try:
                    result = notify_1h_reminder(appointment)
                    if result.get("ok"):
                        Appointment.objects.filter(
                            pk=appointment.pk, reminder_1h_sent_at__isnull=True,
                        ).update(reminder_1h_sent_at=timezone.now())
                        appointment.reminder_1h_sent_at = timezone.now()
                except Exception:
                    logger.exception("Customer one-hour booking reminder failed")

            # Independent admin delivery flags prevent repeat mail when push is
            # unavailable and allow retrying only the failed delivery channel.
            if appointment.reminder_1h_admin_email_sent_at is None:
                try:
                    send_admin_appointment_event_email(appointment, "reminder_1h")
                    Appointment.objects.filter(
                        pk=appointment.pk, reminder_1h_admin_email_sent_at__isnull=True,
                    ).update(reminder_1h_admin_email_sent_at=timezone.now())
                    appointment.reminder_1h_admin_email_sent_at = timezone.now()
                except Exception:
                    logger.exception("Admin one-hour reminder email failed")

            if appointment.reminder_1h_admin_push_sent_at is None:
                try:
                    result = notify_admin_1h_reminder(appointment)
                    if result.get("ok"):
                        Appointment.objects.filter(
                            pk=appointment.pk, reminder_1h_admin_push_sent_at__isnull=True,
                        ).update(reminder_1h_admin_push_sent_at=timezone.now())
                        appointment.reminder_1h_admin_push_sent_at = timezone.now()
                except Exception:
                    logger.exception("Admin one-hour reminder push failed")

            if (
                appointment.reminder_1h_sent_at is not None
                and appointment.reminder_1h_admin_email_sent_at is not None
                and appointment.reminder_1h_admin_push_sent_at is not None
            ):
                complete += 1
            else:
                pending_retry += 1
        # Retry any previously failed conflict-alert channel even when no
        # appointment falls into the one-hour reminder window.
        conflicts = process_pending_block_conflict_alerts()
        self.stdout.write(self.style.SUCCESS(
            f"Booking 1h reminders processed: sent={complete}, pending_retry={pending_retry}; "
            f"block_conflicts={conflicts['attempted']}, "
            f"conflict_retry={conflicts['pending_retry']}"
        ))
