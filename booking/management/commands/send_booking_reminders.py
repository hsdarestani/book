from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import Appointment
from booking.notifications import notify_24h_reminder


class Command(BaseCommand):
    help = "Send one push reminder for upcoming appointments within the next 24 hours."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now + timedelta(hours=24)
        appointments = (
            Appointment.objects.filter(
                status__in=["new", "confirmed"],
                starts_at__gt=now,
                starts_at__lte=cutoff,
                reminder_24h_sent_at__isnull=True,
            )
            .select_related("customer", "service", "staff")
            .order_by("starts_at")[:500]
        )

        sent = 0
        pending_retry = 0
        for appointment in appointments:
            result = notify_24h_reminder(appointment)
            if result.get("ok"):
                updated = Appointment.objects.filter(
                    pk=appointment.pk,
                    reminder_24h_sent_at__isnull=True,
                ).update(reminder_24h_sent_at=timezone.now())
                sent += int(bool(updated))
            else:
                pending_retry += 1

        self.stdout.write(self.style.SUCCESS(
            f"Booking reminders processed: sent={sent}, pending_retry={pending_retry}"
        ))
