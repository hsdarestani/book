from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.emails import send_booking_emails
from booking.models import Appointment, ExternalSyncState
from booking.notifications import (
    appointment_snapshot,
    notify_booking_created,
    notify_customer_cancelled,
    notify_customer_rescheduled,
)


SOURCE = "simplybook"


def snapshots():
    return {
        item.idempotency_key: appointment_snapshot(item)
        for item in Appointment.objects.filter(
            idempotency_key__startswith="simplybook-"
        )
    }


class Command(BaseCommand):
    help = "Continuously mirror SimplyBook into Book and notify only on real post-baseline changes."

    def handle(self, *args, **options):
        state, _ = ExternalSyncState.objects.get_or_create(source=SOURCE)
        before = snapshots()

        # If SimplyBook data already exists locally (for example after a manual
        # migration/import), treat that known local state as the notification
        # baseline before contacting SimplyBook. Any booking that appears after
        # this point is genuinely new to our system and may notify.
        if state.baseline_completed_at is None and before:
            state.baseline_completed_at = timezone.now()
            state.metadata = {
                **(state.metadata or {}),
                "baseline_mode": "existing_local_state",
                "baseline_count": len(before),
            }
            state.save(update_fields=["baseline_completed_at", "metadata"])

        # Import is transactional: never silently accept an incomplete source mirror.
        call_command("simplybook_import", strict=True)
        call_command("fix_simplybook_owner")
        notes_status = "ok"
        try:
            call_command("sync_simplybook_notes")
        except CommandError as exc:
            # SimplyBook's notes API is independently rate limited. A
            # temporary 403 "Too many attempts" must not invalidate a
            # successful, transactionally complete bookings+clients sync.
            # Never mask authentication errors, bad payloads or other faults.
            message = str(exc).lower()
            if "too many attempts" in message or "http 429" in message:
                notes_status = "rate_limited"
                self.stderr.write(self.style.WARNING(
                    "SimplyBook calendar notes rate limited; leave previous notes intact and retry next interval."
                ))
            else:
                raise
        # Keep duplicate rows intact. SimplyBook import already resolves exact identities via find_customer.
        # Automatic merge/delete here can move historical bookings across source identities.

        after = snapshots()

        # Fresh installation / empty local database: the first completed import
        # is reconciliation only. Store it as baseline and deliberately suppress
        # all email/push side effects so historical SimplyBook appointments do
        # not look like fresh bookings.
        if state.baseline_completed_at is None:
            state.baseline_completed_at = timezone.now()
            state.last_success_at = timezone.now()
            state.metadata = {
                **(state.metadata or {}),
                "baseline_mode": "first_import",
                "baseline_count": len(after),
                "last_notes_status": notes_status,
                "last_notes_success_at": (timezone.now().isoformat() if notes_status == "ok" else state.metadata.get("last_notes_success_at")),
            }
            state.save(
                update_fields=[
                    "baseline_completed_at",
                    "last_success_at",
                    "metadata",
                ]
            )
            self.stdout.write(self.style.SUCCESS(
                f"SimplyBook baseline completed: appointments={len(after)}, notifications_suppressed=yes"
            ))
            return

        now = timezone.now()
        created = changed = cancelled = 0
        current = (
            Appointment.objects.filter(
                idempotency_key__startswith="simplybook-"
            )
            .select_related("customer", "service", "staff")
        )

        for item in current:
            previous = before.get(item.idempotency_key)
            if previous is None:
                if item.starts_at > now and item.status != "cancelled":
                    send_booking_emails(item)
                    notify_booking_created(item)
                    created += 1
                continue

            current_state = appointment_snapshot(item)
            if current_state == previous or item.starts_at <= now:
                continue
            # A corrected source client link is a data reconciliation, not an
            # appointment change. Do not send an erroneous reschedule email.
            if {k:v for k,v in current_state.items() if k != "customer_id"} == {k:v for k,v in previous.items() if k != "customer_id"}:
                continue

            if (
                previous.get("status") != "cancelled"
                and item.status == "cancelled"
            ):
                notify_customer_cancelled(item)
                cancelled += 1
            elif item.status != "cancelled":
                if previous.get("starts_at") != current_state.get("starts_at"):
                    item.reminder_1h_sent_at = None
                    item.save(update_fields=["reminder_1h_sent_at"])
                notify_customer_rescheduled(item)
                changed += 1

        state.last_success_at = timezone.now()
        state.metadata = {
            **(state.metadata or {}),
            "last_snapshot_count": len(after),
            "last_created": created,
            "last_changed": changed,
            "last_cancelled": cancelled,
            "last_notes_status": notes_status,
            "last_notes_success_at": (timezone.now().isoformat() if notes_status == "ok" else state.metadata.get("last_notes_success_at")),
        }
        state.save(update_fields=["last_success_at", "metadata"])

        self.stdout.write(self.style.SUCCESS(
            "SimplyBook continuous sync completed: "
            f"new={created}, changed={changed}, cancelled={cancelled}"
        ))
