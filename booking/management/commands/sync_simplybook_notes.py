import json
import os
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from booking.clinical_time import parse_appointment_start
from booking.models import BlockedPeriod, ExternalSyncState, StaffMember
from booking.simplybook_calendar import WRITE_STATE, record_revision
from booking.block_conflict_alerts import (
    enqueue_block_conflicts, process_pending_block_conflict_alerts, resolve_block_conflicts,
)

AUTH_URL = 'https://user-api-v2.simplybook.me/admin/auth'
NOTES_URL = 'https://user-api-v2.simplybook.me/admin/calendar-notes'
MARKER_SEP = '\u2063'
ZERO = '\u200b'
ONE = '\u200c'


def _request_json(url, *, method='GET', payload=None, headers=None, timeout=120):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json', **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read(800).decode('utf-8', errors='replace')
        category = ': too many attempts' if 'too many attempts' in detail.lower() else ''
        raise CommandError(f'SimplyBook notes HTTP {exc.code}{category}') from None
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        raise CommandError('SimplyBook notes response could not be read.') from None


def _items_from_page(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('data', 'items', 'results', 'result'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for nested in ('data', 'items', 'results'):
                    nested_value = value.get(nested)
                    if isinstance(nested_value, list):
                        return nested_value
    raise CommandError('Unexpected SimplyBook calendar note list.')


def _total_pages(payload):
    if not isinstance(payload, dict):
        return None
    candidates = [payload, payload.get('metadata'), payload.get('meta'), payload.get('pagination')]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ('pages_count', 'total_pages', 'pages', 'page_count', 'last_page'):
            try:
                value = int(candidate.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


def _marker(note_id):
    try:
        value = max(0, int(note_id))
    except (TypeError, ValueError):
        value = abs(hash(str(note_id)))
    bits = bin(value)[2:] or '0'
    return MARKER_SEP + ''.join(ONE if bit == '1' else ZERO for bit in bits) + MARKER_SEP


def _clean_text(value):
    return ' '.join(str(value or '').replace('\r', ' ').replace('\n', ' ').split())


class Command(BaseCommand):
    help = 'Synchronizes SimplyBook calendar notes/time blocks to Frau Ariane Regaei.'

    def add_arguments(self, parser):
        parser.add_argument('--note-id', type=int, help='Reconcile one verified SimplyBook note ID.')
        parser.add_argument(
            '--suppress-conflict-alerts', action='store_true', default=False,
            help='Baseline import: do not notify for historically imported blocks.',
        )

    def handle(self, *args, **options):
        suppressed = bool(options.get('suppress_conflict_alerts'))
        note_id = options.get('note_id')
        if note_id is not None and not 0 < note_id < 10**18:
            raise CommandError('Invalid SimplyBook calendar note ID.')
        with transaction.atomic():
            ExternalSyncState.objects.select_for_update().get_or_create(source=WRITE_STATE)
            summary = self._sync(suppressed, source_note_id=note_id)

        # Keep notification delivery outside the source synchronization lock.
        summary['conflict_delivery'] = process_pending_block_conflict_alerts() if not suppressed else {}
        self.stdout.write('SIMPLYBOOK_NOTES_SYNC_JSON=' + json.dumps(summary, sort_keys=True))
        self.stdout.write(self.style.SUCCESS('SimplyBook calendar notes synchronized to Frau Ariane Regaei.'))

    def _sync(self, suppressed, *, source_note_id=None, source=None):
        if source is None:
            company = (os.environ.get('SIMPLYBOOK_COMPANY_LOGIN') or '').strip()
            login = (os.environ.get('SIMPLYBOOK_USER_LOGIN') or '').strip()
            password = (os.environ.get('SIMPLYBOOK_USER_PASSWORD') or '').strip()
            if not company or not login or not password:
                raise CommandError('SIMPLYBOOK_COMPANY_LOGIN, SIMPLYBOOK_USER_LOGIN and SIMPLYBOOK_USER_PASSWORD are required for calendar-note sync.')

            auth = _request_json(AUTH_URL, method='POST', payload={
                'company': company,
                'login': login,
                'password': password,
            })
            token = str((auth or {}).get('token') or '').strip() if isinstance(auth, dict) else ''
            if not token:
                if isinstance(auth, dict) and auth.get('require2fa'):
                    raise CommandError('SimplyBook REST authentication requires 2FA; calendar notes cannot be synchronized unattended.')
                raise CommandError('SimplyBook REST authentication returned no token.')

            headers = {'X-Company-Login': company, 'X-Token': token}

            def source(path):
                return _request_json(NOTES_URL + path, headers=headers)
        all_notes = []
        source_ids = set()
        if source_note_id is not None:
            try:
                row = source(f'/{source_note_id}')
            except CommandError as exc:
                if str(exc) != 'SimplyBook notes HTTP 404':
                    raise
            else:
                if not isinstance(row, dict) or str(row.get('id')) != str(source_note_id):
                    raise CommandError('SimplyBook calendar note identity did not match.')
                all_notes = [row]
                source_ids = {str(source_note_id)}
        else:
            per_page = 100
            for page in range(1, 501):
                query = urllib.parse.urlencode([
                    ('page', page),
                    ('on_page', per_page),
                    ('filter[date_from]', '2000-01-01'),
                    ('filter[date_to]', '2035-12-31'),
                ])
                payload = source(f'?{query}')
                items = _items_from_page(payload)
                for item in items:
                    note_id = str(item.get('id', '')) if isinstance(item, dict) else ''
                    if not (0 < len(note_id) <= 19 and note_id.isascii() and note_id.isdecimal() and note_id[0] != '0'):
                        raise CommandError('Invalid SimplyBook calendar note identity.')
                    if note_id in source_ids:
                        raise CommandError('SimplyBook calendar notes changed during paging.')
                    source_ids.add(note_id)
                all_notes.extend(items)
                total_pages = _total_pages(payload)
                last_page = page >= total_pages if total_pages is not None else len(items) < per_page
                if last_page:
                    break
            else:
                raise CommandError('SimplyBook calendar note list did not finish paging.')

        ariane = StaffMember.objects.filter(display_name='Frau Ariane Regaei').order_by('pk').first()
        if ariane is None:
            raise CommandError('Frau Ariane Regaei was not found; refusing to import SimplyBook notes elsewhere.')

        seen_markers = {_marker(note_id) for note_id in source_ids}
        created = 0
        updated = 0
        skipped = 0
        conflicts_queued = 0
        with transaction.atomic():
            for row in all_notes:
                note_id = row.get('id')
                starts_at = parse_appointment_start(row.get('start_date_time') or row.get('from'))
                ends_at = parse_appointment_start(row.get('end_date_time') or row.get('to'))
                if not starts_at or not ends_at or ends_at <= starts_at:
                    skipped += 1
                    continue

                marker = _marker(note_id)
                blocked_value = row.get('time_blocked')
                blocked = blocked_value is True or str(blocked_value).strip().lower() in ('1', 'true', 'yes')
                prefix = '[BLOCKNOTE][STAFF]' if blocked else '[NOTE][STAFF]'
                text = _clean_text(row.get('note')) or ('Gesperrt' if blocked else 'Notiz')
                max_text = max(1, 160 - len(prefix) - len(marker) - 2)
                reason = f'{prefix} {text[:max_text]}{marker}'

                item = BlockedPeriod.objects.select_for_update().filter(
                    staff=ariane, reason__endswith=marker,
                ).order_by('pk').first()
                if item:
                    was_blocking = (item.reason or '').startswith('[BLOCKNOTE]')
                    period_changed = item.starts_at != starts_at or item.ends_at != ends_at
                    became_blocking = blocked and not was_blocking
                    changed = period_changed or item.reason != reason
                    if changed:
                        # Suppress stale alerts if this blocker was moved or unblocked.
                        if period_changed or (was_blocking and not blocked):
                            resolve_block_conflicts(item)
                        item.starts_at = starts_at
                        item.ends_at = ends_at
                        item.reason = reason
                        item.save(update_fields=['starts_at', 'ends_at', 'reason'])
                        updated += 1
                        # Text-only edits must not produce a fresh alert.
                        if blocked and (period_changed or became_blocking) and not suppressed:
                            conflicts_queued += enqueue_block_conflicts(
                                item, source_note_id=note_id,
                            )
                else:
                    item = BlockedPeriod.objects.create(
                        staff=ariane, starts_at=starts_at, ends_at=ends_at, reason=reason,
                    )
                    created += 1
                    if blocked and not suppressed:
                        conflicts_queued += enqueue_block_conflicts(
                            item, source_note_id=note_id,
                        )
                record_revision(item, row)

            stale = []
            stored = BlockedPeriod.objects.filter(staff=ariane, reason__contains=MARKER_SEP)
            if source_note_id is not None:
                stored = stored.filter(reason__endswith=_marker(source_note_id))
            for item in stored:
                if not item.simplybook_managed:
                    continue
                reason = item.reason or ''
                marker_start = reason.rfind(MARKER_SEP, 0, max(0, len(reason) - 1))
                marker = reason[marker_start:] if marker_start >= 0 else ''
                if marker and marker not in seen_markers:
                    stale.append(item.pk)
            deleted = len(stale)
            if stale:
                for item in BlockedPeriod.objects.filter(pk__in=stale):
                    resolve_block_conflicts(item)
                BlockedPeriod.objects.filter(pk__in=stale).delete()

        return {
            'source_notes': len(all_notes),
            'created': created,
            'updated': updated,
            'deleted': deleted,
            'skipped': skipped,
            'conflicts_queued': conflicts_queued,
            'owner': ariane.display_name,
        }
