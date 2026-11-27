import logging
from django.core.management.base import CommandError
from datetime import timedelta
from uuid import UUID, uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from time import monotonic, sleep
import json
import os

from django.db import transaction
from booking.clinical_time import add_elapsed, clinic_localdate, clinic_localtime
from booking.models import Appointment, Customer, MobileStaffCommand, SimplyBookClientLink, StaffMember
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
mode = os.environ.get('UNIFIED_SYNTHETIC_ENTRYPOINT')
assert mode in {'public','customer'}
assert os.environ.get('SIMPLYBOOK_OUTBOUND_ENABLED') == '1'
assert os.environ.get('SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED', '').lower() == 'true'
test_admin = None
receipt = None
browser = None
item = customer = None
client_id = None
call = None
candidate_days = []
delete_client = None
try:
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    for attempt in range(3):
        try:
            auth = _request_json(AUTH_URL, method='POST', payload={
                'company': company, 'login': os.environ['SIMPLYBOOK_USER_LOGIN'],
                'password': os.environ['SIMPLYBOOK_USER_PASSWORD'],
            }, timeout=25)
            break
        except (CommandError, TimeoutError, OSError) as exc:
            if attempt == 2:
                text = str(exc).casefold()
                error = next((code for code in ('401','403','429','500','502','503','504') if 'http ' + code in text), '')
                print('SYNTHETIC_CLEANUP_AUTHORIZATION_PREFLIGHT_FAILED='+str(error or type(exc).__name__), flush=True)
                raise
            sleep(30 * (attempt + 1))
    headers = {'X-Company-Login': company, 'X-Token': auth['token'], 'Accept': 'application/json'}
    def retry_open(request):
        for attempt in range(3):
            try:
                return urlopen(request, timeout=30)
            except (TimeoutError, OSError) as exc:
                if isinstance(exc, HTTPError) or attempt == 2:
                    raise
                sleep(3)

    def delete_client(ident):
        endpoint = 'https://user-api-v2.simplybook.me/admin/clients/' + str(int(ident))
        for method in ('GET', 'DELETE', 'GET'):
            try:
                with retry_open(Request(endpoint, headers=headers, method=method)) as response:
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

    assert not Customer.objects.filter(email__iexact=email).exists()
    assert call('getClientList', [email, None]) == []
    customer = Customer.objects.create(first_name='Synthetic Book', last_name='QA '+tag,
        email=email, phone='+12025550141')
    browser = Client(HTTP_HOST='book.a-esthetic.de')
    stage = 'entrypoint'
    key = str(uuid4())
    appointment_data = {'staff_id':staff.pk, 'service_id':service.pk, 'starts_at':start.isoformat()}
    member = {'first_name':customer.first_name,'last_name':customer.last_name,'email':email,'phone':customer.phone}
    if mode == 'public':
        for _ in range(2):
            response = browser.post('/api/appointments/', data=json.dumps({
                **appointment_data, **member, 'cancellation_terms_accepted':True, 'privacy_accepted':True,
            }), content_type='application/json', secure=True, HTTP_IDEMPOTENCY_KEY=key)
            assert response.status_code in {200,201}
            assert response.json().get('ok') and response.json()['appointment']['status']=='new'
    else:
        with patch('booking.mobile_api._member', return_value=(member,None)), patch(
                'booking.mobile_api.sync_package', return_value={'ok':True,'package_used':False}):
            for _ in range(2):
                response = browser.post('/api/mobile/booking/', data=json.dumps(appointment_data),
                    content_type='application/json', secure=True, HTTP_IDEMPOTENCY_KEY=key)
                assert response.status_code in {200,201}
                assert response.json().get('ok') and response.json().get('external_confirmation_pending')
    item = Appointment.objects.get(customer=customer)
    assert (item.source, item.status, item.simplybook_sync_state) == (('web' if mode=='public' else 'app'),'new','queued')
    assert item.returning_customer_answered and not item.returning_customer and item.referral_source=='Google'
    assert item.simplybook_booking_id is None
    public_id, local_key = item.public_id, item.idempotency_key
    stage = 'timer_appointment_create'
    deadline = monotonic() + 11*60
    while monotonic() < deadline:
        item.refresh_from_db()
        if item.simplybook_sync_state == 'linked':
            break
        if item.simplybook_sync_state in {'blocked','review'}:
            raise SyncConflict('automated_reservation_requires_review')
        sleep(10)
    else:
        raise RuntimeError('live_timer_did_not_confirm_the_synthetic_booking')
    client_id = int(item.simplybook_client_id)
    source_id = int(item.simplybook_booking_id)
    assert item.status == 'confirmed'
    assert (item.public_id, item.idempotency_key, item.starts_at) == (public_id, local_key, start)
    _verify_readback(call, source_id, item, event, client_id)
    print('CUSTOMER_BOOKING_READBACK_VIA_PRODUCTION_TIMER=true',flush=True)
    stage = 'timer_reverse_cancellation'
    call('cancelBooking',[source_id])
    assert _verified_cancellation(call, item, source_id, event, client_id)
    deadline = monotonic() + 11*60
    while monotonic() < deadline:
        item.refresh_from_db()
        if item.status == 'cancelled':
            assert item.public_id == public_id and item.simplybook_booking_id == str(source_id)
            print('SOURCE_CANCELLATION_MIRRORED_VIA_PRODUCTION_TIMER=true',flush=True)
            break
        sleep(10)
    else:
        raise RuntimeError('live_timer_did_not_mirror_the_synthetic_cancellation')
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
            if receipt is not None and test_admin is not None:
                MobileStaffCommand.objects.filter(actor_id=test_admin.pk, key=receipt).delete()
            # The UUID-tagged fixture patient was created by this process.
            Appointment.objects.filter(customer=customer, idempotency_key=key).delete()
            if client_id:
                SimplyBookClientLink.objects.filter(customer=customer, external_client_id=str(client_id)).delete()
            customer.delete()
        if browser is not None and mode == 'web':
            browser.logout()
        if test_admin is not None:
            test_admin.delete()
        print('BOOK_PILOT_TEMPORARY_RECORDS_CLEANED=true', flush=True)
    else:
        print('BOOK_PILOT_NO_FIXTURE_CREATED=true', flush=True)
except Exception as exc:
    raise SystemExit('BOOK_PILOT_CLEANUP_REQUIRES_REVIEW=' + type(exc).__name__) from None
if failed:
    raise SystemExit(1)
