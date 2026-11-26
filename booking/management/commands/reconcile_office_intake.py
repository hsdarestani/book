from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from booking.intake_forms import reconcile_unassigned_form
from booking.models import OfficeIntakeForm


class Command(BaseCommand):
    help = ('Reconcile existing unassigned signed Office forms by the same automatic '
            '3-of-5 rules as new submissions. Dry-run unless --apply. No patient data is printed.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        apply = options['apply']
        # Snapshot only unassigned forms; assignment itself rechecks the row under lock.
        form_ids = list(OfficeIntakeForm.objects.filter(status='review', customer__isnull=True)
                        .order_by('submitted_at', 'pk').values_list('pk', flat=True))
        outcomes = Counter()
        for form_id in form_ids:
            try:
                outcomes[reconcile_unassigned_form(form_id, apply=apply)] += 1
            except Exception:
                # Never emit exception text: data or private file paths may be embedded.
                outcomes['error_rolled_back'] += 1
        self.stdout.write('mode=' + ('apply' if apply else 'preview'))
        self.stdout.write('total=' + str(len(form_ids)))
        for key in sorted(outcomes):
            self.stdout.write(f'{key}={outcomes[key]}')
        if outcomes['error_rolled_back']:
            raise CommandError('One or more forms could not be reconciled; their transactions were rolled back.')
