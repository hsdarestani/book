import logging
from datetime import timedelta
from uuid import uuid4

from django.core.management.base import CommandError
from django.utils import timezone
from booking.clinical_time import clinic_localdate, clinic_localtime
from booking.models import Appointment, BlockedPeriod, StaffMember
from booking.management.commands.sync_simplybook_notes import AUTH_URL, NOTES_URL, _items_from_page, _request_json
from booking.simplybook_outbound import ARIANE, SERVICE_MAP, UNIT_ID, session, source_slots
from urllib.parse import urlencode
import os

logging.disable(logging.CRITICAL)
stage = 'preflight'
remote_id = None
attempted = False
tag = 'Book synchronization QA ' + uuid4().hex
try:
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    stage = 'rest_auth'
    auth = globals().get('fixture_rest_auth') or _request_json(AUTH_URL, method='POST', payload={
        'company': company, 'login': os.environ['SIMPLYBOOK_USER_LOGIN'],
        'password': os.environ['SIMPLYBOOK_USER_PASSWORD'],
    }, timeout=12)
    headers = {'X-Company-Login': company, 'X-Token': auth['token']}

    def notes(path='', **kwargs):
        return _request_json(NOTES_URL + path, headers=headers, timeout=12, **kwargs)

    stage = 'booking_availability'
    call = session()
    event = SERVICE_MAP['aesthetische-erstberatung'][0]
    staff = StaffMember.objects.get(display_name=ARIANE, active=True)
    first_day = clinic_localdate() + timedelta(days=7)
    last_day = first_day + timedelta(days=13)
    matrix, reserved = source_slots(call, event, first_day.isoformat(), last_day.isoformat())
    candidates = [start for day in matrix.values() for start in sorted(day)]
    start = next(s for s in candidates if s.date() == (s + timedelta(minutes=30)).date()
                 and not any(a < s + timedelta(minutes=30) and b > s for a, b in reserved)
                 and not Appointment.objects.filter(staff=staff, status__in=['new', 'confirmed'],
                     starts_at__lt=s + timedelta(minutes=30), ends_at__gt=s).exists()
                 and not BlockedPeriod.objects.filter(staff=staff, starts_at__lt=s + timedelta(minutes=30),
                     ends_at__gt=s).exclude(reason__startswith='[NOTE]').exists())
    day = start.date().isoformat()
    stage = 'notes_default_type'
    note_type = int(notes('/types/default')['id'])
    def fmt(instant):
        return clinic_localtime(instant).strftime('%Y-%m-%d %H:%M:%S')
    def eligible():
        matrix, intervals = source_slots(call, event, day, day)
        return start in matrix.get(day, ()) and not any(a <= start < b for a,b in intervals)
    def lookup():
        query = urlencode({'page': 1, 'on_page': 100, 'filter[search]': tag,
                           'filter[date_from]': day, 'filter[date_to]': day})
        rows = _items_from_page(notes('?' + query))
        return [row for row in rows if row.get('note') == tag and str(row.get('provider_id')) == str(UNIT_ID)
                and row.get('start_date_time') == fmt(start)]
    def verify(expected):
        row = notes('/' + str(remote_id))
        if int(row['id']) != remote_id or any(str(row.get(k)) != str(expected[k]) for k in expected):
            raise RuntimeError('mismatch')
    assert eligible()
    payload = {'provider_id': UNIT_ID, 'mode': 'provider', 'note_type_id': note_type,
               'start_date_time': fmt(start), 'end_date_time': fmt(start + timedelta(minutes=15)),
               'note': tag, 'time_blocked': False}
    stage = 'create'
    try:
        attempted = True
        remote_id = int(notes(method='POST', payload=payload)['id'])
        verify(payload)
        assert eligible()
        print('VENDOR_NOTE_CREATE_READBACK_AND_AVAILABLE=true', flush=True)
        stage = 'block'
        payload = {**payload, 'end_date_time': fmt(start + timedelta(minutes=30)), 'time_blocked': True}
        notes('/' + str(remote_id), method='PUT', payload=payload)
        verify(payload)
        assert not eligible()
        print('VENDOR_NOTE_EDIT_AND_BLOCKED_SLOT=true', flush=True)
    finally:
        if attempted and remote_id is None:
            matches = lookup()
            if len(matches) == 1:
                remote_id = int(matches[0]['id'])
            elif matches:
                raise RuntimeError('ambiguous_cleanup')
        if remote_id is not None:
            row = notes('/' + str(remote_id))
            if row.get('note') != tag or str(row.get('provider_id')) != str(UNIT_ID):
                raise RuntimeError('invalid_cleanup_identity')
            notes('/' + str(remote_id), method='DELETE')
            try:
                notes('/' + str(remote_id))
            except CommandError as exc:
                if not str(exc).startswith('SimplyBook notes HTTP 404'):
                    raise
            else:
                raise RuntimeError('delete_not_confirmed')
            assert eligible()
            print('VENDOR_NOTE_DELETED_AND_SLOT_RESTORED=true', flush=True)
except Exception as exc:
    code = next((c for c in ('400','401','403','404','409','429','500')
                 if isinstance(exc, CommandError) and str(exc).startswith('SimplyBook notes HTTP '+c)), '')
    raise SystemExit('PILOT_FAILED=' + stage + ':' + type(exc).__name__ + ':' + code + (':rate_limited' if 'too many attempts' in str(exc).lower() else '')) from None
