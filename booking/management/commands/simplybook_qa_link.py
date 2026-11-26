from django.core.management.base import BaseCommand, CommandError
from booking.clinical_time import parse_clinic_wall_time
from booking.models import Appointment
from booking.simplybook_outbound import SyncConflict, reconcile_existing, sync_existing

class Command(BaseCommand):
    help = 'Preflight or explicitly link one synthetic Ariane appointment; no bulk export.'
    def add_arguments(self, parser):
        parser.add_argument('--date',required=True)
        parser.add_argument('--time',required=True)
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--reconcile', action='store_true',
                            help='Read back an uncertain write. With --apply, save only a verified local link.')
    def handle(self,*args,**options):
        start = parse_clinic_wall_time(options['date'], options['time'])
        if start is None:
            raise CommandError('Expected an unambiguous Berlin date and time.')
        matches=list(Appointment.objects.filter(customer__first_name='Test',customer__last_name='Farahani',
            staff__display_name='Frau Ariane Regaei',service__slug='laser-haarentfernung',
            starts_at=start,source='app',status__in=['new','confirmed']))
        if len(matches)!=1:
            raise CommandError('Expected exactly one synthetic QA booking; no write.')
        try:
            operation = reconcile_existing if options['reconcile'] else sync_existing
            result = operation(matches[0].pk, apply=options['apply'])
        except Exception as exc:
            # Never print RPC payloads or patient contact data.
            raise CommandError(str(exc) if isinstance(exc,SyncConflict) else 'Source operation unavailable; inspect state privately; no blind retry.') from None
        self.stdout.write('SIMPLYBOOK_QA_RESULT='+result['result'])
        if result.get('source_booking_id'):
            self.stdout.write('SIMPLYBOOK_QA_LINK_VERIFIED=yes')
