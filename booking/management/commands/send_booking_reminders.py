from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import Appointment
from booking.notifications import notify_1h_reminder


class Command(BaseCommand):
    help = "Send one push + email reminder for appointments within the next hour."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now + timedelta(hours=1)
        appointments = (
            Appointment.objects.filter(
                status__in=["new", "confirmed"],
                starts_at__gt=now,
                starts_at__lte=cutoff,
                reminder_1h_sent_at__isnull=True,
            )
            .select_related("customer", "service", "staff")
            .order_by("starts_at")[:500]
        )
        sent = 0
        pending_retry = 0
        for appointment in appointments:
            result = notify_1h_reminder(appointment)
            if result.get("ok"):
                updated = Appointment.objects.filter(
                    pk=appointment.pk,
                    reminder_1h_sent_at__isnull=True,
                ).update(reminder_1h_sent_at=timezone.now())
                sent += int(bool(updated))
            else:
                pending_retry += 1
        self.stdout.write(self.style.SUCCESS(
            f"Booking 1h reminders processed: sent={sent}, pending_retry={pending_retry}"
        ))
