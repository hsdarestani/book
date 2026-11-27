import json
import logging
import os
from datetime import timedelta
from urllib.parse import urlencode
from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings
from booking.clinical_time import clinic_localdate, clinic_localtime
from booking.management.commands.sync_simplybook_notes import Command as SyncNotes, _items_from_page
from booking.models import Appointment, BlockedPeriod, ExternalSyncState, MobileStaffCommand, SimplyBookCalendarRevision, StaffMember
from booking.simplybook_calendar import ACTION_ID_BASE, WRITE_STATE, _note, _notes_session, _payload, note_fields
from booking.simplybook_outbound import ARIANE, SERVICE_MAP, UNIT_ID, session, source_slots

logging.disable(logging.CRITICAL)
os.environ['SIMPLYBOOK_CALENDAR_WRITEBACK_ENABLED'] = '1'
tag = 'Book note QA ' + uuid4().hex
actor = 2147483647
keys = []
remote_ids = set()
web_admin = None
stage = 'preflight'
call = None
day = None
error = None
try:
    state, _ = ExternalSyncState.objects.get_or_create(source=WRITE_STATE)
    assert not state.metadata.get('pending')
    staff = StaffMember.objects.get(display_name=ARIANE, active=True)
    rpc = session()
    event = SERVICE_MAP['aesthetische-erstberatung'][0]
    begin = clinic_localdate() + timedelta(days=7)
    finish = begin + timedelta(days=13)
    matrix, reserved = source_slots(rpc, event, begin.isoformat(), finish.isoformat())
    placements = [start for values in matrix.values() for start in sorted(values)]
    start = next(s for s in placements if s.date() == (s + timedelta(minutes=30)).date()
                 and not any(a < s + timedelta(minutes=30) and b > s for a,b in reserved)
                 and not Appointment.objects.filter(staff=staff, status__in=['new','confirmed'],
                     starts_at__lt=s + timedelta(minutes=30), ends_at__gt=s).exists()
                 and not BlockedPeriod.objects.filter(staff=staff, starts_at__lt=s + timedelta(minutes=30),
                     ends_at__gt=s).exclude(reason__startswith='[NOTE]').exists())
    day = start.date().isoformat()
    end = start + timedelta(minutes=15)
    extended = start + timedelta(minutes=30)
    call = _notes_session()
    type_id = int(call('/types/default')['id'])
    native = Client(HTTP_HOST='book.a-esthetic.de')
    browser = Client(HTTP_HOST='book.a-esthetic.de')

    def available():
        matrix, intervals = source_slots(rpc, event, day, day)
        return start in matrix.get(day, ()) and not any(a <= start < b for a,b in intervals)

    def native_post(operation, **values):
        key = str(uuid4())
        keys.append(key)
        with patch('booking.mobile_staff_api._verify', return_value=({'role':'admin','id':actor},200)):
            return native.post('/api/mobile/staff/block/', data=json.dumps({
                'operation': operation, 'staff_id': staff.pk, 'key': key, **values,
            }), content_type='application/json', secure=True)

    def revision(action_id):
        return SimplyBookCalendarRevision.objects.select_related('block').get(pk=action_id - ACTION_ID_BASE)

    def import_note(note_id):
        with transaction.atomic():
            ExternalSyncState.objects.select_for_update().get(source=WRITE_STATE)
            SyncNotes()._sync(True, source_note_id=note_id, source=call)

    field_values = {'date':day, 'start':start.strftime('%H:%M'), 'end':end.strftime('%H:%M'), 'text':tag}
    assert available()
    stage = 'native_create'
    reply = native_post('create', kind='note', **field_values)
    if reply.status_code != 200:
        raise RuntimeError('native_create_http_' + str(reply.status_code))
    assert reply.json()['source_confirmed'] is True
    first_id = reply.json()['id']
    first = revision(first_id)
    note_id = first.source_id
    remote_ids.add(note_id)
    assert note_fields(_note(call, note_id)) == _payload(start, end, tag, False, type_id) and available()

    stage = 'native_edit'
    reply = native_post('update', id=first_id, kind='block',
                        **{**field_values, 'end':extended.strftime('%H:%M')})
    if reply.status_code != 200:
        raise RuntimeError('native_edit_http_' + str(reply.status_code))
    second_id = reply.json()['id']
    second = revision(second_id)
    assert first_id != second_id and first.block_id == second.block_id and second.source_id == note_id
    assert note_fields(_note(call,note_id)) == _payload(start, extended, tag, True, type_id) and not available()
    assert native_post('delete', id=first_id).status_code == 409

    stage = 'native_delete'
    assert native_post('delete', id=second_id).status_code == 200
    assert _note(call, note_id) is None and not BlockedPeriod.objects.filter(pk=first.block_id).exists() and available()
    print('LIVE_BOOK_NATIVE_NOTE_BLOCK_CREATE_EDIT_DELETE_AND_STALE_REJECTION=true', flush=True)

    stage = 'source_create'
    remote = call(method='POST', payload=_payload(start, end, tag, False, type_id))
    note_id = int(remote['id'])
    remote_ids.add(note_id)
    import_note(note_id)
    external = SimplyBookCalendarRevision.objects.get(source_id=note_id)
    assert note_fields(_note(call, note_id)) == _payload(start, end, tag, False, type_id) and available()

    stage = 'source_edit'
    call('/' + str(note_id), method='PUT', payload=_payload(start, extended, tag, True, type_id))
    import_note(note_id)
    edited = SimplyBookCalendarRevision.objects.select_related('block').get(source_id=note_id)
    assert edited.block_id == external.block_id and edited.pk != external.pk and not available()
    assert edited.block.starts_at == start and edited.block.ends_at == extended

    stage = 'web_edit'
    web_admin = get_user_model().objects.create(username='qa-calendar-'+uuid4().hex, is_staff=True)
    browser.force_login(web_admin)
    response = browser.post('/verwaltung/kalender/', {
        'action':'edit_calendar_item', 'staff_id':staff.pk, 'block_id':edited.block_id,
        'item_kind':'note', 'item_revision':edited.pk, 'item_scope':'staff',
        'item_date':day, 'item_start':start.strftime('%H:%M'), 'item_end':end.strftime('%H:%M'), 'item_text':tag,
    }, secure=True)
    assert response.status_code == 302 and 'notice=block-updated' in response['Location']
    assert note_fields(_note(call,note_id)) == _payload(start, end, tag, False, type_id) and available()

    stage = 'source_delete'
    call('/' + str(note_id), method='DELETE')
    import_note(note_id)
    assert _note(call,note_id) is None and not BlockedPeriod.objects.filter(pk=edited.block_id).exists()
    print('LIVE_SIMPLYBOOK_CREATE_EDIT_DELETE_MIRRORED_IN_BOOK_AND_WEB_EDIT_CONFIRMED=true', flush=True)
except Exception as exc:
    text = str(exc)
    outcome = text if text.startswith(('native_create_http_', 'native_edit_http_')) else type(exc).__name__
    error = 'LIVE_CALENDAR_ACCEPTANCE_FAILED='+stage+':'+outcome
finally:
    try:
        if call and day:
            query = urlencode({'page':1,'on_page':100,'filter[search]':tag,
                               'filter[date_from]':day,'filter[date_to]':day})
            for row in _items_from_page(call('?' + query)):
                if row.get('note') == tag and str(row.get('provider_id')) == str(UNIT_ID):
                    remote_ids.add(int(row['id']))
            for ident in remote_ids:
                row = _note(call, ident)
                if row:
                    assert row.get('note') == tag and str(row.get('provider_id')) == str(UNIT_ID)
                    call('/'+str(ident), method='DELETE')
                    assert _note(call, ident) is None
                import_note(ident)
            assert not BlockedPeriod.objects.filter(staff=staff, reason__contains=tag).exists()
            # This process is the only writer while the production gate is off. If
            # it had to clean up an uncertain write, the isolated fixture is gone.
            ExternalSyncState.objects.filter(source=WRITE_STATE).update(metadata={})
        MobileStaffCommand.objects.filter(actor_id=actor,key__in=keys).delete()
        if web_admin:
            browser.logout()
            web_admin.delete()
        print('LIVE_CALENDAR_SYNTHETIC_RECORDS_CLEANED=true', flush=True)
    except Exception as exc:
        raise SystemExit('LIVE_CALENDAR_CLEANUP_REQUIRES_REVIEW='+type(exc).__name__) from None
if error:
    raise SystemExit(error)
