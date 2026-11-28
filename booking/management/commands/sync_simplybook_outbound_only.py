import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from booking.models import Appointment
from booking.emails import send_booking_emails, send_customer_booking_email
from booking.notifications import notify_admin_created, notify_admin_confirmed, notify_booking_created

class Command(BaseCommand):
    help = 'Process queued SimplyBook outbound requests. Use the shared sync lock.'
    def handle(self, *args, **options):
        # Enabled only after a controlled source lifecycle passes. Queued
        # records have explicit answers; uncertain writes are never retried.
        if os.getenv('SIMPLYBOOK_OUTBOUND_ENABLED') == '1':
            from booking.simplybook_outbound import ARIANE, sync_existing
            queued = Appointment.objects.filter(
                staff__display_name=ARIANE, source__in=['admin', 'app', 'web'], status='new',
                starts_at__gt=timezone.now(), simplybook_sync_state='queued',
                simplybook_booking_id__isnull=True, returning_customer_answered=True,
            ).exclude(referral_source='').order_by('created_at').values_list('pk', flat=True)[:10]
            for pk in list(queued):
                try:
                    result = sync_existing(pk, apply=True)
                except Exception:
                    Appointment.objects.filter(pk=pk, simplybook_sync_state='queued').update(simplybook_sync_state='blocked')
                    self.stderr.write('SimplyBook outbound reservation needs review.')
                    continue
                if result['result'] == 'linked':
                    item = Appointment.objects.select_related('customer', 'service', 'staff').get(pk=pk)
                    callbacks = (send_customer_booking_email, lambda appt: notify_admin_created(appt, include_admin=False), notify_admin_confirmed) if item.source == 'admin' else (
                        send_booking_emails, notify_booking_created)
                    for notify in callbacks:
                        try:
                            notify(item)
                        except Exception:
                            self.stderr.write('Verified reservation notification failed.')
