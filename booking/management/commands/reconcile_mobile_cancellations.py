from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ...models import MobileStaffCancellation
from ...notifications import _post_internal, appointment_snapshot, notify_admin_changed


class Command(BaseCommand):
    help = 'Retry package credit restoration for cancelled mobile-staff appointments.'

    def handle(self, **options):
        now = timezone.now()
        due = list(MobileStaffCancellation.objects.filter(
            completed_at__isnull=True, next_attempt_at__lte=now,
        ).order_by('next_attempt_at').values_list('pk', flat=True)[:50])
        for pk in due:
            appointment = None
            with transaction.atomic():
                item = MobileStaffCancellation.objects.select_for_update().get(pk=pk)
                if item.completed_at or item.next_attempt_at > now:
                    continue
                item.attempts += 1
                reply = _post_internal(
                    getattr(settings, 'MOBILE_STAFF_PACKAGE_CANCEL_URL',
                            'https://app.a-esthetic.de/api/mobile/internal/staff-cancel-package/'),
                    {'booking_public_id': str(item.booking_public_id)},
                )
                if reply.get('ok'):
                    item.completed_at = timezone.now()
                    appointment = item.appointment
                else:
                    backoff = min(3600, 60 * 2 ** min(6, item.attempts - 1))
                    item.next_attempt_at = timezone.now() + timedelta(seconds=backoff)
                    self.stderr.write(f'Cancellation {pk} pending after attempt {item.attempts}.')
                item.save(update_fields=['attempts', 'next_attempt_at', 'completed_at'])
            if appointment and appointment.status == 'cancelled':
                try:
                    notify_admin_changed(appointment, {**appointment_snapshot(appointment), 'status': 'confirmed'})
                except Exception:
                    self.stderr.write(f'Cancellation {pk} credit settled. Notification failed.')
