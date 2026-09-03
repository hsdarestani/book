import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from booking.models import BlockedPeriod, StaffMember
from booking.management.commands.sync_simplybook_notes import MARKER_SEP


class Command(BaseCommand):
    help = 'Prints safe date/time diagnostics for SimplyBook-imported calendar notes without exposing note text.'

    def handle(self, *args, **options):
        ariane = StaffMember.objects.filter(display_name='Frau Ariane Regaei').order_by('pk').first()
        if ariane is None:
            raise CommandError('Frau Ariane Regaei was not found.')

        qs = BlockedPeriod.objects.filter(staff=ariane, reason__contains=MARKER_SEP).order_by('starts_at', 'pk')
        today = timezone.localdate()

        rows = []
        for item in qs:
            local_start = timezone.localtime(item.starts_at)
            local_end = timezone.localtime(item.ends_at)
            rows.append({
                'date': local_start.date().isoformat(),
                'start': local_start.strftime('%H:%M'),
                'end': local_end.strftime('%H:%M'),
                'blocked': (item.reason or '').startswith('[BLOCKNOTE]'),
            })

        future = [row for row in rows if row['date'] >= today.isoformat()][:12]
        recent_past = [row for row in rows if row['date'] < today.isoformat()][-12:]
        blocked_rows = [row for row in rows if row['blocked']]
        nonblocked_rows = [row for row in rows if not row['blocked']]
        nonblocked_future = [row for row in nonblocked_rows if row['date'] >= today.isoformat()][:12]
        nonblocked_recent = [row for row in nonblocked_rows if row['date'] < today.isoformat()][-12:]

        counts = list(
            qs.values('starts_at__date')
            .annotate(count=Count('id'))
            .order_by('starts_at__date')
        )
        nearest_dates = []
        for row in counts:
            day = row['starts_at__date']
            nearest_dates.append({'date': day.isoformat(), 'count': row['count']})
        nearest_dates.sort(key=lambda row: (abs((timezone.datetime.fromisoformat(row['date']).date() - today).days), row['date']))

        payload = {
            'today': today.isoformat(),
            'total': len(rows),
            'blocked_count': len(blocked_rows),
            'nonblocked_count': len(nonblocked_rows),
            'earliest': rows[0] if rows else None,
            'latest': rows[-1] if rows else None,
            'nearest_dates': nearest_dates[:12],
            'future_samples': future,
            'recent_past_samples': recent_past,
            'nonblocked_future_samples': nonblocked_future,
            'nonblocked_recent_samples': nonblocked_recent,
        }
        self.stdout.write('SIMPLYBOOK_NOTE_DATES_JSON=' + json.dumps(payload, sort_keys=True))
