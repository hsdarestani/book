import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from booking.models import BlockedPeriod, StaffMember

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
        detail = exc.read().decode('utf-8', errors='replace')[:800]
        raise CommandError(f'SimplyBook notes HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise CommandError(f'SimplyBook notes network error: {exc}') from exc


def _items_from_page(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ('data', 'items', 'results', 'result'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ('data', 'items', 'results'):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    return nested_value
    return []


def _total_pages(payload):
    if not isinstance(payload, dict):
        return None
    candidates = [payload, payload.get('meta'), payload.get('pagination')]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ('total_pages', 'pages', 'page_count', 'last_page'):
            try:
                value = int(candidate.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


def _parse_dt(value, source_tz):
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=source_tz).astimezone(timezone.get_current_timezone())
        except ValueError:
            pass
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

    def handle(self, *args, **options):
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
        all_notes = []
        per_page = 100
        for page in range(1, 501):
            query = urllib.parse.urlencode([
                ('page', page),
                ('on_page', per_page),
                ('filter[date_from]', '2000-01-01'),
                ('filter[date_to]', '2035-12-31'),
            ])
            payload = _request_json(f'{NOTES_URL}?{query}', headers=headers)
            items = _items_from_page(payload)
            all_notes.extend(item for item in items if isinstance(item, dict))
            total_pages = _total_pages(payload)
            if (total_pages and page >= total_pages) or len(items) < per_page:
                break

        ariane = StaffMember.objects.filter(display_name='Frau Ariane Regaei').order_by('pk').first()
        if ariane is None:
            raise CommandError('Frau Ariane Regaei was not found; refusing to import SimplyBook notes elsewhere.')

        source_tz = ZoneInfo('Europe/Berlin')
        seen_markers = set()
        created = 0
        updated = 0
        skipped = 0

        with transaction.atomic():
            for row in all_notes:
                note_id = row.get('id')
                if note_id in (None, ''):
                    skipped += 1
                    continue
                starts_at = _parse_dt(row.get('start_date_time') or row.get('from'), source_tz)
                ends_at = _parse_dt(row.get('end_date_time') or row.get('to'), source_tz)
                if not starts_at or not ends_at or ends_at <= starts_at:
                    skipped += 1
                    continue

                marker = _marker(note_id)
                seen_markers.add(marker)
                blocked = bool(row.get('time_blocked'))
                prefix = '[BLOCKNOTE][STAFF]' if blocked else '[NOTE][STAFF]'
                text = _clean_text(row.get('note')) or ('Gesperrt' if blocked else 'Notiz')
                max_text = max(1, 160 - len(prefix) - len(marker) - 2)
                reason = f'{prefix} {text[:max_text]}{marker}'

                item = BlockedPeriod.objects.filter(staff=ariane, reason__endswith=marker).order_by('pk').first()
                if item:
                    changed = item.starts_at != starts_at or item.ends_at != ends_at or item.reason != reason
                    if changed:
                        item.starts_at = starts_at
                        item.ends_at = ends_at
                        item.reason = reason
                        item.save(update_fields=['starts_at', 'ends_at', 'reason'])
                        updated += 1
                else:
                    BlockedPeriod.objects.create(staff=ariane, starts_at=starts_at, ends_at=ends_at, reason=reason)
                    created += 1

            stale = []
            for item in BlockedPeriod.objects.filter(staff=ariane, reason__contains=MARKER_SEP):
                reason = item.reason or ''
                marker_start = reason.rfind(MARKER_SEP, 0, max(0, len(reason) - 1))
                marker = reason[marker_start:] if marker_start >= 0 else ''
                if marker and marker not in seen_markers:
                    stale.append(item.pk)
            deleted = len(stale)
            if stale:
                BlockedPeriod.objects.filter(pk__in=stale).delete()

        self.stdout.write('SIMPLYBOOK_NOTES_SYNC_JSON=' + json.dumps({
            'source_notes': len(all_notes),
            'created': created,
            'updated': updated,
            'deleted': deleted,
            'skipped': skipped,
            'owner': ariane.display_name,
        }, sort_keys=True))
        self.stdout.write(self.style.SUCCESS('SimplyBook calendar notes synchronized to Frau Ariane Regaei.'))
