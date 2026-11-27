import logging
import os
import re
from django.core.management.base import CommandError
from django.db import transaction
from booking.clinical_time import clinic_localtime
from booking.models import Appointment, SimplyBookClientLink
from booking.simplybook_outbound import ARIANE, SERVICE_MAP, UNIT_ID, _contact_matches, as_bool, session
from booking.management.commands.sync_simplybook_notes import AUTH_URL, _request_json

logging.disable(logging.CRITICAL)
stage = 'identify'
try:
    rows = list(Appointment.objects.select_related('customer', 'staff', 'service').filter(
        idempotency_key__startswith='qa-sb-', customer__first_name='Synthetic Book',
        customer__email__endswith='@example.com', customer__phone='+12025550141',
        staff__display_name=ARIANE, source='app', simplybook_booking_id__isnull=False,
    ))
    assert len(rows) == 1
    item = rows[0]
    customer = item.customer
    tag = item.idempotency_key.removeprefix('qa-sb-')
    assert re.fullmatch('[0-9a-f]{32}', tag) and customer.last_name == 'QA '+tag
    assert customer.email == 'esthetic-book-qa-'+tag+'@example.com'
    link = SimplyBookClientLink.objects.get(customer=customer)
    cid, remote_id = int(link.external_client_id), int(item.simplybook_booking_id)
    assert str(cid) == item.simplybook_client_id
    day = clinic_localtime(item.starts_at).date().isoformat()
    assert day != '2026-12-30'
    event = SERVICE_MAP[item.service.slug][0]
    call = session()
    stage = 'verify_source_identity'
    detail = call('getBookingDetails', [remote_id])
    assert all(str(detail.get(k)) == str(v) for k,v in
               {'id':remote_id, 'client_id':cid, 'unit_id':UNIT_ID, 'event_id':event}.items())
    fields = detail.get('additional_fields')
    print('BOOKING_SOURCE_EVENT=' + str(event), flush=True)
    print('ADDITIONAL_FIELDS_TYPE=' + type(fields).__name__, flush=True)
    samples = list(fields.values()) if isinstance(fields, dict) else fields if isinstance(fields, list) else []
    for value in samples[:6]:
        print('ADDITIONAL_ENTRY_TYPE=' + type(value).__name__, flush=True)
        if isinstance(value, dict):
            print('ADDITIONAL_ENTRY_KEYS=' + ','.join(sorted(k for k in value if k in ('name','title','type','field','id','values','value','label','required','service_id'))), flush=True)
    print('BOOKING_DETAIL_STATUS_FIELDS=' + ','.join(sorted(k for k in detail if k in ('is_confirm','is_confirmed','is_cancelled','is_canceled','status','approve_status'))), flush=True)
    def source_ids(kind):
        rows = call('getBookings', [{'date_from':day,'date_to':day,'booking_type':kind}])
        assert isinstance(rows, list)
        return {int(row['id']) for row in rows if str(row.get('id')) == str(remote_id)
                and str(row.get('client_id')) == str(cid)}
    stage = 'cancel_verified_source_fixture'
    if remote_id not in source_ids('cancelled'):
        assert remote_id in source_ids('non_cancelled')
        call('cancelBooking', [remote_id])
    assert remote_id in source_ids('cancelled') and remote_id not in source_ids('non_cancelled')
    print('SYNTHETIC_VENDOR_CANCELLATION_CONFIRMED=true', flush=True)
    stage = 'delete_verified_source_client'
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    auth = _request_json(AUTH_URL, method='POST', payload={'company':company,
        'login':os.environ['SIMPLYBOOK_USER_LOGIN'], 'password':os.environ['SIMPLYBOOK_USER_PASSWORD']}, timeout=20)
    headers = {'X-Company-Login':company,'X-Token':auth['token']}
    url = 'https://user-api-v2.simplybook.me/admin/clients/'+str(cid)
    def client():
        try:
            return _request_json(url, headers=headers, timeout=15)
        except CommandError as exc:
            if re.match(r'SimplyBook notes HTTP 404\b', str(exc)):
                return None
            raise
    remote = client()
    if remote is not None:
        assert int(remote['id']) == cid
        if not as_bool(remote.get('is_deleted')):
            assert _contact_matches(remote, customer)
            _request_json(url, method='DELETE', headers=headers, timeout=15)
        remote = client()
        assert remote is None or (int(remote['id']) == cid and as_bool(remote.get('is_deleted')))
    stage = 'delete_verified_local_fixture'
    with transaction.atomic():
        assert not customer.appointments.exclude(pk=item.pk).exists()
        item.delete()
        link.delete()
        customer.delete()
    print('SYNTHETIC_VENDOR_CLIENT_AND_LOCAL_FIXTURE_CLEANED=true', flush=True)
except Exception as exc:
    message = str(exc)
    code = re.search(r'HTTP (\d{3})', message)
    raise SystemExit('BOOK_FIXTURE_CLEANUP_BLOCKED='+stage+':'+type(exc).__name__+((':'+code.group(1)) if code else '')) from None
