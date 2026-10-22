"""Remove strictly unreferenced synthetic SimplyBook booking placeholders.

Run dry-run first. --apply requires a pre-created, verified DB backup.
Never merge real patients and never cascade/delete appointments or records.
"""
import json
import os
import re
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from booking.models import Appointment, Customer


_SYNTHETIC = re.compile(r'^simplybook-booking-([0-9]+)@invalid\\.local$', re.IGNORECASE)


def candidate_groups():
    groups = defaultdict(list)
    for item in Customer.objects.filter(
        first_name='SimplyBook', last_name='Kunde', phone=''
    ).order_by('pk'):
        if _SYNTHETIC.fullmatch(item.email or ''):
            groups[item.email.lower()].append(item)
    return groups


def has_any_relation(customer):
    """Check every reverse FK/M2M relation including future schema additions."""
    for relation in Customer._meta.related_objects:
        field = relation.field
        if relation.related_model._base_manager.filter(**{field.name: customer}).exists():
            return True
    return False


class Command(BaseCommand):
    help = 'Report or conservatively remove orphaned SimplyBook booking placeholder rows.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-file', default='')

    def handle(self, *args, **options):
        backup = str(options.get('backup_file') or '')
        if options['apply'] and (not backup or not os.path.isfile(backup) or os.path.getsize(backup) < 1024):
            raise CommandError('Refusing cleanup without an existing verified database backup file.')
        with transaction.atomic():
            groups = candidate_groups()
            safe_ids=[]
            protected=0
            source_keepers=0
            for email, customers in groups.items():
                booking_id=_SYNTHET.fullmatch(email).group(1)
                keeper_ids=set(Appointment.objects.filter(
                    idempotency_key=f'simplybook-{booking_id}'
                ).values_list('customer_id', flat=True))
                # A current imported appointment must anchor every source
                # group. Otherwise leave all records untouched for review.
                if not keeper_ids or not keeper_ids.issubset({row.pk for row in customers}):
                    protected+=len(customers)
                    continue
                source_keepers+=len(keeper_ids)
                for row in customers:
                    if row.pk in keeper_ids:
                        continue
                    if has_any_relation(row):
                        protected+=1
                    else:
                        safe_ids.append(row.pk)
            deleted=0
            if options['apply']:
                for item in Customer.objects.select_for_update().filter(pk__in=safe_ids):
                    if has_any_relation(item):
                        protected+=1
                        continue
                    # Re-evaluate the source keeper inside the lock.
                    booking_id=_SYNTHET.fullmatch(item.email.lower()).group(1)
                    if not Appointment.objects.filter(
                        idempotency_key=f'simplybook-{booking_id}'
                    ).exclude(customer=item).exists():
                        protected+=1
                        continue
                    item.delete()
                    deleted+=1
            result={
                'placeholder_groups':len(groups),
                'source_appointment_keepers':source_keepers,
                'safe_orphan_candidates':len(safe_ids),
                'other_protected_rows':protected,
                'deleted':deleted,
                'mode':'apply' if options['apply'] else 'dry-run',
            }
            self.stdout.write('SIMPLYBOOK_ORPHANS_JSON='+json.dumps(result,sort_keys=True))
