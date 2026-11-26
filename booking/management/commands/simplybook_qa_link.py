from datetime import datetime
from zoneinfo import ZoneInfo
from django.core.management.base import BaseCommand, CommandError
from booking.models import Appointment
from booking.simplybook_outbound import sync_existing

class Command(BaseCommand):
    help = 'Preflight or explicitly link one synthetic Ariane appointment; no bulk export.'
    def add_arguments(self, parser):
        parser.add_argument('--date',required=True)
        parser.add_argument('--time',required=True)
        parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        start=datetime.fromisoformat(options['date']+'T'+options['time']).replace(tzinfo=ZoneInfo('Europe/Berlin'))
        matches=list(Appointment.objects.filter(customer__first_name='Test',customer__last_name='Farahani',
            staff__display_name='Frau Ariane Regaei',service__slug='laser-haarentfernung',
            starts_at=start,source='app',status__in=['new','confirmed']))
        if len(matches)!=1:
            raise CommandError('Expected exactly one synthetic QA booking; no write.')
        try:
            result=sync_existing(matches[0].pk,apply=options['apply'])
        except Exception as exc:
            # Never print RPC payloads or patient contact data.
            from booking.simplybook_outbound import SyncConflict
            raise CommandError(str(exc) if isinstance(exc,SyncConflict) else 'Source operation unavailable; inspect state privately; no blind retry.') from None
        self.stdout.write('SIMPLYBOOK_QA_RESULT='+result['result'])
        if result.get('source_booking_id'):
            self.stdout.write('SIMPLYBOOK_QA_LINK_VERIFIED=yes')
