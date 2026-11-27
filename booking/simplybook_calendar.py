"""Source-first notes and blocked time for the verified Ariane provider."""
import hashlib
import json
import os
import urllib.parse
from threading import Lock
from time import monotonic
from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from .block_conflict_alerts import resolve_block_conflicts
from .clinical_time import clinic_localtime, parse_appointment_start
from .models import Appointment, BlockedPeriod, ExternalSyncState, SimplyBookCalendarRevision, StaffMember
from .simplybook_outbound import ARIANE, UNIT_ID, SOURCE_AVAILABILITY_ERRORS, _dt, _source_bookings, as_bool, session, source_credential_values

WRITE_STATE = 'simplybook-calendar-write'
# Build 69 forwards the numeric entry ID instead of a separate revision. A
# distinct, versioned action ID makes stale submissions fail on both platforms.
ACTION_ID_BASE = 1 << 50
_token_lock = Lock()
_token_cache = {}


class CalendarSourceConflict(ValueError):
    pass


def notes_enabled():
    return os.getenv('SIMPLYBOOK_CALENDAR_WRITEBACK_ENABLED') == '1'


def source_staff(staff):
    return staff.display_name == ARIANE and staff.active


def source_revision(block):
    if not source_staff(block.staff) or block.starts_at <= timezone.now():
        return None
    start, end = clinic_localtime(block.starts_at), clinic_localtime(block.ends_at)
    if start.date() != end.date() or any(t.minute % 15 or t.second or t.microsecond for t in (start, end)):
        return None
    try:
        return block.simplybook_revision
    except ObjectDoesNotExist:
        return None


def _note_id(value):
    text = str(value)
    if not text.isascii() or not text.isdecimal() or not 0 < len(text) <= 18 or text[0] == '0':
        raise CalendarSourceConflict('SimplyBook hat keinen eindeutigen Kalendereintrag geliefert.')
    return int(text)


def note_fields(row):
    if (not isinstance(row, dict) or row.get('mode') != 'provider'
            or str(row.get('provider_id')) != str(UNIT_ID)
            or row.get('service_id') not in (None, '', 0, '0')):
        raise CalendarSourceConflict('Dieser Eintrag gilt außerhalb von Arianes SimplyBook-Kalender.')
    start = parse_appointment_start(row.get('start_date_time') or row.get('from'))
    end = parse_appointment_start(row.get('end_date_time') or row.get('to'))
    note = row.get('note')
    blocked = str(row.get('time_blocked')).strip().lower()
    if (not start or not end or end <= start or not isinstance(note, str)
            or blocked not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}):
        raise CalendarSourceConflict('SimplyBook hat unvollständige Kalenderdaten geliefert.')
    return _payload(start, end, note, as_bool(row['time_blocked']), _note_id(row.get('note_type_id')))


def _payload(start, end, note, blocked, note_type):
    def wall_time(value):
        return clinic_localtime(value).strftime('%Y-%m-%d %H:%M:%S')
    return {
        'provider_id': UNIT_ID, 'mode': 'provider', 'note_type_id': note_type,
        'start_date_time': wall_time(start), 'end_date_time': wall_time(end),
        'note': note, 'time_blocked': blocked,
    }


def _digest(fields):
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def record_revision(block, row):
    try:
        fields = note_fields(row)
        source_id = _note_id(row.get('id'))
    except CalendarSourceConflict:
        SimplyBookCalendarRevision.objects.filter(block=block).delete()
        return None
    note = fields['note']
    if len(note) > 120 or note != ' '.join(note.split()):
        SimplyBookCalendarRevision.objects.filter(block=block).delete()
        return None
    digest = _digest(fields)
    existing = SimplyBookCalendarRevision.objects.filter(block=block).first()
    if existing and (existing.source_id, existing.digest) == (source_id, digest):
        return existing
    if existing:
        existing.delete()
    return SimplyBookCalendarRevision.objects.create(block=block, source_id=source_id, digest=digest)


def _notes_session():
    from .management.commands.sync_simplybook_notes import AUTH_URL, NOTES_URL, _request_json
    credentials = source_credential_values()
    company, user, password = (credentials[key] for key in (
        'SIMPLYBOOK_COMPANY_LOGIN', 'SIMPLYBOOK_USER_LOGIN', 'SIMPLYBOOK_USER_PASSWORD',
    ))
    if not all((company, user, password)):
        raise CalendarSourceConflict('Der Zugang zum SimplyBook-Kalender fehlt.')
    key = company, user
    with _token_lock:
        token, expires = _token_cache.get(key, (None, 0))
        if expires <= monotonic():
            auth = _request_json(AUTH_URL, method='POST', payload={
                'company': company, 'login': user, 'password': password,
            }, timeout=15)
            token = auth.get('token') if isinstance(auth, dict) else None
            if not token:
                raise CalendarSourceConflict('SimplyBook konnte den Kalenderzugang nicht bestätigen.')
            _token_cache[key] = token, monotonic() + 180
    headers = {'X-Company-Login': company, 'X-Token': token}

    def call(path='', **kwargs):
        try:
            return _request_json(NOTES_URL + path, headers=headers, timeout=15, **kwargs)
        except CommandError as exc:
            if str(exc) == 'SimplyBook notes HTTP 401':
                with _token_lock:
                    if _token_cache.get(key, (None,))[0] == token:
                        _token_cache.pop(key, None)
            raise
    return call


def _note(call, source_id):
    try:
        row = call(f'/{source_id}')
    except CommandError as exc:
        if str(exc) == 'SimplyBook notes HTTP 404':
            return None
        raise
    if not isinstance(row, dict) or _note_id(row.get('id')) != source_id:
        raise CalendarSourceConflict('SimplyBook hat einen anderen Kalendereintrag geliefert.')
    return row


def _check_bookings(staff, start, end):
    if Appointment.objects.filter(staff=staff, status__in=['new', 'confirmed'],
                                  starts_at__lt=end, ends_at__gt=start).exists():
        raise CalendarSourceConflict('In diesem Zeitraum gibt es bereits einen Termin.')
    for row in _source_bookings(session(), start, end):
        if str(row.get('unit_id')) != str(UNIT_ID):
            continue
        starts_at = _dt(row.get('start_date_time') or row.get('start_date'))
        ends_at = _dt(row.get('end_date_time') or row.get('end_date'))
        if not starts_at or not ends_at or starts_at < end and ends_at > start:
            raise CalendarSourceConflict('SimplyBook hat in diesem Zeitraum einen Termin.')


def _existing_match(call, desired):
    from .management.commands.sync_simplybook_notes import _items_from_page, _total_pages
    day = desired['start_date_time'].split(' ', 1)[0]
    query = urllib.parse.urlencode({'page': 1, 'on_page': 100, 'filter[search]': desired['note'],
                                    'filter[date_from]': day, 'filter[date_to]': day})
    response = call('?' + query)
    rows = _items_from_page(response)
    if (_total_pages(response) or 1) > 1 or len(rows) >= 100:
        raise CalendarSourceConflict('SimplyBook hat zu viele mögliche passende Einträge geliefert.')
    matches = []
    for row in rows:
        try:
            fields = note_fields(row)
        except CalendarSourceConflict:
            continue
        if fields == desired:
            matches.append(_note_id(row.get('id')))
    if len(matches) > 1:
        raise CalendarSourceConflict('Der Kalendereintrag ist in SimplyBook mehrfach vorhanden.')
    return matches[0] if matches else None


def _local_note(staff, row, block=None):
    from .management.commands.sync_simplybook_notes import _marker
    fields = note_fields(row)
    start = parse_appointment_start(fields['start_date_time'])
    end = parse_appointment_start(fields['end_date_time'])
    marker = _marker(_note_id(row.get('id')))
    prefix = '[BLOCKNOTE][STAFF]' if fields['time_blocked'] else '[NOTE][STAFF]'
    text = fields['note'] or ('Gesperrt' if fields['time_blocked'] else 'Notiz')
    reason = f'{prefix} {text[:160 - len(prefix) - len(marker) - 1]}{marker}'
    if block is None:
        block = BlockedPeriod.objects.filter(staff=staff, reason__endswith=marker).first() or BlockedPeriod(staff=staff)
    if block.pk and (block.starts_at != start or block.ends_at != end or not fields['time_blocked']):
        resolve_block_conflicts(block)
    block.starts_at, block.ends_at, block.reason = start, end, reason
    block.save()
    revision = record_revision(block, row)
    if not revision:
        raise CalendarSourceConflict('SimplyBook hat den Kalendereintrag in einem unerwarteten Format gespeichert.')
    return block.pk, ACTION_ID_BASE + revision.pk


def mutate_note(staff_id, operation, *, revision_id=None, start=None, end=None, text='', blocked=False,
                check_replay=None, save_receipt=None):
    """Return only confirmed mutations. An uncertain write quarantines the provider."""
    if not notes_enabled() or operation not in {'create', 'update', 'delete'}:
        raise CalendarSourceConflict('Die SimplyBook-Kalenderänderung ist derzeit nicht verfügbar.')
    if operation != 'delete':
        if not start or not end or not timezone.now() < start < end:
            raise CalendarSourceConflict('Bitte einen zukünftigen Zeitraum auswählen.')
        if clinic_localtime(start).date() != clinic_localtime(end).date():
            raise CalendarSourceConflict('Bitte einen Zeitraum innerhalb eines Tages auswählen.')
        text = ' '.join(text.split())
        if len(text) > 120 or '\u2063' in text:
            raise CalendarSourceConflict('Bitte den Text der Notiz prüfen.')
        text = text or ('Gesperrt' if blocked else 'Notiz')

    claim = str(uuid4())
    pending = {'pending': claim, 'staff_id': staff_id, 'operation': operation, 'revision_id': revision_id}
    with transaction.atomic():
        state, _ = ExternalSyncState.objects.select_for_update().get_or_create(source=WRITE_STATE)
        previous = check_replay() if check_replay else None
        if previous is not None:
            return previous
        if state.metadata.get('pending'):
            raise CalendarSourceConflict('Eine ungeklärte SimplyBook-Änderung muss zuerst geprüft werden.')
        state.metadata = pending
        state.save(update_fields=['metadata'])

    attempted = False
    try:
        with transaction.atomic():
            state = ExternalSyncState.objects.select_for_update().get(source=WRITE_STATE)
            staff = StaffMember.objects.select_for_update().get(pk=staff_id)
            if not source_staff(staff) or state.metadata.get('pending') != claim:
                raise CalendarSourceConflict('Der Kalendereintrag gehört nicht zu Arianes SimplyBook-Kalender.')
            block = None
            call = _notes_session()
            if operation == 'create':
                row = call('/types/default')
                type_id = _note_id(row.get('id') if isinstance(row, dict) else None)
            else:
                revision = SimplyBookCalendarRevision.objects.select_related('block').filter(
                    pk=revision_id, block__staff=staff,
                ).first()
                if not revision or not source_revision(revision.block):
                    raise CalendarSourceConflict('Der Kalendereintrag wurde geändert. Bitte neu laden.')
                block = revision.block
                source_id = revision.source_id
                current = _note(call, source_id)
                if current is None or _digest(note_fields(current)) != revision.digest:
                    raise CalendarSourceConflict('Der Kalendereintrag wurde in SimplyBook geändert. Bitte neu laden.')
                type_id = _note_id(current.get('note_type_id'))

            if operation == 'delete':
                attempted = True
                call(f'/{source_id}', method='DELETE')
                if _note(call, source_id) is not None:
                    raise CalendarSourceConflict('SimplyBook hat die Löschung nicht bestätigt.')
                result = block.pk, ACTION_ID_BASE + revision.pk
                resolve_block_conflicts(block)
                block.delete()
            else:
                desired = _payload(start, end, text, blocked, type_id)
                if blocked:
                    _check_bookings(staff, start, end)
                if operation == 'create':
                    source_id = _existing_match(call, desired)
                    if source_id is None:
                        attempted = True
                        reply = call(method='POST', payload=desired)
                        source_id = _note_id(reply.get('id') if isinstance(reply, dict) else None)
                else:
                    # Re-read immediately before the write after any scheduling checks.
                    latest = _note(call, source_id)
                    if latest is None or _digest(note_fields(latest)) != revision.digest:
                        raise CalendarSourceConflict('Der Kalendereintrag wurde in SimplyBook geändert. Bitte neu laden.')
                    attempted = True
                    call(f'/{source_id}', method='PUT', payload=desired)
                verified = _note(call, source_id)
                if verified is None or note_fields(verified) != desired:
                    raise CalendarSourceConflict('SimplyBook hat die Änderung nicht bestätigt.')
                result = _local_note(staff, verified, block)

            if save_receipt:
                save_receipt(result)
            state.metadata = {}
            state.save(update_fields=['metadata'])
            return result
    except Exception as exc:
        if not attempted:
            ExternalSyncState.objects.filter(pk=state.pk, metadata=pending).update(metadata={})
        if isinstance(exc, CalendarSourceConflict):
            raise
        if isinstance(exc, SOURCE_AVAILABILITY_ERRORS + (CommandError,)):
            raise CalendarSourceConflict('SimplyBook konnte die Kalenderänderung nicht bestätigen.') from None
        raise
