import logging
from copy import copy
from time import monotonic, sleep
from datetime import timedelta
from uuid import uuid4
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import re

from django.db import transaction
from booking.clinical_time import add_elapsed, clinic_localdate, clinic_localtime
from booking.models import Appointment, Customer, Service, SimplyBookClientLink, StaffMember
from booking.services import available_slots
from booking.simplybook_outbound import (
    ARIANE, SERVICE_MAP, UNIT_ID, SyncConflict, _contact_matches, _dt, _verify_availability, _verify_readback, as_bool, session,
    source_slots, sync_existing,
)
from booking.simplybook_writeback import _additional_values, _verified_cancellation, change_locked
from booking.management.commands.sync_simplybook_notes import AUTH_URL, _request_json

logging.disable(logging.CRITICAL)
stage = 'rest_cleanup_access'
tag = uuid4().hex
email = 'esthetic-book-qa-' + tag + '@example.com'
os.environ['SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED'] = 'true'
item = customer = None
client_id = None
call = None
candidate_days = []
delete_client = None
try:
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    auth = globals().get('fixture_rest_auth') or _request_json(AUTH_URL, method='POST', payload={
        'company': company, 'login': os.environ['SIMPLYBOOK_USER_LOGIN'],
        'password': os.environ['SIMPLYBOOK_USER_PASSWORD'],
    }, timeout=12)
    headers = {'X-Company-Login': company, 'X-Token': auth['token'], 'Accept': 'application/json'}
    def delete_client(ident):
        endpoint = 'https://user-api-v2.simplybook.me/admin/clients/' + str(int(ident))
        for method in ('GET', 'DELETE', 'GET'):
            try:
                with urlopen(Request(endpoint, headers=headers, method=method), timeout=15) as response:
                    if method == 'GET':
                        record = json.load(response)
                        if int(record['id']) == ident and as_bool(record.get('is_deleted')):
                            return
                        if int(record['id']) != ident or str(record.get('email', '')).casefold() != email:
                            raise RuntimeError('client_cleanup_identity_mismatch')
            except HTTPError as exc:
                if exc.code != 404 or method != 'GET':
                    raise
                return
        raise RuntimeError('client_deletion_unverified')
    stage = 'slot_selection'
    call = session()
    staff = StaffMember.objects.get(display_name=ARIANE, active=True)
    first_day = clinic_localdate() + timedelta(days=5)
    last_day = first_day + timedelta(days=15)
    eligible_services = staff.services.filter(slug__in=SERVICE_MAP, active=True, bookable=True).exclude(
        slug='aesthetische-erstberatung').order_by('sort_order', 'pk')
    eligible = None
    for service in eligible_services:
        event = SERVICE_MAP[service.slug][0]
        matrix, blocks = source_slots(call, event, first_day.isoformat(), last_day.isoformat())
        for date, raw in sorted(matrix.items()):
            if date == '2026-12-30' or not raw:
                continue
            live = sorted(available_slots(service, staff, raw[0].date(), source_availability=(raw, blocks)))
            if len(live) < 2 or live[-1] < add_elapsed(live[0], service.reserved_duration):
                continue
            start, moved = live[0], live[-1]
            vendor_end = _dt(call('calculateEndTime', [start.strftime('%Y-%m-%d %H:%M:%S'), event, UNIT_ID, []]))
            if vendor_end is None or not add_elapsed(start, service.reserved_duration - timedelta(minutes=service.buffer_minutes)) <= vendor_end <= add_elapsed(start, service.reserved_duration):
                continue
            eligible = date
            break
        if eligible:
            break
    if not eligible:
        raise RuntimeError('two_isolated_bookable_slots_with_matching_durations_unavailable')
    candidate_days = [eligible]
    print('BOOKING_CONFIG_VERIFIED_SERVICE_EVENT=' + str(event), flush=True)
    assert not Customer.objects.filter(email__iexact=email).exists()
    assert call('getClientList', [email, None]) == []
    with transaction.atomic():
        StaffMember.objects.select_for_update().get(pk=staff.pk)
        assert not Appointment.objects.filter(staff=staff, status__in=['confirmed','new'],
            starts_at__lt=add_elapsed(start, service.reserved_duration), ends_at__gt=start).exists()
        customer = Customer.objects.create(first_name='Synthetic Book', last_name='QA '+tag,
            email=email, phone='+12025550141')
        item = Appointment.objects.create(customer=customer, staff=staff, service=service, source='app',
            status='new', returning_customer=False, returning_customer_answered=True, referral_source='Google',
            starts_at=start, ends_at=add_elapsed(start, service.reserved_duration),
            treatment_minutes_at_booking=service.duration_minutes, idempotency_key='qa-sb-'+tag)
    public_id, local_key = item.public_id, item.idempotency_key
    stage = 'booking_create'
    class Telemetry:
        def __call__(self, method, params):
            try:
                result = call(method, params)
            except Exception as exc:
                details = str(exc).lower()
                code = re.search(r'(?:failed:|http)\s*(-?\d+)', details)
                categories = [name for name in ('invalid', 'required', 'field', 'email', 'phone', 'permission', 'rate limit', 'timeframe', 'duration', 'available', 'payment', 'confirmation', 'parameter') if name in details]
                print('BOOK_VENDOR_ERROR=' + method + ':' + (code.group(1) if code else 'unknown') + ':' + ','.join(categories), flush=True)
                raise
            if method == 'book':
                print('BOOK_RESULT_IS_OBJECT=' + str(isinstance(result, dict)), flush=True)
                if isinstance(result, dict):
                    print('BOOK_RESULT_HAS_BOOKINGS=' + str(isinstance(result.get('bookings'), list)), flush=True)
                    print('BOOK_RESULT_REQUIRES_CONFIRMATION=' + str(as_bool(result.get('require_confirm'))), flush=True)
            return result
    result = sync_existing(item.pk, apply=True, call=Telemetry())
    item.refresh_from_db()
    client_id = int(item.simplybook_client_id)
    assert result['result'] == 'linked' and item.simplybook_booking_id and item.status == 'confirmed'
    assert (item.public_id, item.idempotency_key, item.starts_at) == (public_id, local_key, start)
    print('BOOK_CREATE_SOURCE_READBACK_AND_IDENTITIES=true', flush=True)
    stage = 'booking_reschedule'
    with transaction.atomic():
        StaffMember.objects.select_for_update().get(pk=staff.pk)
        locked = Appointment.objects.select_for_update().get(pk=item.pk)
        assert change_locked(locked, starts_at=moved, call=call)
    item.refresh_from_db()
    assert item.starts_at == moved and item.public_id == public_id
    print('BOOK_RESCHEDULE_SOURCE_READBACK=true', flush=True)
    stage = 'source_reschedule'
    target = copy(item)
    target.starts_at = start
    target.ends_at = add_elapsed(start, item.reserved_duration)
    source_id = int(item.simplybook_booking_id)
    remote = call('getBookingDetails', [source_id])
    additional = _additional_values(call, event, remote)
    source_end = add_elapsed(start, item.simplybook_remote_ends_at - item.starts_at)
    assert not _verify_availability(call, target, event, client_id, exclude_source_id=source_id, remote_end=source_end)
    a, b = clinic_localtime(start), clinic_localtime(source_end)
    call('editBook',[source_id,event,UNIT_ID,client_id,a.strftime('%Y-%m-%d'),a.strftime('%H:%M:%S'),
                     b.strftime('%Y-%m-%d'),b.strftime('%H:%M:%S'),int(remote.get('client_time_offset') or 0),additional])
    _verify_readback(call, source_id, target, event, client_id, remote_end=source_end)
    print('SOURCE_RESCHEDULE_CONFIRMED_WAITING_FOR_BOOK_TIMER=true', flush=True)
    stage = 'book_timer_mirror'
    deadline = monotonic() + 11 * 60
    while monotonic() < deadline:
        item.refresh_from_db()
        if item.starts_at == start:
            assert (item.public_id, item.idempotency_key, item.ends_at) == (public_id, local_key, target.ends_at)
            assert int(item.simplybook_booking_id) == source_id
            print('SOURCE_RESCHEDULE_MIRRORED_BY_LIVE_BOOK_TIMER=true', flush=True)
            break
        sleep(15)
    else:
        raise RuntimeError('book_timer_did_not_reconcile_fixture')
    stage = 'booking_cancel'
    with transaction.atomic():
        StaffMember.objects.select_for_update().get(pk=staff.pk)
        locked = Appointment.objects.select_for_update().get(pk=item.pk)
        assert change_locked(locked, cancel=True, call=call)
    item.refresh_from_db()
    assert item.status == 'cancelled'
    print('BOOK_CANCEL_SOURCE_READBACK=true', flush=True)
except Exception as exc:
    key = str(exc) if type(exc) is SyncConflict and str(exc).replace('_','').isalnum() else type(exc).__name__
    print('BOOK_PILOT_FAILED=' + stage + ':' + key, flush=True)
    failed = True
else:
    failed = False
try:
    if customer is not None and call is not None:
        matches = [r for r in call('getClientList', [email, None]) if _contact_matches(r, customer)]
        if len(matches) > 1:
            raise RuntimeError('ambiguous_fixture_client_cleanup')
        if matches:
            client_id = int(matches[0]['id'])
        if client_id:
            for date in candidate_days:
                rows = call('getBookings', [{'date_from': date, 'date_to': date, 'booking_type': 'all'}])
                if not isinstance(rows, list):
                    raise RuntimeError('unverified_fixture_booking_listing')
                for row in rows:
                    if str(row.get('client_id')) != str(client_id):
                        continue
                    ident = int(row['id'])
                    detail = call('getBookingDetails', [ident])
                    if str(detail.get('client_id')) != str(client_id) or str(detail.get('unit_id')) != str(UNIT_ID) or str(detail.get('event_id')) != str(event):
                        raise RuntimeError('booking_cleanup_identity_mismatch')
                    if not _verified_cancellation(call, item, ident, event, client_id):
                        call('cancelBooking', [ident])
                        if not _verified_cancellation(call, item, ident, event, client_id):
                            raise RuntimeError('booking_cleanup_unverified')
            delete_client(client_id)
        with transaction.atomic():
            if item is not None:
                item.delete()
            if client_id:
                SimplyBookClientLink.objects.filter(customer=customer, external_client_id=str(client_id)).delete()
            customer.delete()
        print('BOOK_PILOT_TEMPORARY_RECORDS_CLEANED=true', flush=True)
    else:
        print('BOOK_PILOT_NO_FIXTURE_CREATED=true', flush=True)
except Exception as exc:
    raise SystemExit('BOOK_PILOT_CLEANUP_REQUIRES_REVIEW=' + type(exc).__name__) from None
if failed:
    raise SystemExit(1)
