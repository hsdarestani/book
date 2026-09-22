from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.emails import send_booking_emails
from booking.models import Appointment
from booking.notifications import appointment_snapshot, notify_booking_created, notify_customer_cancelled, notify_customer_rescheduled


def snapshots():
    return {
        item.idempotency_key: appointment_snapshot(item)
        for item in Appointment.objects.filter(idempotency_key__startswith="simplybook-")
    }


class Command(BaseCommand):
    help = "Continuously mirror SimplyBook into Book and notify only on real future changes."

    def handle(self, *args, **options):
        before = snapshots()
        call_command("simplybook_import")
        call_command("fix_simplybook_owner")
        call_command("sync_simplybook_notes")
        call_command("dedupe_customers")

        now = timezone.now()
        created = changed = cancelled = 0
        current = Appointment.objects.filter(
            idempotency_key__startswith="simplybook-"
        ).select_related("customer", "service", "staff")

        for item in current:
            previous = before.get(item.idempotency_key)
            if previous is None:
                if item.starts_at > now and item.status != "cancelled":
                    send_booking_emails(item)
                    notify_booking_created(item)
                    created += 1
                continue

            state = appointment_snapshot(item)
            if state == previous or item.starts_at <= now:
                continue
            if previous.get("status") != "cancelled" and item.status == "cancelled":
                notify_customer_cancelled(item)
                cancelled += 1
            elif item.status != "cancelled":
                if previous.get("starts_at") != state.get("starts_at"):
                    item.reminder_1h_sent_at = None
                    item.save(update_fields=["reminder_1h_sent_at"])
                notify_customer_rescheduled(item)
                changed += 1

        self.stdout.write(self.style.SUCCESS(
            f"SimplyBook continuous sync completed: new={created}, changed={changed}, cancelled={cancelled}"
        ))
