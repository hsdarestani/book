from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from booking.models import StaffBookingAlert
from booking.notifications import _push, _local_start
from booking.emails import send_admin_appointment_event_email

class Command(BaseCommand):
    help = 'Deliver durable native admin booking alerts outside HTTP requests.'
    def handle(self, *args, **options):
        now = timezone.now()
        ids = list(StaffBookingAlert.objects.filter(next_attempt_at__lte=now)
                   .filter(Q(push_sent_at__isnull=True) | Q(email_sent_at__isnull=True))
                   .order_by('next_attempt_at').values_list('pk',flat=True)[:20])
        for pk in ids:
            with transaction.atomic():
                job = StaffBookingAlert.objects.select_for_update().filter(pk=pk).first()
                if not job or job.next_attempt_at > timezone.now():
                    continue
                appointment = job.appointment
                if job.push_sent_at is None:
                    try:
                        local = _local_start(appointment)
                        result = _push(appointment, target='admin', event='admin_created',
                            title='Neue Terminanfrage',
                            body=f'Termin am {local:%d.%m.%Y} um {local:%H:%M}. Details in der App.')
                        if result.get('ok'):
                            job.push_sent_at = timezone.now()
                    except Exception:
                        self.stderr.write('Admin booking push delivery failed.')
                if job.email_sent_at is None:
                    try:
                        if settings.BOOKING_NOTIFICATION_EMAIL:
                            send_admin_appointment_event_email(appointment, 'created')
                            job.email_sent_at = timezone.now()
                    except Exception:
                        self.stderr.write('Admin booking email delivery failed.')
                job.attempts += 1
                job.next_attempt_at = timezone.now() + timedelta(seconds=min(900, 10*2**min(job.attempts,6)))
                job.save(update_fields=['push_sent_at','email_sent_at','attempts','next_attempt_at'])
