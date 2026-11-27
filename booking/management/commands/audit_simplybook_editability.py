"""Private, read-only audit of existing SimplyBook entries through real HTTP.

Run on the authorized Book host in its ordinary application environment. Use an
administrator bearer obtained through the normal App sign-in. Never run this
against real data in public CI or print HTTP bodies, IDs, patient data or tokens.
"""
from collections import Counter, defaultdict
from copy import copy
from datetime import timedelta
from getpass import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from booking.clinical_time import clinic_localdate, clinic_localtime
from booking.models import Appointment, BlockedPeriod
from booking.simplybook_calendar import (
    CalendarSourceConflict, _digest, _note, _notes_session, note_fields,
    source_revision, source_staff,
)
from booking.simplybook_outbound import ARIANE, UNIT_ID, SOURCE_AVAILABILITY_ERRORS, _same_booking, as_bool, session
from booking.simplybook_writeback import _details, _identity, source_id, source_managed

APP = 'https://app.a-esthetic.de/api/mobile/staff/'
BOOK = 'https://book.a-esthetic.de/api/mobile/staff/'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_json(url, token=None, *, data=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(url, headers=headers, data=None if data is None else json.dumps(data).encode())
    try:
        with build_opener(NoRedirect).open(request, timeout=25) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise CommandError('HTTP response exceeded the audit limit.')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise CommandError('Unexpected HTTP response shape.')
            return result
    except HTTPError as exc:
        raise CommandError(f'Authenticated HTTP request failed: {exc.code}.') from None
    except (URLError, OSError, ValueError):
        raise CommandError('Authenticated HTTP request could not be verified.') from None


def appointment_reason(item):
    """Local eligibility gates, independent of a feature-flag override."""
    if item.staff.display_name != ARIANE or not item.staff.active:
        return 'provider_out_of_scope'
    if item.status != 'confirmed':
        return 'not_confirmed'
    if item.simplybook_sync_state not in {'', 'linked'}:
        return 'source_sync_not_ready'
    if source_id(item) is None:
        return 'source_booking_id_missing'
    return None


def note_source_id(item):
    if not item.simplybook_managed:
        return None
    marker = item.reason[:-1].rpartition('\u2063')[2]
    value = int(marker.replace('\u200b', '0').replace('\u200c', '1'), 2)
    return value if 0 < value < 10**18 else None


def note_reason(item):
    if not source_staff(item.staff):
        return 'provider_out_of_scope'
    start, end = clinic_localtime(item.starts_at), clinic_localtime(item.ends_at)
    if start.date() != end.date():
        return 'cross_day_interval'
    if any(t.minute % 15 or t.second or t.microsecond for t in (start, end)):
        return 'interval_not_quarter_hour'
    if not source_revision(item):
        return 'source_revision_missing'
    return None


def verify_appointment(item, call):
    if source_id(item) is None:
        return 'source_booking_id_missing'
    try:
        remote = _details(call, source_id(item))
        event, client = _identity(item, remote)
        expected = copy(item)
        expected.ends_at = item.simplybook_remote_ends_at or item.ends_at
        if not _same_booking(remote, expected, event, client):
            return 'source_booking_changed'
        if (remote.get('invoice_id') not in (None, 0, '0', '')
                or remote.get('invoice_payment_received') not in (None, 0, '0', '')
                or as_bool(remote.get('deposit_is_enabled'))
                or remote.get('price') not in (None, {}, [], '')
                or remote.get('promo') not in (None, {}, [], '')
                or remote.get('batch_id') not in (None, 0, '0', '')):
            return 'source_payment_requires_review'
        return 'verified'
    except SOURCE_AVAILABILITY_ERRORS as exc:
        # Only publish a finite allowlist of diagnostic categories.
        code = str(exc)
        return code if code in {
            'source_service_mismatch', 'source_client_not_verified',
            'source_client_not_unique', 'source_identity_unverified',
            'source_booking_readback_mismatch',
        } else 'source_readback_unverified'


def verify_note(item, call):
    ident = note_source_id(item)
    if ident is None:
        return 'source_note_id_missing'
    try:
        remote = _note(call, ident)
        if remote is None:
            return 'source_note_not_found'
        if (remote.get('mode') != 'provider' or str(remote.get('provider_id')) != str(UNIT_ID)
                or remote.get('service_id') not in (None, '', 0, '0')):
            return 'source_scope_not_supported'
        fields = note_fields(remote)
        if len(fields['note']) > 120 or fields['note'] != ' '.join(fields['note'].split()):
            return 'source_text_not_losslessly_representable'
        revision = source_revision(item)
        if not revision:
            return 'source_revision_missing_with_valid_source'
        if revision.source_id != ident or revision.digest != _digest(fields):
            return 'source_revision_mismatch'
        return 'verified'
    except (SOURCE_AVAILABILITY_ERRORS + (CommandError, CalendarSourceConflict)):
        return 'source_readback_unverified'


def calendar_index(payload, kind):
    items = payload.get('appointments' if kind == 'appointment' else 'blocks')
    if not isinstance(items, list):
        raise CommandError('Calendar HTTP response is incomplete.')
    result = {}
    for item in items:
        ident = item.get('id') if kind == 'appointment' else item.get('record_id', item.get('id'))
        if ident in result:
            raise CommandError('Calendar HTTP response contains duplicate local identities.')
        result[ident] = item
    return result


def http_status(entry, kind):
    if entry is None:
        return 'not_returned'
    value = entry.get('source_editable' if kind == 'appointment' else 'editable')
    return 'editable' if value is True else 'read_only' if value is False else 'missing_eligibility'


class Command(BaseCommand):
    help = 'Privately audit all existing future source entries via Book and the live native App relay (GET only).'

    def add_arguments(self, parser):
        parser.add_argument('--use-bearer', action='store_true', help='Use an existing legitimately obtained bearer instead of ordinary login.')
        parser.add_argument('--target', action='append', default=[],
                            help='Private check: appointment@YYYY-MM-DDTHH:MM or block@YYYY-MM-DDTHH:MM (Berlin).')

    def handle(self, *args, **options):
        if not sys.stdin.isatty():
            raise CommandError('Run interactively in an authorized private terminal, never in CI.')
        if options['use_bearer']:
            token = getpass('Existing signed-in administrator bearer (not stored): ').strip()
        else:
            identifier = input('App administrator email or username: ').strip()
            password = getpass('App administrator password: ')
            login = get_json('https://app.a-esthetic.de/api/mobile/login/', data={'username': identifier, 'password': password})
            del password
            if login.get('account_type') != 'admin':
                raise CommandError('App sign-in did not resolve to administrator.')
            token = login.get('token', '')
            del login
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise CommandError('An existing administrator bearer is required.')
        identity = get_json(APP + 'session/', token)
        if identity.get('role') != 'admin' or not identity.get('id'):
            raise CommandError('The actual authenticated identity is not an administrator.')
        now = timezone.now()
        appointments = Appointment.objects.filter(starts_at__gt=now).filter(
            Q(idempotency_key__startswith='simplybook-') | Q(simplybook_booking_id__isnull=False)
            | ~Q(simplybook_sync_state='')
        ).select_related('staff', 'service', 'customer')
        blocks = BlockedPeriod.objects.filter(starts_at__gt=now).filter(
            Q(reason__contains='\u2063') | Q(simplybook_revision__isnull=False)
        ).select_related('staff', 'simplybook_revision')
        by_week = defaultdict(list)
        for kind, rows in (('appointment', appointments), ('block', blocks)):
            for item in rows.iterator():
                if not (source_managed(item) if kind == 'appointment' else item.simplybook_managed or getattr(item, 'simplybook_revision', None)):
                    continue
                day = clinic_localdate(item.starts_at)
                by_week[day - timedelta(days=day.weekday())].append((kind, item))
        source_calls = {}
        counts = defaultdict(Counter)
        targets = {str(index + 1): {'query': target, 'matches': []} for index, target in enumerate(options['target'])}
        for week, records in sorted(by_week.items()):
            indexes = {}
            if abs((week - clinic_localdate()).days) <= 730:
                path = 'calendar/?start=' + week.isoformat() + '&days=7'
                direct = get_json(BOOK + path, token)
                relay = get_json(APP + 'book/' + path, token)
                for kind in ('appointment', 'block'):
                    indexes[kind] = (calendar_index(direct, kind), calendar_index(relay, kind))
            for kind, item in records:
                bucket = kind if kind == 'appointment' else ('note' if item.reason.startswith('[NOTE]') else 'blocked_period')
                tally = counts[bucket]
                tally['total'] += 1
                local = appointment_reason(item) if kind == 'appointment' else note_reason(item)
                tally['local:' + (local or 'eligible')] += 1
                if kind not in indexes:
                    direct_status = relay_status = 'outside_http_calendar_range'
                else:
                    direct_index, relay_index = indexes[kind]
                    direct_entry, relay_entry = direct_index.get(item.pk), relay_index.get(item.pk)
                    direct_status, relay_status = http_status(direct_entry, kind), http_status(relay_entry, kind)
                tally['book:' + direct_status] += 1
                tally['relay:' + relay_status] += 1
                if direct_status != relay_status:
                    tally['book_relay_eligibility_mismatch'] += 1
                if kind not in source_calls:
                    try:
                        source_calls[kind] = session() if kind == 'appointment' else _notes_session()
                    except (SOURCE_AVAILABILITY_ERRORS + (CommandError,)):
                        source_calls[kind] = None
                call = source_calls[kind]
                verified = ('source_session_unavailable' if call is None else
                            verify_appointment(item, call) if kind == 'appointment' else verify_note(item, call))
                tally['source:' + verified] += 1
                if relay_status == 'editable' and (local is not None or verified != 'verified'):
                    tally['advertised_editable_but_not_verified'] += 1
                if relay_status == 'read_only' and local is None and verified == 'verified':
                    tally['verified_source_but_relay_read_only'] += 1
                key = kind + '@' + clinic_localtime(item.starts_at).strftime('%Y-%m-%dT%H:%M')
                if item.staff.display_name == ARIANE:
                    for target in targets.values():
                        if target['query'] == key:
                            target['matches'].append({'local': local or 'eligible', 'source': verified,
                                                      'book': direct_status, 'relay': relay_status})
        # This is diagnostic evidence, NOT a release acceptance result. Real
        # record identities and all response bodies remain on the private host.
        self.stdout.write(json.dumps({'authenticated_role': 'admin', 'records': counts,
                                      'target_results': {index: value['matches'] for index, value in targets.items()}},
                                     sort_keys=True))
